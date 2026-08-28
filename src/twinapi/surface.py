"""Jedna powierzchnia, cztery transporty.

Adapter CLI, REST, MCP i A2A nie zna żadnej operacji z osobna. Każdy pyta tę
klasę o to samo: co jest w słowniku, jak wygląda plan dla tego wejścia i jakie
jest pokwitowanie wykonania. Dzięki temu nie da się dodać czasownika do jednego
transportu, zapominając o trzech pozostałych — nie ma gdzie go dodać.

Wykonanie jest związane hashem planu. `execute` bez planu policzy go sam z tego
samego wejścia; `execute` z planem sprawdzi, czy plan opisuje dokładnie to
wejście. Rozjazd między „co pokazałem" a „co zrobiłem" jest wtedy błędem, a nie
niespodzianką.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .poa import build_plan, build_process, build_receipt, digest, verify_plan
from .registry import Registry
from .vocabulary import Operation, describe


class SurfaceError(RuntimeError):
    """Żądanie, którego nie da się spełnić bez łamania kontraktu."""


class Surface:
    """Słownik + rejestr + POA. Wszystko, czego potrzebuje każdy z transportów."""

    def __init__(self, registry: Registry, *, target: str,
                 subject: str = "human:operator") -> None:
        self.registry = registry
        self.vocabulary = registry.vocabulary
        self.target = target
        self.subject = subject

    # — opis —

    def describe(self) -> dict[str, Any]:
        """Co ten projekt umie, czego jeszcze nie, i z czyjego słownika to bierze."""
        document = describe(self.vocabulary)
        document["target"] = self.target
        document["implemented"] = list(self.registry.implemented)
        document["declared_only"] = list(self.registry.declared_only)
        for entry in document["operations"]:
            entry["implemented"] = entry["id"] in self.registry.handlers
        return document

    def process(self, operation_id: str) -> dict[str, Any]:
        return build_process(self.vocabulary.get(operation_id))

    def repairs_for(self, rule_id: str) -> list[dict[str, Any]]:
        """Most między raportem a naprawą: czym wolno zamknąć to naruszenie."""
        return [
            {"operation": item.id, "why": item.why,
             "implemented": item.id in self.registry.handlers,
             "requires_approval": item.requires_approval}
            for item in self.vocabulary.clearing(rule_id)
        ]

    # — plan —

    def plan(self, operation_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        operation = self.vocabulary.get(operation_id)
        return build_plan(operation, payload or {}, target=self.target, subject=self.subject)

    # — wykonanie —

    def execute(self, operation_id: str, payload: dict[str, Any] | None = None, *,
                plan: dict[str, Any] | None = None,
                approved: bool = False) -> dict[str, Any]:
        """Buduje kandydata i zwraca wynik razem z pokwitowaniem POA."""
        operation = self.vocabulary.get(operation_id)
        payload = payload or {}
        bound = plan or self.plan(operation_id, payload)
        verify_plan(bound)
        self._check_binding(operation, payload, bound)
        if operation.requires_approval and not approved:
            raise SurfaceError(
                f"operacja {operation.id} zmienia {operation.changes} i wymaga zgody; "
                "wykonaj ją ponownie z approved=true po obejrzeniu planu"
            )
        handler = self.registry.handler(operation.id)
        started = datetime.now(UTC)
        try:
            output = handler(payload)
        except Exception as exc:  # pokwitowanie należy się także porażce
            completed = datetime.now(UTC)
            receipt = build_receipt(
                bound, operation, state="failed",
                output={"error": type(exc).__name__, "message": str(exc)},
                started_at=started, completed_at=completed,
                error_code=type(exc).__name__,
            )
            raise SurfaceError(f"{operation.id}: {exc}") from _WithReceipt(receipt, exc)
        completed = datetime.now(UTC)
        receipt = build_receipt(
            bound, operation, state="succeeded", output=output,
            started_at=started, completed_at=completed,
            verified=bool(output.get("verified")),
        )
        return {
            "schema_id": "twinapi.result/v1",
            "operation": operation.id,
            "plan": bound,
            "output": output,
            "receipt": receipt,
        }

    def _check_binding(self, operation: Operation, payload: dict[str, Any],
                       plan: dict[str, Any]) -> None:
        expected = build_plan(operation, payload, target=self.target,
                              subject=self.subject)["request_sha256"]
        if plan.get("request_sha256") != expected:
            raise SurfaceError(
                "plan opisuje inne wejście niż podane — wykonanie musiałoby zrobić coś "
                "innego, niż pokazał plan"
            )
        if plan.get("process_ref") != build_process(operation)["process_ref"]:
            raise SurfaceError("plan dotyczy innej operacji niż żądana")

    # — pomocnicze —

    @staticmethod
    def fingerprint(payload: dict[str, Any]) -> str:
        return digest(payload)


class _WithReceipt(Exception):
    """Nosi pokwitowanie porażki, żeby nie ginęło razem z wyjątkiem."""

    def __init__(self, receipt: dict[str, Any], cause: BaseException) -> None:
        super().__init__(str(cause))
        self.receipt = receipt


def receipt_of(error: BaseException) -> dict[str, Any] | None:
    """Pokwitowanie porażki, jeśli wyjątek je niesie."""
    cause = error.__cause__
    return getattr(cause, "receipt", None)


__all__ = ["Surface", "SurfaceError", "receipt_of"]
