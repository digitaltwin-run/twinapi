"""Powierzchnia: zgoda ze słownika, wykonanie związane planem, pokwitowanie zawsze."""
from __future__ import annotations

import pytest

from twinapi import Registry, Surface, SurfaceError, load_vocabulary
from twinapi.surface import receipt_of


def _surface(*, failing: bool = False) -> Surface:
    registry = Registry(load_vocabulary("pcb", "sch"))

    def widen(payload):
        if failing:
            raise ValueError("segment poza płytką")
        return {"candidate": "rev/panel9.kicad_pcb", "verified": True, **payload}

    registry.register("set_track_width", widen)
    registry.register("snap_to_common_grid", lambda payload: {"points": 276})
    return Surface(registry, target="panel9")


def test_the_surface_says_what_it_cannot_do_instead_of_staying_silent() -> None:
    document = _surface().describe()

    assert "set_track_width" in document["implemented"]
    assert "add_decoupling_capacitor" in document["declared_only"]
    assert all("implemented" in entry for entry in document["operations"])


def test_a_change_to_copper_needs_consent_and_the_rule_comes_from_the_vocabulary() -> None:
    surface = _surface()

    with pytest.raises(SurfaceError, match="wymaga zgody"):
        surface.execute("set_track_width", {"segment": "GP7"})

    result = surface.execute("set_track_width", {"segment": "GP7"}, approved=True)
    assert result["receipt"]["state"] == "succeeded"


def test_a_drawing_change_needs_no_consent() -> None:
    """Rysunek nie rusza ani miedzi, ani listy części — zgoda byłaby ceremonią."""
    result = _surface().execute("snap_to_common_grid", {})

    assert result["receipt"]["state"] == "succeeded"
    assert result["output"]["points"] == 276


def test_a_plan_for_other_input_refuses_to_bind_this_execution() -> None:
    surface = _surface()
    plan = surface.plan("set_track_width", {"segment": "GP7"})

    with pytest.raises(SurfaceError, match="inne wejście"):
        surface.execute("set_track_width", {"segment": "GP8"}, plan=plan, approved=True)


def test_a_plan_for_another_operation_refuses_too() -> None:
    surface = _surface()
    plan = surface.plan("snap_to_common_grid", {})

    with pytest.raises(SurfaceError):
        surface.execute("set_track_width", {}, plan=plan, approved=True)


def test_a_failure_still_produces_a_receipt() -> None:
    """Pokwitowanie należy się także porażce — inaczej znika ślad po próbie."""
    surface = _surface(failing=True)

    with pytest.raises(SurfaceError) as caught:
        surface.execute("set_track_width", {"segment": "GP7"}, approved=True)

    receipt = receipt_of(caught.value)
    assert receipt is not None
    assert receipt["state"] == "failed"
    assert receipt["steps"][0]["error_code"] == "ValueError"


def test_an_operation_the_standard_knows_but_the_project_cannot_do_says_so() -> None:
    surface = _surface()

    with pytest.raises(Exception, match="ten projekt jej nie umie"):
        surface.execute("trim_silkscreen", {}, approved=True)


def test_the_surface_bridges_a_rule_to_its_repairs() -> None:
    """Jedno naruszenie bywa naprawialne wąsko albo hurtem — i widać oba sposoby.

    Na panel9 to nie jest teoria: 52 zbyt wąskie odcinki da się poszerzyć po
    jednym albo zamknąć jednym przetrasowaniem. Kto pyta o naprawę, ma zobaczyć
    obie drogi, a nie tę, którą narzędzie akurat zna.
    """
    found = _surface().repairs_for("RULE_TRACK_WIDTH_BY_NET")
    by_id = {entry["operation"]: entry for entry in found}

    assert set(by_id) == {"set_track_width", "reroute_component_nets"}
    assert by_id["set_track_width"]["implemented"] is True
    assert by_id["reroute_component_nets"]["implemented"] is False
    assert all(entry["requires_approval"] for entry in found)


def test_the_ssot_document_carries_state_vocabulary_and_limits_together() -> None:
    """Model potrzebuje sześciu rzeczy naraz; zbieranie ich osobno kończy się zgadywaniem."""
    surface = _surface()
    surface.registry.register_reporter(
        lambda: [{"rule": "RULE_TRACK_WIDTH_BY_NET", "count": 52, "severity": "blocking"}])

    document = surface.ssot(history_limit=2)

    assert document["schema_id"] == "twinapi.ssot/v1"
    assert document["state"]["findings"][0]["repairs"][0]["operation"] == "set_track_width"
    assert set(document["request_schema"]["properties"]["operation"]["enum"]) == \
        set(document["vocabulary"]["implemented"])


def test_without_a_reporter_the_document_says_nothing_rather_than_guessing() -> None:
    document = _surface().ssot()

    assert document["state"]["findings"] == []
    assert document["state"]["unrepairable"] == []
