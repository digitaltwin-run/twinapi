"""A2A: karta agenta i zadania, z planem jako artefaktem pośrednim.

Drugi agent dostaje kartę z umiejętnościami wziętymi ze słownika i wykonuje
zadania w dwóch krokach: najpierw `plan`, który zwraca hash, potem `run`
związany tym hashem. To jest ta sama para, którą widzi człowiek w powłoce —
i o to chodzi, żeby agent nie miał krótszej drogi niż człowiek.
"""
from __future__ import annotations

from typing import Any

from ..surface import Surface, SurfaceError, receipt_of
from ..vocabulary import VocabularyError


def agent_card(surface: Surface, *, name: str, url: str, version: str = "0.1.0"
               ) -> dict[str, Any]:
    document = surface.describe()
    return {
        "schema_id": "twinapi.agent-card/v1",
        "name": name,
        "description": (
            "Proponuje zmiany w projekcie EDA wyłącznie ze słownika standardu; "
            "każda zmiana jest kandydatem, nie zapisem w projekcie."
        ),
        "url": url,
        "version": version,
        "capabilities": {"streaming": False, "pushNotifications": False,
                         "stateTransitionHistory": True},
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": entry["id"],
                "name": entry["id"],
                "description": entry["why"],
                "tags": [entry["scope"], entry["changes"], entry["pack"]],
                "examples": [f'{{"operation": "{entry["id"]}", "input": {{}}}}'],
                "requiresApproval": entry["requires_approval"],
            }
            for entry in document["operations"] if entry["implemented"]
        ],
        "provenance": {"packs": document["packs"], "target": document["target"]},
    }


def handle_task(surface: Surface, task: dict[str, Any]) -> dict[str, Any]:
    """Jedno zadanie A2A: `plan` albo `run`, zawsze z pokwitowaniem w odpowiedzi."""
    task_id = task.get("id") or "task"
    action = task.get("action") or "plan"
    operation = task.get("operation")
    payload = task.get("input") or {}
    if not operation:
        return _failed(task_id, "zadanie bez operacji")
    try:
        if action == "plan":
            plan = surface.plan(operation, payload)
            return {
                "schema_id": "twinapi.task/v1", "id": task_id, "state": "input-required",
                "artifacts": [{"name": "plan", "parts": [{"kind": "data", "data": plan}]}],
                "message": ("Plan gotowy. Wykonanie wymaga zgody."
                            if surface.vocabulary.get(operation).requires_approval
                            else "Plan gotowy."),
            }
        if action == "run":
            result = surface.execute(operation, payload, plan=task.get("plan"),
                                     approved=bool(task.get("approved")))
            return {
                "schema_id": "twinapi.task/v1", "id": task_id, "state": "completed",
                "artifacts": [
                    {"name": "output", "parts": [{"kind": "data", "data": result["output"]}]},
                    {"name": "receipt", "parts": [{"kind": "data", "data": result["receipt"]}]},
                ],
            }
        return _failed(task_id, f"nieznane działanie {action!r}; dozwolone: plan, run")
    except SurfaceError as exc:
        return _failed(task_id, str(exc), receipt_of(exc))
    except VocabularyError as exc:
        return _failed(task_id, str(exc))


def _failed(task_id: str, message: str, receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    artifacts = []
    if receipt is not None:
        artifacts.append({"name": "receipt", "parts": [{"kind": "data", "data": receipt}]})
    return {"schema_id": "twinapi.task/v1", "id": task_id, "state": "failed",
            "message": message, "artifacts": artifacts}
