from __future__ import annotations

import json

import pytest

from integra7_conductor import cli


@pytest.fixture
def run(full_db, capsys):
    def invoke(*argv: str, expect: int = 0):
        code = cli.main([*argv, "--db", str(full_db), "--backend", "mock", "--json"])
        captured = capsys.readouterr()
        result = json.loads(captured.out)  # exactly one JSON object on stdout
        assert code == expect, captured.out
        assert result["ok"] is (expect == 0)
        return result

    return invoke


def test_dry_run_select_matches_documented_contract(run):
    result = run("part", "select", "--part", "1", "--patch", "Full Grand 1", "--dry-run")
    assert result["verification_status"] == "not_sent"
    assert result["backend"] == "mock"
    data = result["data"]
    assert (data["part"], data["channel"], data["patch_name"]) == (1, 1, "Full Grand 1")
    assert data["midi_messages_hex"] == ["B0 00 59", "B0 20 40", "C0 00"]
    assert data["sent"] is False


def test_select_by_id_is_mocked(run):
    result = run("part", "select", "--part", "2", "--patch-id", "sn-a-preset-0001")
    assert result["verification_status"] == "mocked"
    assert result["data"]["midi_messages_hex"][0] == "B1 00 59"


def test_global_flags_work_before_the_subcommand(full_db, capsys):
    code = cli.main(
        ["--json", "--backend", "mock", "--db", str(full_db), "patches", "search", "grand",
         "--limit", "3"]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["data"]["returned"] == 3


def test_search_and_show(run):
    hits = run("patches", "search", "full grand", "--kind", "tone", "--limit", "5")["data"]
    assert hits["results"][0]["id"] == "sn-a-preset-0001"
    shown = run("patches", "show", "studio-set-01")["data"]
    assert shown["kind"] == "studio_set" and "studio-set select 1" in shown["select_with"]


def test_ambiguous_name_error_is_json_with_candidates(run):
    result = run("part", "select", "--part", "10", "--patch", "Jazz Kit", expect=1)
    assert result["error"]["code"] == "AMBIGUOUS_PATCH"
    assert result["verification_status"] == "not_sent"
    assert len(result["error"]["details"]["candidates"]) >= 2


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (("part", "select", "--part", "17", "--patch-id", "sn-a-preset-0001"), "INVALID_PART"),
        (("part", "select", "--part", "x", "--patch-id", "sn-a-preset-0001"), "INVALID_ARGUMENT"),
        (("part", "select", "--part", "1"), "INVALID_ARGUMENT"),
        (("part", "audition", "--part", "1", "--note", "200"), "INVALID_NOTE"),
        (("part", "channels", "set", "--part", "2", "--channel", "0"), "INVALID_CHANNEL"),
        (("studio-set", "select", "65", "--dry-run"), "INVALID_PROGRAM"),
        (("patches",), "INVALID_ARGUMENT"),
        (("no-such-command",), "INVALID_ARGUMENT"),
        (("patches", "search", "x", "--limit", "0"), "INVALID_ARGUMENT"),
    ],
)
def test_usage_errors_are_json_with_exit_2(run, argv, code):
    assert run(*argv, expect=2)["error"]["code"] == code


def test_runtime_errors_exit_1(run):
    assert run("patches", "show", "nope", expect=1)["error"]["code"] == "PATCH_NOT_FOUND"
    result = run("studio-set", "select", "1", expect=1)
    assert result["error"]["code"] == "CONFIRMATION_REQUIRED"
    wrong = run("part", "select", "--part", "1", "--patch-id", "studio-set-01", expect=1)
    assert wrong["error"]["code"] == "WRONG_PATCH_KIND"


def test_missing_catalog_error(tmp_path, capsys):
    code = cli.main(["patches", "search", "x", "--db", str(tmp_path / "none.db"), "--json"])
    result = json.loads(capsys.readouterr().out)
    assert code == 1 and result["error"]["code"] == "CATALOG_NOT_FOUND"
    assert "patches import" in result["error"]["hint"]


def test_studio_set_dry_run_and_confirmed(run):
    dry = run("studio-set", "select", "1", "--dry-run")
    assert dry["data"]["midi_messages_hex"] == ["BF 00 55", "BF 20 00", "CF 00"]
    assert dry["verification_status"] == "not_sent"
    assert run("studio-set", "select", "1", "--yes")["verification_status"] == "mocked"


