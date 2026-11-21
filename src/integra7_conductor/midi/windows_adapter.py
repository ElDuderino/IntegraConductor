#!/usr/bin/env python3
"""Standalone MIDI adapter. Runs under *Windows* Python (mido + python-rtmidi).

This file is executed by path, so it must not import the rest of the package and
must stay compatible with older Python 3 versions. It reads ONE JSON request
(stdin or --request-file), performs it with the MIDI port(s) held open for the
whole transaction, and writes ONE JSON object to stdout. Diagnostics go to stderr.

Requests:
  {"op": "ping"}
  {"op": "ports"}
  {"op": "transact", "input_port": "INTEGRA-7" | null, "steps": [
      {"type": "send", "port": "INTEGRA-7", "messages": [[176, 0, 89], ...]},
      {"type": "sleep", "ms": 150},
      {"type": "request", "port": "INTEGRA-7", "message": [240, ..., 247],
       "timeout_ms": 800, "quiet_ms": 60},
      {"type": "sequence", "port": "INTEGRA-7", "events": [
          {"t_ms": 0, "message": [144, 60, 90]}, {"t_ms": 500, "message": [128, 60, 0]}]}]}

A "sequence" step plays events at absolute offsets from the step's start, so
timing does not drift. Any note still sounding when a transaction ends or fails
is turned off in the cleanup path.

Native use on Windows:  python windows_adapter.py --ports

The same run_request() function drives the mock backend in tests, so the
note-off cleanup and port-resolution logic are exercised without hardware.
"""

from __future__ import annotations

import json
import re
import sys
import time

ADAPTER_VERSION = 1
MAX_TOTAL_SLEEP_MS = 10000
MAX_SEQUENCE_MS = 300000
_POLL_INTERVAL_S = 0.002
_INJECT_POLL_S = 0.12


class AdapterError(Exception):
    def __init__(self, code, message, details=None, hint=None):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.hint = hint

    def to_dict(self):
        out = {"code": self.code, "message": self.message}
        if self.details:
            out["details"] = self.details
        if self.hint:
            out["hint"] = self.hint
        return out


def _strip_index(name):
    # RtMidi on Windows appends the device index, e.g. "INTEGRA-7 1".
    return re.sub(r"\s+\d+$", "", name).strip().lower()


def resolve_port(requested, available, direction):
    """Map a configured name to exactly one real port name, or fail with candidates."""
    details = {"requested": requested, "direction": direction, "available": list(available)}
    if not requested:
        raise AdapterError("PORT_NOT_FOUND", "No %s port name configured" % direction, details)
    if requested in available:
        return requested
    want = requested.strip().lower()
    for matches in (
        [n for n in available if n.strip().lower() == want],
        [n for n in available if _strip_index(n) == _strip_index(requested)],
        [n for n in available if want in n.lower()],
    ):
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            details["candidates"] = matches
            raise AdapterError(
                "PORT_AMBIGUOUS",
                "MIDI %s port name %r matches several ports" % (direction, requested),
                details,
                "Configure the exact port name from `integra7 ports`.",
            )
    raise AdapterError(
        "PORT_NOT_FOUND",
        "MIDI %s port %r not found" % (direction, requested),
        details,
        "Check the USB cable, power, the Roland driver (USB Driver mode VENDER) and "
        "`integra7 ports`. Another program may also be holding the port.",
    )


