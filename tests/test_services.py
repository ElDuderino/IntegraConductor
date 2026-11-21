from __future__ import annotations

import pytest

from integra7_conductor.errors import Integra7Error
from integra7_conductor.services import device, expansions, parts, studio_sets

GRAND = "sn-a-preset-0001"
SRX_TONE = "srx06-tone-0001"


# ------------------------------------------------------------- part select

def test_select_emits_exact_bytes_and_is_mocked_not_verified(ctx, backend):
    result = parts.select_patch(ctx, 1, patch_id=GRAND)
    assert backend.sent_hex()[:3] == ["B0 00 59", "B0 20 40", "C0 00"]
    assert result["verification_status"] == "mocked"  # never "verified" without hardware
    assert result["backend"] == "mock"
    assert result["data"]["sent"] is True
    assert result["data"]["readback"]["status"] == "matched"
    assert backend.device.parts[1]["program"] == 0


def test_bank_select_and_program_change_share_one_transaction(ctx, backend):
    parts.select_patch(ctx, 1, patch_id=GRAND)
    transactions = [r for r in backend.requests if r["op"] == "transact"]
    assert len(transactions) == 1  # port held open across the whole sequence
    assert [s["type"] for s in transactions[0]["steps"]] == ["send", "sleep", "request"]
    assert len(transactions[0]["steps"][0]["messages"]) == 3


def test_part_2_mapped_to_channel_4_uses_channel_4(make_ctx, backend):
    ctx = make_ctx(part_channels={2: 4})
    backend.device.parts[2]["channel"] = 4
    result = parts.select_patch(ctx, 2, patch_id=GRAND)
    assert backend.sent_hex()[:3] == ["B3 00 59", "B3 20 40", "C3 00"]
    assert result["data"]["channel"] == 4
    assert result["data"]["channel_source"] == "configured"


def test_dry_run_sends_nothing_and_reports_plan(ctx, backend):
    result = parts.select_patch(ctx, 1, name="Full Grand 1", dry_run=True)
    assert backend.sent == [] and backend.requests == []
    assert result["verification_status"] == "not_sent"
    assert result["data"]["sent"] is False
    assert result["data"]["midi_messages_hex"] == ["B0 00 59", "B0 20 40", "C0 00"]
    assert result["data"]["port"] == "INTEGRA-7"
    assert result["data"]["channel"] == 1


def test_dry_run_config_default_applies(make_ctx, backend):
    result = parts.select_patch(make_ctx(dry_run=True), 1, patch_id=GRAND)
    assert backend.sent == [] and result["verification_status"] == "not_sent"


def test_ambiguous_name_sends_no_midi(ctx, backend):
    with pytest.raises(Integra7Error) as info:
        parts.select_patch(ctx, 10, name="Jazz Kit")
    assert info.value.code == "AMBIGUOUS_PATCH"
    assert len(info.value.details["candidates"]) >= 2
    assert info.value.verification_status == "not_sent"
    assert backend.sent == [] and backend.requests == []


def test_studio_set_refused_by_part_api(ctx, backend):
    with pytest.raises(Integra7Error) as info:
        parts.select_patch(ctx, 1, patch_id="studio-set-01")
    assert info.value.code == "WRONG_PATCH_KIND"
    assert "studio-set select 1" in info.value.hint
    assert backend.sent == []


@pytest.mark.parametrize("part", [0, 17, -1, "2", 1.5, None])
def test_invalid_part_rejected(ctx, backend, part):
    with pytest.raises(Integra7Error) as info:
        parts.select_patch(ctx, part, patch_id=GRAND)
    assert info.value.code == "INVALID_PART"
    assert backend.sent == []


def test_readback_mismatch_is_an_error_with_channel_diagnosis(ctx, backend):
    backend.device.parts[2]["channel"] = 9  # the unit listens elsewhere than assumed
    with pytest.raises(Integra7Error) as info:
        parts.select_patch(ctx, 2, patch_id="sn-a-preset-0002")
    err = info.value
    assert err.code == "MIDI_NOT_VERIFIED"
    assert err.verification_status == "mocked"
    assert err.details["sent"] is True
    assert err.details["readback"]["status"] == "mismatch"
    assert "channel 9" in err.hint and "--from-device" in err.hint


def test_silent_device_is_unverified_with_warning(ctx, backend):
    backend.device.respond = False
    result = parts.select_patch(ctx, 1, patch_id=GRAND)
    assert result["ok"] and result["data"]["readback"]["status"] == "no_reply"
    assert any("Rx Exclusive" in w for w in result["warnings"])
    assert result["verification_status"] != "verified"