def test_channel_map_set_then_used(run):
    run("part", "channels", "set", "--part", "2", "--channel", "4")
    rows = run("part", "channels")["data"]["parts"]
    assert rows[1] == {"part": 2, "channel": 4, "source": "configured"}
    dry = run("part", "select", "--part", "2", "--patch-id", "sn-a-preset-0001", "--dry-run")
    assert dry["data"]["midi_messages_hex"] == ["B3 00 59", "B3 20 40", "C3 00"]


def test_config_precedence_cli_over_env_over_file(run, monkeypatch):
    run("config", "set", "studio_set_control_channel", "9")
    shown = run("config", "show")["data"]
    assert shown["values"]["studio_set_control_channel"] == 9
    assert shown["origins"]["studio_set_control_channel"] == "config_file"
    monkeypatch.setenv("INTEGRA7_STUDIO_SET_CONTROL_CHANNEL", "3")
    monkeypatch.setenv("INTEGRA7_DEVICE_ID", "0x11")
    shown = run("config", "show")["data"]
    assert shown["values"]["studio_set_control_channel"] == 3
    assert shown["origins"]["studio_set_control_channel"] == "environment"
    assert shown["values"]["device_id"] == 0x11
    shown = run("config", "show", "--device-id", "0x12")["data"]
    assert (shown["values"]["device_id"], shown["origins"]["device_id"]) == (0x12, "cli")
    assert shown["origins"]["backend"] == "cli"


def test_invalid_config_value_rejected(run):
    assert run("config", "set", "expansion_policy", "maybe", expect=2)["error"]["code"] == (
        "CONFIG_INVALID"
    )
    assert run("config", "show", "--device-id", "5", expect=2)["error"]["code"] == (
        "INVALID_ARGUMENT"
    )


def test_import_audit_export_roundtrip(tmp_path, capsys):
    db = str(tmp_path / "cat.db")
    base = ["--db", db, "--backend", "mock", "--json"]

    def call(*argv):
        code = cli.main([*argv, *base])
        return code, json.loads(capsys.readouterr().out)

    code, imported = call("patches", "import")  # bundled sources, one command
    assert code == 0 and imported["data"]["patch_count"] > 0
    code, audit = call("patches", "audit")
    assert code == 0 and audit["data"]["patch_count"] == imported["data"]["patch_count"]
    assert "coverage_vs_roland_bank_table" in audit["data"]
    out = tmp_path / "patches.json"
    code, _ = call("patches", "export", "--format", "json", "--output", str(out))
    assert code == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))["patches"]) == (
        imported["data"]["patch_count"]
    )
    code, missing = call("patches", "import", str(tmp_path / "missing.txt"))
    assert code == 1 and missing["error"]["code"] == "SOURCE_NOT_FOUND"


def test_expansions_declare_and_status(run):
    assert run("expansions", "status")["data"]["state"] == "unknown"
    run("expansions", "declare", "srx6", "ExSN1")
    assert run("expansions", "status")["data"]["loaded_expansions"] == ["SRX-06", "ExSN1"]
    bad = run("expansions", "declare", "ExPCM", "SRX-01", expect=2)
    assert bad["error"]["code"] == "INVALID_ARGUMENT"
    run("expansions", "declare", "--unknown")
    assert run("expansions", "status")["data"]["state"] == "unknown"


def test_read_only_commands(run):
    assert run("ports")["data"]["outputs"]
    assert run("device", "identify")["data"]["is_integra7"]
    assert run("device", "state", "--no-parts")["data"]["sound_mode"] == "STUDIO"
    assert run("capabilities")["data"]["hardware_verified"] is False
    assert run("doctor")["data"]["ready_for_hardware"] is False


def test_doctor_strict_exits_nonzero_when_not_hardware_ready(full_db, capsys):
    code = cli.main(["doctor", "--strict", "--db", str(full_db), "--backend", "mock", "--json"])
    result = json.loads(capsys.readouterr().out)
    assert code == 1 and result["ok"] is True and "_exit_code" not in result


def test_human_output_and_stderr_for_errors(full_db, capsys):
    base = ["--db", str(full_db), "--backend", "mock"]
    assert cli.main(["patches", "search", "full grand 1", "--limit", "1", *base]) == 0
    out = capsys.readouterr()
    assert "sn-a-preset-0001" in out.out and out.err == ""
    assert cli.main(["patches", "show", "nope", *base]) == 1
    out = capsys.readouterr()
    assert out.out == "" and "PATCH_NOT_FOUND" in out.err
