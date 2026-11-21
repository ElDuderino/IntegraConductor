from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("mcp")

from integra7_conductor import mcp_server  # noqa: E402

REQUIRED_TOOLS = {
    "search_patches",
    "get_patch",
    "list_midi_ports",
    "get_configured_part_channels",
    "select_patch",
    "select_studio_set",
    "audition_patch",
    "get_device_capabilities",
}


@pytest.fixture
def server(full_db, backend, monkeypatch):
    monkeypatch.setenv("INTEGRA7_BACKEND", "mock")
    monkeypatch.setenv("INTEGRA7_DB_PATH", str(full_db))
    return mcp_server.build_server(backend)


def call(server, name: str, **arguments):
    result = asyncio.run(server.call_tool(name, arguments))
    if hasattr(result, "content"):  # SDK 2.x CallToolResult
        content = result.content
    else:  # SDK 1.x: a content list, or (content, structured) tuple
        content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text)


def schema(tool) -> dict:
    return getattr(tool, "input_schema", None) or tool.inputSchema


def test_required_tools_are_exposed_with_typed_schemas(server):
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert REQUIRED_TOOLS <= set(tools)
    select = schema(tools["select_patch"])
    assert select["properties"]["part"]["type"] == "integer"
    assert select["properties"]["patch_id"]["type"] == "string"
    assert select["properties"]["dry_run"]["default"] is False
    assert set(select["required"]) == {"part", "patch_id"}
    studio = schema(tools["select_studio_set"])
    assert studio["properties"]["dry_run"]["default"] is True  # safe by default
    audition = schema(tools["audition_patch"])["properties"]
    assert {"part", "patch_id", "note", "velocity", "duration_ms"} <= set(audition)
    for tool in tools.values():
        assert tool.description and len(tool.description) > 40
    assert "not an ID" in tools["get_patch"].description or "name is not" in (
        tools["get_patch"].description
    )


def test_search_then_select_workflow(server, backend):
    found = call(server, "search_patches", query="full grand", kind="tone", limit=5)
    assert found["ok"] and found["data"]["returned"] == 5
    patch_id = found["data"]["results"][0]["id"]
    assert patch_id == "sn-a-preset-0001"
    assert backend.sent == []

    dry = call(server, "select_patch", part=2, patch_id=patch_id, dry_run=True)
    assert dry["verification_status"] == "not_sent" and backend.sent == []
    assert dry["data"]["midi_messages_hex"] == ["B1 00 59", "B1 20 40", "C1 00"]

    done = call(server, "select_patch", part=2, patch_id=patch_id)
    assert done["verification_status"] == "mocked"
    assert backend.sent_hex()[:3] == ["B1 00 59", "B1 20 40", "C1 00"]


def test_errors_are_structured_not_exceptions(server, backend):
    by_name = call(server, "select_patch", part=1, patch_id="Full Grand 1")
    assert by_name["ok"] is False and by_name["error"]["code"] == "PATCH_NOT_FOUND"
    assert "not an ID" in by_name["error"]["hint"]
    bad_part = call(server, "select_patch", part=99, patch_id="sn-a-preset-0001")
    assert bad_part["error"]["code"] == "INVALID_PART"
    studio = call(server, "select_patch", part=1, patch_id="studio-set-01")
    assert studio["error"]["code"] == "WRONG_PATCH_KIND"
    assert backend.sent == []


def test_studio_set_defaults_to_dry_run(server, backend):
    preview = call(server, "select_studio_set", number=1)
    assert preview["verification_status"] == "not_sent" and backend.sent == []
    assert preview["data"]["midi_messages_hex"] == ["BF 00 55", "BF 20 00", "CF 00"]
    done = call(server, "select_studio_set", number=1, dry_run=False)
    assert done["verification_status"] == "mocked"
    assert backend.sent_hex()[:3] == ["BF 00 55", "BF 20 00", "CF 00"]


def test_audition_and_read_tools(server, backend):
    played = call(server, "audition_patch", part=1, note=64, velocity=80, duration_ms=250)
    assert played["ok"] and backend.sent_hex() == ["90 40 50", "80 40 00"]
    too_long = call(server, "audition_patch", part=1, duration_ms=60000)
    assert too_long["error"]["code"] == "INVALID_ARGUMENT"

    assert call(server, "get_patch", patch_id="studio-set-01")["data"]["kind"] == "studio_set"
    assert call(server, "list_midi_ports")["data"]["outputs"]
    channels = call(server, "get_configured_part_channels")["data"]["parts"]
    assert channels[0]["source"] == "default_assumption"
    assert call(server, "get_device_capabilities")["data"]["hardware_verified"] is False
    assert call(server, "get_expansion_slots")["data"]["state"] == "unknown"
    assert call(server, "get_current_part_patch", part=1)["data"]["receive_channel"] == 1
    assert call(server, "get_device_state")["data"]["sound_mode"] == "STUDIO"


def test_effect_tools(server, backend):
    listed = call(server, "list_effect_parameters")["data"]
    assert "reverb.type" in listed["global"]
    done = call(server, "set_effects", settings={"reverb.type": "room2", "part.1.reverb_send": 40})
    assert done["verification_status"] == "mocked"
    assert call(server, "get_effects", parts=[1])["data"]["parts"][0]["reverb_send"] == 40
    bad = call(server, "set_effects", settings={"reverb.type": "cave"})
    assert bad["error"]["code"] == "INVALID_ARGUMENT"