def test_real_backend_status_is_verified_only_on_matching_readback(ctx, backend):
    backend.is_mock = False  # pretend bytes reach hardware
    assert parts.select_patch(ctx, 1, patch_id=GRAND)["verification_status"] == "verified"
    assert (
        parts.select_patch(ctx, 1, patch_id=GRAND, verify=False)["verification_status"]
        == "sent_unverified"
    )
    backend.device.respond = False
    assert parts.select_patch(ctx, 1, patch_id=GRAND)["verification_status"] == "sent_unverified"


def test_missing_input_port_does_not_block_send(make_ctx, backend):
    backend.is_mock = False
    result = parts.select_patch(make_ctx(input_port="Nonexistent"), 1, patch_id=GRAND)
    assert result["verification_status"] == "sent_unverified"
    assert result["data"]["readback"]["status"] == "skipped"
    assert backend.sent_hex() == ["B0 00 59", "B0 20 40", "C0 00"]


# -------------------------------------------------------------- port errors

def test_port_not_found_is_structured_and_nothing_sent(make_ctx, backend):
    with pytest.raises(Integra7Error) as info:
        parts.select_patch(make_ctx(performance_port="FA-06"), 1, patch_id=GRAND)
    assert info.value.code == "PORT_NOT_FOUND"
    assert info.value.details["available"] == backend.ports["outputs"]
    assert info.value.verification_status == "not_sent"
    assert backend.sent == []


def test_disconnected_device_no_ports(ctx, backend):
    backend.ports = {"inputs": [], "outputs": ["Microsoft GS Wavetable Synth 0"]}
    with pytest.raises(Integra7Error) as info:
        parts.select_patch(ctx, 1, patch_id=GRAND)
    assert info.value.code == "PORT_NOT_FOUND"


def test_ambiguous_port_name(make_ctx, backend):
    backend.ports["outputs"] = ["2- INTEGRA-7", "3- INTEGRA-7 CTRL"]
    with pytest.raises(Integra7Error) as info:
        parts.select_patch(make_ctx(performance_port="integra"), 1, patch_id=GRAND)
    assert info.value.code == "PORT_AMBIGUOUS"
    assert len(info.value.details["candidates"]) == 2


def test_port_open_failure(ctx, backend):
    backend.fail_open = True
    with pytest.raises(Integra7Error) as info:
        parts.select_patch(ctx, 1, patch_id=GRAND)
    assert info.value.code == "PORT_OPEN_FAILED"
    assert info.value.verification_status == "not_sent"


def test_failure_mid_sequence_reports_partial_send(ctx, backend):
    backend.is_mock = False
    backend.fail_after_messages = 2  # dies before the Program Change
    with pytest.raises(Integra7Error) as info:
        parts.select_patch(ctx, 1, patch_id=GRAND)
    assert info.value.code == "MIDI_SEND_FAILED"
    assert [s["hex"] for s in info.value.details["sent"]] == ["B0 00 59", "B0 20 40"]
    assert info.value.verification_status == "sent_unverified"


# ---------------------------------------------------------------- audition

def test_audition_sends_note_on_then_off(ctx, backend):
    result = parts.audition(ctx, 3, note=60, velocity=90, duration_ms=500)
    assert backend.sent_hex() == ["92 3C 5A", "82 3C 00"]
    assert backend.device.notes_on == set()
    assert result["verification_status"] == "mocked"
    steps = backend.requests[-1]["steps"]
    assert [s["type"] for s in steps] == ["send", "sleep", "send"]
    assert steps[1]["ms"] == 500


def test_audition_with_patch_selects_first(ctx, backend):
    parts.audition(ctx, 1, patch_id=GRAND, duration_ms=100)
    assert backend.sent_hex() == ["B0 00 59", "B0 20 40", "C0 00", "90 3C 5A", "80 3C 00"]


def test_audition_never_leaves_a_hanging_note_after_failure(ctx, backend):
    backend.fail_after_messages = 1  # the scheduled note-off send raises
    with pytest.raises(Integra7Error) as info:
        parts.audition(ctx, 1, duration_ms=200)
    assert info.value.code == "MIDI_SEND_FAILED"
    assert backend.sent_hex() == ["90 3C 5A", "80 3C 00"]  # cleanup path sent the note-off
    assert backend.device.notes_on == set()


