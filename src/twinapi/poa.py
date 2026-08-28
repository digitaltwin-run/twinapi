"""Dokumenty POA: proces, plan i pokwitowanie, budowane ze słownika operacji.

`wellmanifest/poa` opisuje, jak wygląda praca, którą da się obejrzeć przed
wykonaniem i sprawdzić po nim: żądanie → plan związany hashem → wykonanie →
pokwitowanie. Tutaj zamieniamy jedną zadeklarowaną operację w te dokumenty, żeby
transport przestał mieć znaczenie: plan zbudowany z powłoki i plan zbudowany
przez MCP mają ten sam hash, bo powstają z tego samego wejścia.

Kanonizacja jest fail-closed. RFC 8785 rozstrzyga zapis liczb zmiennoprzecinkowych
w sposób, którego `json.dumps` nie odtwarza — zamiast udawać zgodność, odmawiamy
kanonizowania `float`. Wejście operacji, które potrzebuje ułamka, ma go podać jako
łańcuch albo jako liczbę całkowitą w mniejszej jednostce; wtedy hash znaczy to,
co obiecuje.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .vocabulary import Operation

DOMAIN = "digitaltwin.run"
HASH_PROFILE = "RFC8785+SHA-256"
PLAN_TTL_SECONDS = 900


class PlanError(RuntimeError):
    """Wejście, którego nie da się uczciwie zahashować albo zaplanować."""


def canonical(value: Any) -> bytes:
    """Kanoniczny JSON — podzbiór RFC 8785, w którym zapis jest jednoznaczny."""
    _reject_floats(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _reject_floats(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        raise PlanError(
            f"{path}: liczba zmiennoprzecinkowa nie ma jednoznacznego zapisu kanonicznego; "
            "podaj ją jako łańcuch albo jako liczbę całkowitą w mniejszej jednostce"
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_floats(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def process_ref(operation: Operation) -> str:
    return f"poa://{DOMAIN}/process/{operation.id.replace('_', '-')}/v1"


def capability_ref(operation: Operation) -> str:
    return f"capability://{DOMAIN}/eda/{operation.id.replace('_', '-')}/v1"


def process_uri(operation: Operation, target: str) -> str:
    return f"twinapi://{DOMAIN}/{target}/command/{operation.id}"


def target_ref(target: str) -> str:
    return f"target://{DOMAIN}/{target}"


def verification_ref(name: str) -> dict[str, str]:
    slug = name.replace("_", "-")
    return {
        "capability_ref": f"capability://{DOMAIN}/gate/{slug}/v1",
        "expectation_schema_ref": f"schema://{DOMAIN}/gate/{slug}/v1",
    }


def build_process(operation: Operation) -> dict[str, Any]:
    """Deklaracja procesu POA dla jednej operacji ze słownika."""
    return {
        "schema": "poa.process/v1",
        "process_ref": process_ref(operation),
        "title": f"{operation.id}: {operation.why}",
        # POA żąda podmiotu w postaci `rola:nazwa`; właścicielem procesu jest
        # paczka standardu, która ten czasownik zadeklarowała.
        "owner": f"service:{operation.pack.replace('/', '.')}",
        "input_schema_ref": f"schema://{DOMAIN}/eda/{operation.id}.input/v1",
        "output_schema_ref": f"schema://{DOMAIN}/eda/candidate/v1",
        "policy_refs": [f"policy://{DOMAIN}/eda/propose-only/v1"],
        "steps": [{
            "id": operation.id.replace("_", "-"),
            "capability_ref": capability_ref(operation),
            "kind": operation.kind,
            "effects": list(operation.effects),
            "depends_on": [],
            "requires_approval": operation.requires_approval,
            "timeout_seconds": 900,
            "max_attempts": 1,
            "idempotency": "required",
            "verification": [verification_ref(name) for name in operation.verify],
        }],
    }


def build_plan(operation: Operation, payload: dict[str, Any], *, target: str,
               subject: str = "human:operator",
               now: datetime | None = None) -> dict[str, Any]:
    """Plan związany hashem: to samo wejście daje ten sam plan w każdym transporcie."""
    moment = now or datetime.now(UTC)
    request = {
        "schema": "poa.request.plan/v1",
        "operation": operation.id,
        "process_ref": process_ref(operation),
        "target": target,
        "input": payload,
    }
    request_sha256 = digest(request)
    step = {
        "id": operation.id.replace("_", "-"),
        "capability_ref": capability_ref(operation),
        "process_uri": process_uri(operation, target),
        "target_ref": target_ref(target),
        "kind": operation.kind,
        "effects": list(operation.effects),
        "depends_on": [],
        "input_ref": f"artifact://{DOMAIN}/request/{request_sha256[:12]}/r1",
        "input_sha256": request_sha256,
        "timeout_seconds": 900,
        "max_attempts": 1,
        "idempotency_key": request_sha256[:32],
        "verification": [verification_ref(name) for name in operation.verify],
    }
    plan = {
        "schema": "poa.plan/v1",
        "plan_id": f"plan.{request_sha256[:16]}",
        "process_ref": process_ref(operation),
        "request_sha256": request_sha256,
        "valid_until": (moment + timedelta(seconds=PLAN_TTL_SECONDS)).isoformat(),
        "steps": [step],
        "dsl_contract": {
            "schema_ref": f"schema://{DOMAIN}/eda/{operation.id}.input/v1",
            "grammar_ref": f"grammar://{DOMAIN}/eda/{operation.id}/v1",
            "schema_sha256": digest({"operation": operation.id, "part": "schema"}),
            "grammar_sha256": digest({"operation": operation.id, "part": "grammar"}),
            "canonical_sha256": digest(payload),
            "canonicalization": "RFC8785",
            "hash_algorithm": "SHA-256",
            "validated": True,
            "additional_properties": False,
        },
        "authority_requirements": {
            "subject": subject,
            "scopes": [f"eda:{operation.changes}"],
            "grant_ttl_seconds": PLAN_TTL_SECONDS,
            "intent_required": operation.requires_approval,
            "plan_hash_binding": True,
        },
        "execution_boundary": {
            "boundary_ref": target_ref(target),
            "host_shell": False,
            "arbitrary_executable": False,
            "transport_from_registry": True,
        },
        "hash_profile": HASH_PROFILE,
    }
    plan["plan_hash"] = digest(plan)
    return plan


def verify_plan(plan: dict[str, Any]) -> None:
    """Plan, którego hash nie zgadza się z treścią, nie wiąże niczego."""
    claimed = plan.get("plan_hash")
    if not claimed:
        raise PlanError("plan bez hasza nie wiąże wykonania")
    recomputed = digest({key: value for key, value in plan.items() if key != "plan_hash"})
    if claimed != recomputed:
        raise PlanError("hash planu nie odpowiada jego treści — plan został zmieniony po podpisie")


def build_receipt(plan: dict[str, Any], operation: Operation, *, state: str,
                  output: dict[str, Any], started_at: datetime, completed_at: datetime,
                  attempts: int = 1, error_code: str | None = None,
                  verified: bool = False) -> dict[str, Any]:
    """Pokwitowanie: co się stało, z odciskiem wyniku i planu, który to związał."""
    step = plan["steps"][0]
    payload = canonical(output)
    step_receipt: dict[str, Any] = {
        "step_id": step["id"],
        "process_uri": step["process_uri"],
        "state": state,
        "attempts": attempts,
        "output_sha256": hashlib.sha256(payload).hexdigest(),
        "output_bytes": len(payload),
        "effect_verified": verified,
        # POA chce tu odnośników do artefaktów dowodowych, nie do zdolności:
        # pokwitowanie ma wskazywać *wynik* sprawdzenia, nie jego nazwę.
        "verification_refs": [
            f"artifact://{DOMAIN}/verification/{plan['request_sha256'][:12]}."
            f"{index}/r1"
            for index, _item in enumerate(step["verification"], start=1)
        ],
    }
    if error_code:
        step_receipt["error_code"] = error_code
    receipt = {
        "schema": "poa.receipt/v1",
        "run_id": f"run.{plan['request_sha256'][:16]}",
        "process_ref": plan["process_ref"],
        "plan_ref": f"sha256:{plan['plan_hash']}",
        "grant_ref": f"grant:{plan['plan_id']}",
        "intent_ref": f"intent:{plan['plan_id']}",
        "state": state,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "steps": [step_receipt],
        "raw_output_included": False,
        "secret_material_included": False,
        "hash_profile": HASH_PROFILE,
    }
    receipt["receipt_hash"] = digest(receipt)
    return receipt
