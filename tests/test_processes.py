"""Routing procesów jest deklaracją; słownik pozostaje zamknięty."""
from __future__ import annotations

import json

import pytest

from twinapi import ProcessError, bind, load_processes, load_vocabulary, routing
from twinapi.processes import bindings


def _document(**overrides):
    document = {
        "schema_id": "twinapi.processes/v1",
        "target": "panel9",
        "processes": [{"operation": "trim_silkscreen",
                       "handler": "twinapi.poa:digest"}],
        "gates": [{"name": "drc_no_regression", "handler": "twinapi.poa:digest"}],
    }
    document.update(overrides)
    return document


def _write(tmp_path, document) -> object:
    path = tmp_path / "processes.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_a_manifest_cannot_invent_a_verb(tmp_path) -> None:
    """Routing jest wolny, słownik zamknięty — to jest cała granica."""
    from twinapi import VocabularyError

    document = _document(processes=[{"operation": "rewrite_everything",
                                     "handler": "twinapi.poa:digest"}])

    with pytest.raises(VocabularyError, match="nieznana operacja"):
        bindings(document, load_vocabulary("pcb", "sch"), "panel9")


def test_a_uri_that_disagrees_with_the_plan_is_refused() -> None:
    """Plan niesie `process_uri`; rejestr wskazujący gdzie indziej rozjeżdża oba."""
    document = _document(processes=[{"operation": "trim_silkscreen",
                                     "uri": "twinapi://digitaltwin.run/inny/command/trim_silkscreen",
                                     "handler": "twinapi.poa:digest"}])

    with pytest.raises(ProcessError, match="rozjazd routingu z planem"):
        bindings(document, load_vocabulary("pcb", "sch"), "panel9")


def test_the_uri_matches_the_one_the_plan_will_carry() -> None:
    from twinapi import build_plan

    vocabulary = load_vocabulary("pcb", "sch")
    binding = bindings(_document(), vocabulary, "panel9")[0]
    plan = build_plan(vocabulary.get("trim_silkscreen"), {}, target="panel9")

    assert binding.uri == plan["steps"][0]["process_uri"]


def test_a_handler_that_cannot_be_imported_says_so_instead_of_failing_later(tmp_path) -> None:
    document = _document(processes=[{"operation": "trim_silkscreen",
                                     "handler": "nie.ma.takiego:modulu"}])

    with pytest.raises(ProcessError, match="nie da się zaimportować"):
        bind(load_vocabulary("pcb", "sch"), document, target="panel9")


def test_a_reference_without_a_function_is_refused() -> None:
    document = _document(processes=[{"operation": "trim_silkscreen", "handler": "twinapi.poa"}])

    with pytest.raises(ProcessError, match="moduł:funkcja"):
        bind(load_vocabulary("pcb", "sch"), document, target="panel9")


def test_promotion_needs_both_a_declaration_and_an_explicit_permission() -> None:
    document = _document(promoter="twinapi.poa:digest")
    vocabulary = load_vocabulary("pcb", "sch")

    assert bind(vocabulary, document, target="panel9").promoter is None
    assert bind(vocabulary, document, target="panel9", allow_promotion=True).promoter is not None


def test_a_manifest_with_the_wrong_schema_is_refused(tmp_path) -> None:
    path = _write(tmp_path, _document(schema_id="coś.innego/v1"))

    with pytest.raises(ProcessError, match="schema_id"):
        load_processes(path)


def test_the_routing_table_is_showable_in_every_transport() -> None:
    table = routing(_document(), load_vocabulary("pcb", "sch"), "panel9")

    assert table["schema_id"] == "twinapi.routing/v1"
    assert table["registry_schema_id"] == "twinapi.processes/v1"
    assert len(table["registry_sha256"]) == len(table["routing_sha256"]) == 64
    assert table["processes"][0]["operation"] == "trim_silkscreen"
    assert table["processes"][0]["process_ref"].startswith("poa://")
    assert table["processes"][0]["capability_ref"].startswith("capability://")
    assert table["processes"][0]["process_uri"] == table["processes"][0]["uri"]
    assert table["processes"][0]["adapter_ref"].startswith("adapter://")
    assert table["gates"] == ["drc_no_regression"]
    assert table["verification"][0]["capability_ref"].endswith(
        "/gate/drc-no-regression/v1"
    )
    assert json.loads(json.dumps(table, ensure_ascii=False))["target"] == "panel9"
