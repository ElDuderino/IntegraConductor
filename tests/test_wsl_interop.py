"""The WSL -> Windows launcher, exercised with a stand-in adapter executable.

No Windows process is started: a small Python script plays the adapter so the
real subprocess path (argument array, stdin JSON, stdout parsing, timeouts) runs.
"""

from __future__ import annotations

import json
import stat
import sys
import threading

import pytest

from integra7_conductor.errors import Integra7Error
from integra7_conductor.midi import windows_adapter, wsl_interop
from integra7_conductor.midi.backend import hardware_lock, send_step
from integra7_conductor.midi.wsl_interop import WindowsBackend

FAKE_ADAPTER = """#!{python}
import json, sys, time
request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
mode = {mode!r}
if mode == "echo":
    print("stray log line that is not JSON")
    print(json.dumps({{"ok": True, "data": {{"echo": request, "argv": sys.argv[1:]}}}}))
elif mode == "error":
    print(json.dumps({{"ok": False, "error": {{"code": "PORT_OPEN_FAILED",
          "message": "busy", "details": {{"port": "INTEGRA-7 1"}}, "hint": "close the DAW"}}}}))
    sys.exit(1)
elif mode == "garbage":
    sys.stderr.write("Traceback: boom\\n")
    print("not json at all")
    sys.exit(3)
elif mode == "hang":
    time.sleep(30)
"""