def test_audition_note_off_after_interrupt_during_sleep(ctx, backend):
    def interrupted(_seconds):
        raise KeyboardInterrupt

    backend._sleep = interrupted
    with pytest.raises(KeyboardInterrupt):
        parts.audition(ctx, 1, duration_ms=200)
    assert backend.sent_hex() == ["90 3C 5A", "80 3C 00"]
    assert backend.device.notes_on == set()


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"note": 128}, "INVALID_NOTE"),
        ({"note": -1}, "INVALID_NOTE"),
        ({"velocity": 0}, "INVALID_NOTE"),
        ({"velocity": 128}, "INVALID_NOTE"),
        ({"duration_ms": 5001}, "INVALID_ARGUMENT"),
        ({"duration_ms": 0}, "INVALID_ARGUMENT"),
    ],
)
def test_audition_validation(ctx, backend, kwargs, code):
    with pytest.raises(Integra7Error) as info:
        parts.audition(ctx, 1, **kwargs)
    assert info.value.code == code and backend.sent == []


# -------------------------------------------------------------- studio sets

def test_studio_set_uses_control_channel_routing(ctx, backend):
    result = studio_sets.select_studio_set(ctx, 1, confirmed=True)
    # Integra Preview = 85/0/0 on the Studio Set Control Channel (16), not a part channel.
    assert backend.sent_hex()[:3] == ["BF 00 55", "BF 20 00", "CF 00"]
    assert result["data"]["factory_name"] == "Integra Preview"
    assert result["data"]["control_channel"] == 16
    assert result["verification_status"] == "mocked"
    assert any("all 16 parts" in w for w in result["warnings"])


def test_studio_set_requires_confirmation_or_dry_run(ctx, backend):
    with pytest.raises(Integra7Error) as info:
        studio_sets.select_studio_set(ctx, 12)
    assert info.value.code == "CONFIRMATION_REQUIRED"
    assert info.value.verification_status == "not_sent"
    assert backend.sent == []
    dry = studio_sets.select_studio_set(ctx, 12, dry_run=True)
    assert dry["data"]["midi_messages_hex"] == ["BF 00 55", "BF 20 00", "CF 0B"]
    assert backend.sent == []


def test_studio_set_custom_control_channel_and_mismatch(make_ctx, backend):
    ctx = make_ctx(studio_set_control_channel=10)
    with pytest.raises(Integra7Error) as info:  # the fake unit still listens on 16
        studio_sets.select_studio_set(ctx, 5, confirmed=True)
    assert backend.sent_hex()[:3] == ["B9 00 55", "B9 20 00", "C9 04"]
    assert info.value.code == "MIDI_NOT_VERIFIED"
    assert "Control Channel" in info.value.hint


def test_studio_set_control_channel_off(make_ctx, backend):
    with pytest.raises(Integra7Error) as info:
        studio_sets.select_studio_set(make_ctx(studio_set_control_channel=0), 1, confirmed=True)
    assert info.value.code == "INVALID_CHANNEL" and backend.sent == []


@pytest.mark.parametrize("number", [0, 65, -3])
def test_studio_set_number_range(ctx, number):
    with pytest.raises(Integra7Error) as info:
        studio_sets.select_studio_set(ctx, number, dry_run=True)
    assert info.value.code == "INVALID_PROGRAM"


# --------------------------------------------------------------- expansions

def test_expansion_unknown_warns_and_is_never_verified(ctx, backend):
    backend.is_mock = False
    result = parts.select_patch(ctx, 1, patch_id=SRX_TONE)
    assert result["verification_status"] == "sent_unverified"  # even though readback matched
    assert result["data"]["readback"]["status"] == "matched"
    assert any("SRX-06" in w and "unknown" in w for w in result["warnings"])


def test_expansion_policy_refuse(make_ctx, backend):
    with pytest.raises(Integra7Error) as info:
        parts.select_patch(make_ctx(expansion_policy="refuse"), 1, patch_id=SRX_TONE)
    assert info.value.code == "EXPANSION_NOT_LOADED"
    assert info.value.verification_status == "not_sent"
    assert backend.sent == []


def test_expansion_declared_loaded_passes_refuse_policy_as_assumption(make_ctx, backend):
    ctx = make_ctx(
        expansion_policy="refuse", expansions_declared=True, loaded_expansions="srx6,ExSN1"
    )
    result = parts.select_patch(ctx, 1, patch_id=SRX_TONE)
    assert any("assumption" in w for w in result["warnings"])
    with pytest.raises(Integra7Error) as info:
        parts.select_patch(ctx, 1, patch_id="srx07-tone-0001")
    assert info.value.code == "EXPANSION_NOT_LOADED"


