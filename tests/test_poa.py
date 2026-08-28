"""Plan wiąże wykonanie, a kanonizacja jest fail-closed."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from twinapi import PlanError, build_plan, build_process, canonical, load_vocabulary
from twinapi.poa import build_receipt, verify_plan

POA = Path.home() / "github" / "wellmanifest" / "poa" / "standard" / "poa-process.schema.v1.json"


def _operation(name: str = "set_track_width"):
    return load_vocabulary("pcb").get(name)


def _validate(document: dict) -> None:
    if not POA.is_file():
        pytest.skip("standard wellmanifest/poa nie jest dostępny lokalnie")
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(POA.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(document),
                    key=lambda item: list(item.path))
    assert not errors, errors[0].message


def test_a_process_declaration_conforms_to_the_poa_contract() -> None:
    _validate(build_process(_operation()))


def test_a_plan_conforms_to_the_poa_contract() -> None:
    _validate(build_plan(_operation(), {"segment": "GP7"}, target="panel9"))


def test_a_receipt_conforms_to_the_poa_contract() -> None:
    operation = _operation()
    plan = build_plan(operation, {"segment": "GP7"}, target="panel9")
    moment = datetime.now(UTC)
    _validate(build_receipt(plan, operation, state="succeeded", output={"candidate": "x"},
                            started_at=moment, completed_at=moment))


def test_the_same_input_gives_the_same_plan_hash_whatever_asked_for_it() -> None:
    """To jest cały sens: transport nie może zmieniać znaczenia zmiany."""
    operation = _operation()
    payload = {"segment": "GP7", "width_um": 500}

    first = build_plan(operation, payload, target="panel9")
    second = build_plan(operation, dict(reversed(list(payload.items()))), target="panel9")

    assert first["request_sha256"] == second["request_sha256"]


def test_a_plan_edited_after_the_fact_stops_binding_anything() -> None:
    plan = build_plan(_operation(), {"segment": "GP7"}, target="panel9")
    verify_plan(plan)

    plan["steps"][0]["effects"].append("destructive")

    with pytest.raises(PlanError, match="został zmieniony"):
        verify_plan(plan)


def test_a_float_is_refused_rather_than_hashed_dishonestly() -> None:
    """RFC 8785 rozstrzyga zapis float inaczej niż json.dumps — nie udajemy."""
    with pytest.raises(PlanError, match="zmiennoprzecinkowa"):
        canonical({"width_mm": 0.5})

    assert canonical({"width_um": 500}) == b'{"width_um":500}'