def fake_adapter(tmp_path, mode: str) -> str:
    folder = tmp_path / "Program Files" / "it's \"here\""  # spaces, apostrophe, quotes
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"adapter {mode}.exe"
    path.write_text(FAKE_ADAPTER.format(python=sys.executable, mode=mode), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_request_survives_quotes_unicode_and_paths_with_spaces(tmp_path):
    backend = WindowsBackend(windows_adapter_exe=fake_adapter(tmp_path, "echo"))
    tricky = "Comp' \"Steel\" & Sawﬂutter; $(rm -rf ~) %PATH% `x`"
    data = backend.call({"op": "ports", "note": tricky})
    assert data["echo"]["note"] == tricky  # byte-for-byte: never passed through a shell
    assert data["argv"] == []


def test_command_is_an_argument_array_not_a_shell_string():
    cmd = wsl_interop.build_command(
        "/mnt/c/Program Files/Python 3.12/python.exe",
        r"C:\Users\O'Brien\my repo\windows_adapter.py",
    )
    assert cmd == [
        "/mnt/c/Program Files/Python 3.12/python.exe",
        "-X",
        "utf8",
        r"C:\Users\O'Brien\my repo\windows_adapter.py",
    ]
    assert wsl_interop.build_command("/mnt/c/tools/adapter.exe", None) == [
        "/mnt/c/tools/adapter.exe"
    ]


def test_windows_python_path_is_translated_with_wslpath(tmp_path, monkeypatch):
    exe = tmp_path / "python.exe"
    exe.write_text("")
    calls = []

    def fake_wslpath(flag, path):
        calls.append((flag, path))
        return str(exe) if flag == "-u" else r"\\wsl.localhost\Ubuntu\repo\windows_adapter.py"

    monkeypatch.setattr(wsl_interop, "wslpath", fake_wslpath)
    backend = WindowsBackend(windows_python=r"C:\Users\Jo Smith\venv\Scripts\python.exe")
    assert backend.command() == [
        str(exe), "-X", "utf8", r"\\wsl.localhost\Ubuntu\repo\windows_adapter.py",
    ]
    assert calls[0] == ("-u", r"C:\Users\Jo Smith\venv\Scripts\python.exe")
    assert calls[1] == ("-w", str(wsl_interop.adapter_script_path()))


def test_path_classification():
    assert wsl_interop.is_windows_path(r"C:\Python312\python.exe")
    assert wsl_interop.is_windows_path("C:/Python312/python.exe")
    assert wsl_interop.is_windows_path(r"\\wsl.localhost\Ubuntu\home")
    assert not wsl_interop.is_windows_path("/mnt/c/Python312/python.exe")


def test_adapter_error_envelope_becomes_structured_error(tmp_path):
    backend = WindowsBackend(windows_adapter_exe=fake_adapter(tmp_path, "error"))
    with pytest.raises(Integra7Error) as info:
        backend.transact([send_step("INTEGRA-7", [b"\xc0\x00"])])
    assert info.value.code == "PORT_OPEN_FAILED"
    assert info.value.details == {"port": "INTEGRA-7 1"}
    assert info.value.hint == "close the DAW"


def test_non_json_output_is_reported_with_stderr(tmp_path):
    backend = WindowsBackend(windows_adapter_exe=fake_adapter(tmp_path, "garbage"))
    with pytest.raises(Integra7Error) as info:
        backend.list_ports()
    assert info.value.code == "ADAPTER_FAILED"
    assert "boom" in info.value.details["stderr"]


def test_hung_adapter_times_out(tmp_path):
    backend = WindowsBackend(windows_adapter_exe=fake_adapter(tmp_path, "hang"), timeout_s=0.5)
    with pytest.raises(Integra7Error) as info:
        backend.list_ports()
    assert info.value.code == "DEVICE_TIMEOUT"


def test_missing_executable(tmp_path):
    backend = WindowsBackend(windows_adapter_exe=str(tmp_path / "nope.exe"))
    with pytest.raises(Integra7Error) as info:
        backend.list_ports()
    assert info.value.code == "ADAPTER_NOT_FOUND"


def test_no_python_configured_and_none_discovered(monkeypatch):
    monkeypatch.setattr(wsl_interop, "discover_windows_python", lambda: None)
    with pytest.raises(Integra7Error) as info:
        WindowsBackend().list_ports()
    assert info.value.code == "ADAPTER_NOT_FOUND"
    assert "setup-windows.ps1" in info.value.hint


def test_interop_disabled_is_diagnosed(tmp_path, monkeypatch):
    exe = fake_adapter(tmp_path, "echo")

    def refuse(*args, **kwargs):
        raise OSError(8, "Exec format error")

    monkeypatch.setattr(wsl_interop.subprocess, "run", refuse)
    monkeypatch.setattr(
        wsl_interop, "interop_status",
        lambda: {"registered": True, "enabled": False, "source": "test"},
    )
    with pytest.raises(Integra7Error) as info:
        WindowsBackend(windows_adapter_exe=exe).list_ports()
    assert info.value.code == "WINDOWS_INTEROP_UNAVAILABLE"
    assert "wsl.conf" in info.value.hint


def test_timeout_budget_includes_sleeps_and_reply_waits():
    backend = WindowsBackend(timeout_s=10)
    request = {"steps": [{"type": "sleep", "ms": 3000}, {"type": "request", "timeout_ms": 800}]}
    assert backend._budget_s(request) == pytest.approx(13.8)


def test_hardware_lock_serializes_and_times_out(tmp_path):
    lock = tmp_path / "hw.lock"
    held, release = threading.Event(), threading.Event()

    def holder():
        with hardware_lock(lock, 1):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert held.wait(5)
        with pytest.raises(Integra7Error) as info:
            with hardware_lock(lock, 0.2):
                pass
        assert info.value.code == "DEVICE_BUSY"
    finally:
        release.set()
        thread.join()
    with hardware_lock(lock, 0.2):  # free again
        pass


# ---- the adapter module itself (pure logic; runs under any Python) ----------

def test_adapter_port_resolution():
    outs = ["Microsoft GS Wavetable Synth 0", "INTEGRA-7 1", "INTEGRA-7 CTRL 2"]
    resolve = windows_adapter.resolve_port
    assert resolve("INTEGRA-7", outs, "output") == "INTEGRA-7 1"
    assert resolve("INTEGRA-7 CTRL", outs, "output") == "INTEGRA-7 CTRL 2"
    assert resolve("integra-7 ctrl 2", outs, "output") == "INTEGRA-7 CTRL 2"
    assert resolve("wavetable", outs, "output") == "Microsoft GS Wavetable Synth 0"
    with pytest.raises(windows_adapter.AdapterError) as info:
        resolve("INTEGRA", outs, "output")
    assert info.value.code == "PORT_AMBIGUOUS"
    with pytest.raises(windows_adapter.AdapterError) as info:
        resolve("JUPITER", outs, "output")
    assert info.value.code == "PORT_NOT_FOUND" and info.value.details["available"] == outs


@pytest.mark.parametrize(
    "message",
    [[], [0x40, 0, 0], [0xB0, 0x80, 0], [0xF0, 0x41, 0x10], [0xB0, 0, 0, 0], [0xC0, 300], "C0 00"],
)
def test_adapter_rejects_malformed_messages(message):
    response = windows_adapter.run_request(
        {"op": "transact", "steps": [{"type": "send", "port": "x", "messages": [message]}]},
        lambda: pytest.fail("ports must not be touched for an invalid request"),
    )
    assert response["ok"] is False and response["error"]["code"] == "INVALID_ARGUMENT"


def test_adapter_unknown_op_and_bad_request_shape():
    for request in ({"op": "format-disk"}, ["not", "a", "dict"], {"op": "transact", "steps": []}):
        response = windows_adapter.run_request(request, lambda: None)
        assert response["ok"] is False and response["error"]["code"] == "INVALID_ARGUMENT"


def test_adapter_main_reads_request_file_and_emits_ascii_json(tmp_path, capsys, monkeypatch):
    request = tmp_path / "req.json"
    request.write_text(json.dumps({"op": "nonsense ﬂ"}), encoding="utf-8")
    code = windows_adapter.main(["--request-file", str(request)])
    out = capsys.readouterr().out
    assert code == 1 and out.isascii()
    assert json.loads(out)["error"]["code"] == "INVALID_ARGUMENT"
    assert windows_adapter.main(["--bogus"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_adapter_source_has_no_package_imports():
    source = wsl_interop.adapter_script_path().read_text(encoding="utf-8")
    assert "from ." not in source and "integra7_conductor" not in source.split('"""', 2)[2]