def test_expansion_status_never_fabricates(ctx, make_ctx):
    data = expansions.status(ctx)["data"]
    assert data["state"] == "unknown" and data["loaded_expansions"] is None
    assert data["device_readback"] == "unsupported"
    declared = expansions.status(make_ctx(expansions_declared=True, loaded_expansions="ExPCM"))
    assert declared["data"]["state"] == "assumed"
    assert declared["data"]["loaded_expansions"] == ["ExPCM"]


def test_expansion_slot_planning():
    assert expansions.plan(["srx1", "SRX-02", "ExSN3", "exsn4"])["compatible"]
    assert not expansions.plan(["srx1", "srx2", "srx3", "srx4", "srx5"])["compatible"]
    assert not expansions.plan(["ExPCM", "SRX-01"])["compatible"]
    assert expansions.plan(["expcm"])["compatible"]
    with pytest.raises(Integra7Error):
        expansions.plan(["SRX-99"])


# ------------------------------------------------------------ device/readback

def test_channel_map_marks_assumptions(make_ctx):
    data = parts.channel_map(make_ctx(part_channels={2: 4}))
    rows = {r["part"]: r for r in data["data"]["parts"]}
    assert rows[2] == {"part": 2, "channel": 4, "source": "configured"}
    assert rows[3]["source"] == "default_assumption"
    assert 2 not in data["data"]["assumed_parts"] and data["warnings"]


def test_set_channel_persists_without_sending(ctx, backend, make_ctx):
    parts.set_channel(ctx, 2, 4)
    assert backend.sent == []
    assert make_ctx().config.channel_for_part(2) == (4, "configured")
    with pytest.raises(Integra7Error) as info:
        parts.set_channel(ctx, 2, 17)
    assert info.value.code == "INVALID_CHANNEL"


def test_channel_map_from_device_reports_differences(ctx, backend):
    backend.device.parts[5]["channel"] = 11
    data = parts.channel_map_from_device(ctx)["data"]
    assert data["source"] == "mock_device"
    assert data["differences_from_config"] == [{"part": 5, "configured": 5, "device": 11}]
    assert data["saved"] is False


def test_show_part_maps_address_to_patch(ctx, backend):
    parts.select_patch(ctx, 4, patch_id="sn-a-preset-0002")
    data = parts.show_part(ctx, 4)["data"]
    assert (data["patch_id"], data["display_pc"], data["receive_channel"]) == (
        "sn-a-preset-0002", 2, 4,
    )


def test_device_state_and_identity(ctx, backend):
    state = device.device_state(ctx)["data"]
    assert state["sound_mode"] == "STUDIO"
    assert state["studio_set_control_channel"] == 16
    assert len(state["parts"]) == 16
    ident = device.identify(ctx)["data"]
    assert ident["is_integra7"] and ident["device_id_displayed"] == 17


def test_read_timeout_is_structured(ctx, backend):
    backend.device.respond = False
    for call in (device.device_state, device.identify, lambda c: parts.show_part(c, 1)):
        with pytest.raises(Integra7Error) as info:
            call(ctx)
        assert info.value.code == "DEVICE_TIMEOUT"
        assert "Rx Exclusive" in info.value.hint


def test_wrong_device_id_gets_no_reply(make_ctx, backend):
    with pytest.raises(Integra7Error) as info:
        device.device_state(make_ctx(device_id=0x11))
    assert info.value.code == "DEVICE_TIMEOUT"


def test_list_ports_resolves_configured_names(ctx):
    result = device.list_ports(ctx)
    cfg = result["data"]["configured"]
    assert cfg["performance_port"]["resolved"] == "INTEGRA-7 1"  # not the CTRL port
    assert cfg["control_port"]["resolved"] == "INTEGRA-7 CTRL 2"
    assert cfg["input_port"]["resolved"] == "INTEGRA-7 0"
    assert any("simulated" in w for w in result["warnings"])


def test_capabilities_do_not_overclaim(ctx):
    data = device.capabilities(ctx)["data"]
    assert data["hardware_verified"] is False
    assert data["supported"]["expansion_switching"] is False
    assert data["supported"]["raw_sysex"] is False


def test_doctor_with_mock_backend(ctx):
    data = device.doctor(ctx)["data"]
    names = {c["name"]: c["status"] for c in data["checks"]}
    assert names["catalog"] == "ok" and names["midi_ports"] == "ok"
    assert names["part_channels"] == "warn"
    assert data["ready_for_offline_use"] is True
    assert data["ready_for_hardware"] is False  # mock never counts as hardware-ready