class MidoIO(object):
    """Real MIDI I/O through mido's RtMidi backend."""

    def __init__(self):
        try:
            import mido
            import rtmidi  # noqa: F401  (fail early with a clear message)
        except ImportError as exc:
            raise AdapterError(
                "ADAPTER_DEPENDENCY_MISSING",
                "mido/python-rtmidi are not importable in this Python: %s" % exc,
                {"python": sys.executable},
                "Run scripts/setup-windows.ps1, or `pip install mido python-rtmidi` "
                "in this interpreter's environment.",
            )
        mido.set_backend("mido.backends.rtmidi")
        self._mido = mido

    def versions(self):
        import rtmidi

        return {
            "mido": getattr(self._mido, "__version__", None)
            or getattr(getattr(self._mido, "version", None), "version", None),
            "python_rtmidi": getattr(rtmidi, "__version__", None),
        }

    def list_ports(self):
        def unique(names):
            seen = []
            for n in names:
                if n not in seen:
                    seen.append(n)
            return seen

        return {
            "inputs": unique(self._mido.get_input_names()),
            "outputs": unique(self._mido.get_output_names()),
        }

    def open_output(self, name):
        mido = self._mido
        port = mido.open_output(name)

        class _Out(object):
            def send(self, data):
                port.send(mido.Message.from_bytes(list(data)))

            def close(self):
                port.close()

        return _Out()

    def open_input(self, name):
        port = self._mido.open_input(name)

        class _In(object):
            def poll(self):
                return [list(msg.bytes()) for msg in port.iter_pending()]

            def close(self):
                port.close()

        return _In()


