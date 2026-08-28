"""Cztery transporty, jedna zmiana.

Ten plik pilnuje własności, dla której `twinapi` w ogóle istnieje: powłoka,
REST, MCP i A2A nie mogą znaczyć różnych rzeczy przez to samo wejście.
"""
from __future__ import annotations

import json

import pytest

from twinapi import Registry, Surface, load_vocabulary
from twinapi.adapters import a2a, cli, mcp


def _surface() -> Surface:
    registry = Registry(load_vocabulary("pcb", "sch"))
    registry.register("set_track_width",
                      lambda payload: {"candidate": "rev/panel9.kicad_pcb", **payload})
    registry.register("snap_to_common_grid", lambda payload: {"points": 276})
    return Surface(registry, target="panel9")


PAYLOAD = {"segment": "GP7", "width_um": 500}


def test_every_transport_produces_the_same_plan_for_the_same_input() -> None:
    """Wiążący jest odcisk *żądania*, nie całego planu.

    Plan niesie jeszcze okno ważności, więc jego własny hash zmienia się z
    zegarem — i tak ma być, bo termin jest częścią obietnicy. Tym, co musi być
    identyczne w czterech transportach, jest `request_sha256`: to on decyduje,
    czy wykonanie robi dokładnie to, co pokazał plan.
    """
    surface = _surface()

    direct = surface.plan("set_track_width", PAYLOAD)
    through_mcp = mcp.call_tool(surface, "twinapi_plan",
                                {"operation": "set_track_width", "input": PAYLOAD})["content"]
    through_a2a = a2a.handle_task(surface, {"id": "t1", "action": "plan",
                                            "operation": "set_track_width",
                                            "input": PAYLOAD})
    from_a2a = through_a2a["artifacts"][0]["parts"][0]["data"]

    assert direct["request_sha256"] == through_mcp["request_sha256"] == \
        from_a2a["request_sha256"]
    assert direct["steps"][0]["idempotency_key"] == from_a2a["steps"][0]["idempotency_key"]


def test_the_cli_subcommands_are_generated_from_the_vocabulary(capsys) -> None:
    surface = _surface()

    assert cli.main(surface, ["--format", "json", "list"]) == 0
    document = json.loads(capsys.readouterr().out)

    assert document["target"] == "panel9"
    assert "add_decoupling_capacitor" in document["declared_only"]


def test_the_cli_refuses_a_copper_change_without_consent(capsys) -> None:
    surface = _surface()

    code = cli.main(surface, ["run", "set_track_width", "--input", json.dumps(PAYLOAD)])

    assert code == 1
    assert "wymaga zgody" in capsys.readouterr().err


def test_mcp_only_lists_tools_the_project_can_actually_run() -> None:
    tools = {tool["name"] for tool in mcp.list_tools(_surface())}

    assert "twinapi_set_track_width" in tools
    assert "twinapi_add_decoupling_capacitor" not in tools
    assert {"twinapi_list", "twinapi_plan"} <= tools


def test_mcp_makes_consent_a_required_argument_not_a_convention() -> None:
    tools = {tool["name"]: tool for tool in mcp.list_tools(_surface())}

    widening = tools["twinapi_set_track_width"]["inputSchema"]
    drawing = tools["twinapi_snap_to_common_grid"]["inputSchema"]

    assert widening["required"] == ["approved"]
    assert drawing["required"] == []


def test_mcp_returns_the_failure_as_content_not_as_a_transport_error() -> None:
    answer = mcp.call_tool(_surface(), "twinapi_set_track_width", {"input": PAYLOAD})

    assert answer["isError"] is True
    assert "wymaga zgody" in answer["content"]["error"]


def test_the_agent_card_advertises_only_implemented_skills() -> None:
    card = a2a.agent_card(_surface(), name="panel9", url="https://example.invalid/a2a")

    skills = {skill["id"] for skill in card["skills"]}
    assert skills == {"set_track_width", "snap_to_common_grid"}
    assert next(s for s in card["skills"] if s["id"] == "set_track_width")["requiresApproval"]


def test_a2a_gives_an_agent_the_same_two_steps_a_human_gets() -> None:
    surface = _surface()

    planned = a2a.handle_task(surface, {"id": "t2", "action": "plan",
                                        "operation": "set_track_width", "input": PAYLOAD})
    assert planned["state"] == "input-required"

    refused = a2a.handle_task(surface, {"id": "t3", "action": "run",
                                        "operation": "set_track_width", "input": PAYLOAD})
    assert refused["state"] == "failed"

    done = a2a.handle_task(surface, {"id": "t4", "action": "run", "approved": True,
                                     "operation": "set_track_width", "input": PAYLOAD})
    assert done["state"] == "completed"
    assert [artifact["name"] for artifact in done["artifacts"]] == ["output", "receipt"]


def test_the_rest_router_exposes_the_same_surface() -> None:
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from twinapi.adapters import rest

    surface = _surface()
    app = FastAPI()
    app.include_router(rest.build_router(surface))
    client = TestClient(app)

    assert client.get("/api/twinapi/operations").json()["target"] == "panel9"
    planned = client.post("/api/twinapi/plan/set_track_width", json=PAYLOAD).json()
    assert planned["request_sha256"] == \
        surface.plan("set_track_width", PAYLOAD)["request_sha256"]

    refused = client.post("/api/twinapi/run/set_track_width", json={"input": PAYLOAD})
    assert refused.status_code == 409

    done = client.post("/api/twinapi/run/set_track_width",
                       json={"input": PAYLOAD, "approved": True})
    assert done.json()["receipt"]["state"] == "succeeded"
    assert client.get("/api/twinapi/operations/nie_ma_takiej").status_code == 404