class WinMMIO(object):
    """Windows Multimedia (winmm.dll) MIDI through ctypes: no third-party packages.

    Used automatically on Windows when mido/python-rtmidi cannot be imported (for
    example on a Python version python-rtmidi has no wheel for). Input collects
    SysEx only, by polling driver-filled buffers, which is all readback needs.
    """

    _SYSEX_BUFFERS = 4
    _SYSEX_BUFFER_SIZE = 2048
    _MHDR_DONE = 0x00000001

    def __init__(self):
        if sys.platform != "win32":
            raise AdapterError(
                "ADAPTER_DEPENDENCY_MISSING", "The WinMM MIDI fallback only exists on Windows"
            )
        import ctypes
        from ctypes import wintypes

        self._ct = ctypes
        self._mm = ctypes.WinDLL("winmm")
        ptr = ctypes.c_void_p

        class OutCaps(ctypes.Structure):
            _fields_ = [
                ("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT), ("szPname", wintypes.WCHAR * 32),
                ("wTechnology", wintypes.WORD), ("wVoices", wintypes.WORD),
                ("wNotes", wintypes.WORD), ("wChannelMask", wintypes.WORD),
                ("dwSupport", wintypes.DWORD),
            ]

        class InCaps(ctypes.Structure):
            _fields_ = [
                ("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT), ("szPname", wintypes.WCHAR * 32),
                ("dwSupport", wintypes.DWORD),
            ]

        class MidiHdr(ctypes.Structure):
            pass

        MidiHdr._fields_ = [
            ("lpData", ctypes.c_char_p), ("dwBufferLength", wintypes.DWORD),
            ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_size_t),
            ("dwFlags", wintypes.DWORD), ("lpNext", ctypes.POINTER(MidiHdr)),
            ("reserved", ctypes.c_size_t), ("dwOffset", wintypes.DWORD),
            ("dwReserved", ctypes.c_size_t * 8),
        ]
        self._OutCaps, self._InCaps, self._MidiHdr = OutCaps, InCaps, MidiHdr
        uint, size = wintypes.UINT, ctypes.c_size_t
        hdr_p = ctypes.POINTER(MidiHdr)
        for name, args in (
            ("midiOutGetDevCapsW", [size, ctypes.POINTER(OutCaps), uint]),
            ("midiInGetDevCapsW", [size, ctypes.POINTER(InCaps), uint]),
            ("midiOutOpen", [ctypes.POINTER(ptr), uint, size, size, wintypes.DWORD]),
            ("midiInOpen", [ctypes.POINTER(ptr), uint, size, size, wintypes.DWORD]),
            ("midiOutShortMsg", [ptr, wintypes.DWORD]),
            ("midiOutPrepareHeader", [ptr, hdr_p, uint]),
            ("midiOutUnprepareHeader", [ptr, hdr_p, uint]),
            ("midiOutLongMsg", [ptr, hdr_p, uint]),
            ("midiInPrepareHeader", [ptr, hdr_p, uint]),
            ("midiInUnprepareHeader", [ptr, hdr_p, uint]),
            ("midiInAddBuffer", [ptr, hdr_p, uint]),
            ("midiOutClose", [ptr]), ("midiOutReset", [ptr]),
            ("midiInStart", [ptr]), ("midiInReset", [ptr]), ("midiInClose", [ptr]),
        ):
            fn = getattr(self._mm, name)
            fn.argtypes = args
            fn.restype = uint

    def versions(self):
        return {"mido": None, "python_rtmidi": None, "midi_api": "winmm (ctypes fallback)"}

    def _names(self, count_fn, caps_fn, caps_type):
        ct = self._ct
        names = []
        for index in range(getattr(self._mm, count_fn)()):
            caps = caps_type()
            if getattr(self._mm, caps_fn)(index, ct.byref(caps), ct.sizeof(caps)) == 0:
                names.append(caps.szPname)
        return names

    def _raw_ports(self):
        return {
            "inputs": self._names("midiInGetNumDevs", "midiInGetDevCapsW", self._InCaps),
            "outputs": self._names("midiOutGetNumDevs", "midiOutGetDevCapsW", self._OutCaps),
        }

    def list_ports(self):
        # Device names can repeat; append the device index, as RtMidi does.
        raw = self._raw_ports()
        return {k: ["%s %d" % (n, i) for i, n in enumerate(v)] for k, v in raw.items()}

    def _check(self, code, what):
        if code != 0:
            raise OSError("%s failed with MMSYSERR %d" % (what, code))

    def _index(self, name, direction):
        return self.list_ports()[direction].index(name)

    def open_output(self, name):
        io, ct, mm = self, self._ct, self._mm
        handle = ct.c_void_p()
        io._check(mm.midiOutOpen(ct.byref(handle), io._index(name, "outputs"), 0, 0, 0),
                  "midiOutOpen")

        class _Out(object):
            def send(self, data):
                data = list(data)
                if data[0] != 0xF0:
                    word = data[0] | (data[1] << 8 if len(data) > 1 else 0)
                    word |= data[2] << 16 if len(data) > 2 else 0
                    io._check(mm.midiOutShortMsg(handle, word), "midiOutShortMsg")
                    return
                buf = ct.create_string_buffer(bytes(bytearray(data)), len(data))
                hdr = io._MidiHdr()
                hdr.lpData = ct.cast(buf, ct.c_char_p)
                hdr.dwBufferLength = len(data)
                size = ct.sizeof(hdr)
                io._check(mm.midiOutPrepareHeader(handle, ct.byref(hdr), size), "prepare")
                try:
                    io._check(mm.midiOutLongMsg(handle, ct.byref(hdr), size), "midiOutLongMsg")
                    deadline = time.time() + 2.0
                    while not hdr.dwFlags & io._MHDR_DONE and time.time() < deadline:
                        time.sleep(0.001)
                finally:
                    mm.midiOutUnprepareHeader(handle, ct.byref(hdr), size)

            def close(self):
                mm.midiOutReset(handle)
                mm.midiOutClose(handle)

        return _Out()

    def open_input(self, name):
        io, ct, mm = self, self._ct, self._mm
        handle = ct.c_void_p()
        io._check(mm.midiInOpen(ct.byref(handle), io._index(name, "inputs"), 0, 0, 0),
                  "midiInOpen")
        size = ct.sizeof(io._MidiHdr)
        buffers = []
        for _ in range(io._SYSEX_BUFFERS):
            buf = ct.create_string_buffer(io._SYSEX_BUFFER_SIZE)
            hdr = io._MidiHdr()
            hdr.lpData = ct.cast(buf, ct.c_char_p)
            hdr.dwBufferLength = io._SYSEX_BUFFER_SIZE
            io._check(mm.midiInPrepareHeader(handle, ct.byref(hdr), size), "midiInPrepareHeader")
            io._check(mm.midiInAddBuffer(handle, ct.byref(hdr), size), "midiInAddBuffer")
            buffers.append((buf, hdr))
        io._check(mm.midiInStart(handle), "midiInStart")

        class _In(object):
            def poll(self):
                out = []
                for buf, hdr in buffers:
                    if hdr.dwFlags & io._MHDR_DONE and hdr.dwBytesRecorded:
                        out.append(list(bytearray(buf.raw[: hdr.dwBytesRecorded])))
                        hdr.dwBytesRecorded = 0
                        mm.midiInAddBuffer(handle, ct.byref(hdr), size)
                return out

            def close(self):
                mm.midiInReset(handle)
                for _buf, hdr in buffers:
                    mm.midiInUnprepareHeader(handle, ct.byref(hdr), size)
                mm.midiInClose(handle)

        return _In()


def default_io():
    """mido/RtMidi when importable; otherwise the built-in WinMM fallback on Windows."""
    try:
        return MidoIO()
    except AdapterError:
        if sys.platform != "win32":
            raise
        return WinMMIO()


def _check_message(msg):
    if (
        not isinstance(msg, list)
        or not msg
        or any((not isinstance(b, int)) or isinstance(b, bool) or b < 0 or b > 255 for b in msg)
        or msg[0] < 0x80
        or any(b > 0x7F for b in msg[1:-1])
        or (msg[0] == 0xF0) != (msg[-1] == 0xF7)
        or (msg[0] != 0xF0 and (len(msg) > 3 or msg[-1] > 0x7F))
    ):
        raise AdapterError(
            "INVALID_ARGUMENT", "Malformed MIDI message in request", {"message": msg}
        )
    return msg


def _hex(msg):
    return " ".join("%02X" % b for b in msg)


def _transact(request, io_factory, sleep, clock):
    steps = request.get("steps")
    if not isinstance(steps, list) or not steps:
        raise AdapterError("INVALID_ARGUMENT", "transact needs a non-empty steps list")
    total_sleep = sum(int(s.get("ms", 0)) for s in steps if s.get("type") == "sleep")
    if total_sleep > MAX_TOTAL_SLEEP_MS:
        raise AdapterError("INVALID_ARGUMENT", "Total sleep exceeds %d ms" % MAX_TOTAL_SLEEP_MS)
    for step in steps:
        if step.get("type") == "send":
            for msg in step.get("messages", []):
                _check_message(msg)
        elif step.get("type") == "request":
            _check_message(step.get("message"))
        elif step.get("type") == "sequence":
            events = step.get("events")
            if not isinstance(events, list) or not events:
                raise AdapterError("INVALID_ARGUMENT", "sequence needs a non-empty events list")
            for event in events:
                t_ms = event.get("t_ms") if isinstance(event, dict) else None
                if isinstance(t_ms, bool) or not isinstance(t_ms, (int, float)) or not (
                    0 <= t_ms <= MAX_SEQUENCE_MS
                ):
                    raise AdapterError(
                        "INVALID_ARGUMENT", "sequence event t_ms must be 0-%d" % MAX_SEQUENCE_MS
                    )
                _check_message(event.get("message"))
        elif step.get("type") != "sleep":
            raise AdapterError("INVALID_ARGUMENT", "Unknown step type %r" % step.get("type"))

    # The request is fully validated before any MIDI library or port is touched.
    io = io_factory()
    available = io.list_ports()
    resolved = {}
    for step in steps:
        name = step.get("port")
        if step.get("type") in ("send", "request", "sequence") and name not in resolved:
            resolved[name] = resolve_port(name, available["outputs"], "output")

    outputs = {}
    inp = None
    input_info = {"requested": request.get("input_port"), "resolved": None, "error": None}
    sent = []  # type: list
    replies = []  # type: list
    # Entries are (requested port name, channel nibble, note).
    pending_notes = []  # type: list
    cleanup = []  # type: list
    sequences = []  # type: list
    try:
        for name, real in resolved.items():
            try:
                outputs[name] = io.open_output(real)
            except AdapterError:
                raise
            except Exception as exc:
                raise AdapterError(
                    "PORT_OPEN_FAILED",
                    "Could not open MIDI output %r: %s" % (real, exc),
                    {"port": real},
                    "Close other software using the port (DAW, editor) and retry.",
                )
        if any(s.get("type") == "request" for s in steps):
            try:
                real_in = resolve_port(request.get("input_port"), available["inputs"], "input")
                inp = io.open_input(real_in)
                input_info["resolved"] = real_in
            except AdapterError as exc:
                if request.get("input_required"):
                    raise
                input_info["error"] = exc.to_dict()
            except Exception as exc:
                if request.get("input_required"):
                    raise AdapterError("PORT_OPEN_FAILED", "Could not open MIDI input: %s" % exc)
                input_info["error"] = {"code": "PORT_OPEN_FAILED", "message": str(exc)}

        for index, step in enumerate(steps):
            kind = step["type"]
            if kind == "sleep":
                sleep(max(0, int(step.get("ms", 0))) / 1000.0)
            elif kind == "send":
                out = outputs[step["port"]]
                for msg in step["messages"]:
                    _send(out, msg, step["port"], resolved, sent, pending_notes)
            elif kind == "sequence":
                out = outputs[step["port"]]
                started = clock()
                played = 0
                inject = step.get("inject_file")
                inject_offset = 0
                injected = 0
                for event in sorted(step["events"], key=lambda e: e["t_ms"]):
                    target = started + event["t_ms"] / 1000.0
                    while True:
                        remaining = target - clock()
                        if remaining <= 0:
                            break
                        sleep(min(remaining, _INJECT_POLL_S) if inject else remaining)
                        # Live changes from other commands; skipped right before an event
                        # so reading the file cannot delay a note.
                        if inject and target - clock() > 0.03:
                            inject_offset, count = _drain_inject(
                                inject, inject_offset, out, step["port"], resolved, pending_notes
                            )
                            injected += count
                    # Sequences are summarized, not logged byte by byte.
                    _send(out, event["message"], step["port"], resolved, [], pending_notes)
                    played += 1
                sequences.append({"step": index, "port": resolved[step["port"]],
                                  "events_sent": played, "live_messages_sent": injected})
            else:
                received = []  # type: list
                entry = {"step": index, "messages": received, "timed_out": False, "skipped": None}
                replies.append(entry)
                if inp is None:
                    entry["skipped"] = "input port unavailable"
                    continue
                inp.poll()  # discard stale input
                _send(outputs[step["port"]], step["message"], step["port"], resolved, sent, [])
                timeout = int(step.get("timeout_ms", 800)) / 1000.0
                quiet = int(step.get("quiet_ms", 60)) / 1000.0
                deadline = clock() + timeout
                last = None
                while True:
                    for msg in inp.poll():
                        if msg and msg[0] == 0xF0:
                            received.append(msg)
                            last = clock()
                    now = clock()
                    if last is not None and now - last >= quiet:
                        break
                    if now >= deadline:
                        entry["timed_out"] = not received
                        break
                    sleep(_POLL_INTERVAL_S)
    except AdapterError as exc:
        exc.details.setdefault("sent", sent)
        raise
    except Exception as exc:
        raise AdapterError(
            "MIDI_SEND_FAILED",
            "MIDI transmission failed: %s" % exc,
            {"sent": sent},
            "The device may have been disconnected. Check `integra7 ports`.",
        )
    finally:
        # Never leave a note hanging, whatever interrupted the transaction.
        for port_name, channel, note in list(pending_notes):
            try:
                off = [0x80 | channel, note, 0]
                outputs[port_name].send(off)
                cleanup.append({"port": resolved[port_name], "hex": _hex(off)})
            except Exception as exc:  # report, but keep cleaning up
                sys.stderr.write("note-off cleanup failed: %s\n" % exc)
        for port in list(outputs.values()) + ([inp] if inp is not None else []):
            try:
                port.close()
            except Exception as exc:
                sys.stderr.write("port close failed: %s\n" % exc)

    return {
        "sent": sent,
        "replies": replies,
        "sequences": sequences,
        "ports": resolved,
        "input": input_info,
        "cleanup_note_offs": cleanup,
    }


def _drain_inject(path, offset, out, port_name, resolved, pending_notes):
    """Send messages other commands appended to the live file (one JSON list per line)."""
    count = 0
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except (IOError, OSError):
        return offset, 0
    complete = data.rfind(b"\n") + 1
    for line in data[:complete].splitlines():
        try:
            for msg in json.loads(line.decode("utf-8")):
                _send(out, _check_message(msg), port_name, resolved, [], pending_notes)
                count += 1
        except Exception as exc:
            sys.stderr.write("ignored bad live message: %s\n" % exc)
    return offset + complete, count


def _send(out, msg, port_name, resolved, sent, pending_notes):
    out.send(msg)
    sent.append({"port": resolved[port_name], "hex": _hex(msg)})
    status = msg[0] & 0xF0
    key = (port_name, msg[0] & 0x0F, msg[1] if len(msg) > 1 else 0)
    if status == 0x90 and len(msg) == 3 and msg[2] > 0:
        pending_notes.append(key)
    elif status == 0x80 or (status == 0x90 and len(msg) == 3 and msg[2] == 0):
        if key in pending_notes:
            pending_notes.remove(key)


def run_request(request, io_factory, sleep=time.sleep, clock=time.monotonic):
    """Execute one request and return the full response envelope (never raises)."""
    try:
        if not isinstance(request, dict):
            raise AdapterError("INVALID_ARGUMENT", "Request must be a JSON object")
        op = request.get("op")
        if op == "ping":
            io = io_factory()
            data = {
                "midi_api": "mido + python-rtmidi",
                "python": sys.version.split()[0],
                "executable": sys.executable,
                "platform": sys.platform,
            }
            if hasattr(io, "versions"):
                data.update(io.versions())
        elif op == "ports":
            data = io_factory().list_ports()
        elif op == "transact":
            data = _transact(request, io_factory, sleep, clock)
        else:
            raise AdapterError("INVALID_ARGUMENT", "Unknown op %r" % op)
        return {"ok": True, "adapter_version": ADAPTER_VERSION, "data": data}
    except AdapterError as exc:
        return {"ok": False, "adapter_version": ADAPTER_VERSION, "error": exc.to_dict()}
    except Exception as exc:  # last resort: still answer with structured JSON
        return {
            "ok": False,
            "adapter_version": ADAPTER_VERSION,
            "error": {"code": "ADAPTER_FAILED", "message": "%s: %s" % (type(exc).__name__, exc)},
        }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv[:1] == ["--ports"]:
            request = {"op": "ports"}
        elif argv[:1] == ["--ping"]:
            request = {"op": "ping"}
        elif argv[:1] == ["--request-file"] and len(argv) == 2:
            with open(argv[1], "rb") as fh:
                request = json.loads(fh.read().decode("utf-8"))
        elif not argv:
            request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        else:
            raise ValueError("usage: windows_adapter.py [--ports | --ping | --request-file PATH]")
    except Exception as exc:
        response = {
            "ok": False,
            "adapter_version": ADAPTER_VERSION,
            "error": {"code": "INVALID_ARGUMENT", "message": "Bad adapter request: %s" % exc},
        }
    else:
        response = run_request(request, default_io)
    # ASCII-only JSON avoids any dependence on the Windows console code page.
    sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
    sys.stdout.flush()
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
