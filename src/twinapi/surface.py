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

from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from .journal import Journal
from .poa import build_plan, build_process, build_receipt, digest, verify_plan
from .registry import Registry
from .vocabulary import Operation, describe


class SurfaceError(RuntimeError):
    """Żądanie, którego nie da się spełnić bez łamania kontraktu."""


class Surface:
    """Słownik + rejestr + POA. Wszystko, czego potrzebuje każdy z transportów."""

    def __init__(self, registry: Registry, *, target: str,
                 subject: str = "human:operator",
                 journal: Journal | None = None) -> None:
        self.registry = registry
        self.vocabulary = registry.vocabulary
        self.target = target
        self.subject = subject
        # Bez dziennika zmiana zostawia kandydata i żadnego śladu w historii
        # projektu. Z dziennikiem — wpis z dowodami, niezależnie od transportu.
        self.journal = journal

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

    def history(self, limit: int = 20, *, event_type: str | None = None,
                source: str | None = None) -> dict[str, Any]:
        """Historia zmian projektu wraz z oceną spójności łańcucha."""
        if self.journal is None:
            return {"schema_id": "twinapi.history/v1", "available": False, "entries": [],
                    "chain": ["ten projekt nie prowadzi dziennika zmian"]}
        return {
            "schema_id": "twinapi.history/v1",
            "available": True,
            "path": str(self.journal.path),
            "entries": self.journal.read(limit, event_type=event_type, source=source),
            "chain": self.journal.verify(),
        }

    # — plan —

    def plan(self, operation_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        operation = self.vocabulary.get(operation_id)
        return build_plan(operation, payload or {}, target=self.target, subject=self.subject)

    # — weryfikacja —

    def verify(self, operation_id: str, context: dict[str, Any]) -> dict[str, Any]:
        """Uruchamia bramki, które ta operacja deklaruje — po nazwie, nie z kodu.

        Operacja mówi, co musi przejść; rejestr mówi, kto to umie policzyć.
        Bramka zadeklarowana, a niezarejestrowana, jest **brakiem kontroli**
        i tak się liczy: `unavailable` blokuje, bo cisza wygląda tak samo jak
        zaliczenie, a nie jest tym samym.
        """
        operation = self.vocabulary.get(operation_id)
        results: dict[str, Any] = {}
        for name in operation.verify:
            gate = self.registry.gate(name)
            if gate is None:
                results[name] = {"status": "unavailable", "blocking": True,
                                 "codes": [f"GATE_NOT_REGISTERED:{name}"]}
                continue
            try:
                results[name] = gate(context)
            except Exception as exc:  # noqa: BLE001 - awaria bramki to brak kontroli
                results[name] = {"status": "unavailable", "blocking": True,
                                 "codes": [f"GATE_FAILED:{name}"], "message": str(exc)}
        blocking = sorted(name for name, item in results.items() if item.get("blocking"))
        return {
            "schema_id": "twinapi.verification/v1",
            "operation": operation.id,
            "declared": list(operation.verify),
            "gates": results,
            "blocking": blocking,
            "status": "blocked" if blocking else "passed",
        }

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
        correlation = bound["request_sha256"][:16]
        self._record(operation, "eda.change_planned", "OBSERVED", correlation,
                     bound["request_sha256"], mode="PLAN")
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
            self._record(operation, "eda.change_plan_failed", "FAILED", correlation,
                         bound["request_sha256"], severity="ERROR",
                         code=type(exc).__name__,
                         receipt_ref=f"sha256:{receipt['receipt_hash']}")
            raise SurfaceError(f"{operation.id}: {exc}") from _WithReceipt(receipt, exc)
        completed = datetime.now(UTC)
        receipt = build_receipt(
            bound, operation, state="succeeded", output=output,
            started_at=started, completed_at=completed,
            verified=bool(output.get("verified")),
        )
        self._record(operation, "eda.candidate_created", "SUCCEEDED", correlation,
                     bound["request_sha256"],
                     evidence=list(output.get("evidence") or []),
                     receipt_ref=f"sha256:{receipt['receipt_hash']}",
                     subject_state=str(output.get("candidate") or ""))
        return {
            "schema_id": "twinapi.result/v1",
            "operation": operation.id,
            "plan": bound,
            "output": output,
            "receipt": receipt,
        }

    def apply(self, operation_id: str, payload: dict[str, Any] | None = None, *,
              approved: bool = False, promote: bool = False) -> dict[str, Any]:
        """Pełny cykl: plan → kandydat → bramki → (opcjonalnie) wpisanie do projektu.

        Automatyczne przyjęcie zmiany jest bezpieczne dokładnie wtedy, gdy
        bramki, które operacja deklaruje, są **zarejestrowane i przeszły**.
        Bramka zadeklarowana, a nieumiana, blokuje — bo „nie sprawdziłem"
        i „sprawdziłem, jest dobrze" muszą się różnić.
        """
        result = self.execute(operation_id, payload, approved=approved)
        context = {"operation": operation_id, "target": self.target,
                   "output": result["output"]}
        verification = self.verify(operation_id, context)
        result["verification"] = verification
        correlation = result["plan"]["request_sha256"][:16]
        operation = self.vocabulary.get(operation_id)
        self._record(operation, "eda.validation_completed",
                     "ACCEPTED" if verification["status"] == "passed" else "REJECTED",
                     correlation, result["plan"]["request_sha256"],
                     severity="INFO" if verification["status"] == "passed" else "WARNING",
                     subject_state=verification["status"])
        result["promoted"] = False
        if not promote:
            return result
        if verification["status"] != "passed":
            raise SurfaceError(
                f"{operation_id}: bramki {', '.join(verification['blocking'])} nie przeszły — "
                "zmiana nie zostanie wpisana do projektu"
            )
        if self.registry.promoter is None:
            raise SurfaceError(
                f"{operation_id}: ten projekt jest propose-only — nikt nie zarejestrował "
                "kodu wpisującego kandydata do projektu"
            )
        promotion = self.registry.promoter(result)
        result["promoted"] = True
        result["promotion"] = promotion
        self._record(operation, "eda.change_accepted", "ACCEPTED", correlation,
                     result["plan"]["request_sha256"],
                     evidence=list(promotion.get("evidence") or []),
                     subject_state=str(promotion.get("revision") or ""))
        self._record(operation, "eda.revision_promoted", "ACCEPTED", correlation,
                     result["plan"]["request_sha256"],
                     evidence=list(promotion.get("evidence") or []))
        return result

    def _record(self, operation: Operation, event_type: str, outcome: str,
                correlation: str, input_hash: str, *, severity: str = "INFO",
                mode: str = "APPLY", evidence: list | None = None,
                code: str | None = None, receipt_ref: str | None = None,
                subject_state: str | None = None) -> None:
        """Dopisuje ślad do historii projektu; brak dziennika nie jest błędem.

        Zapis do dziennika nie może wywrócić zmiany, która się udała: historia
        jest świadkiem, nie warunkiem. Gdy strumień jest niedostępny, zmiana
        zostaje, a ślad — nie, i to jest mniejsze zło niż odwrotnie.
        """
        if self.journal is None:
            return
        with suppress(Exception):  # historia jest świadkiem, nie warunkiem
            self.journal.append(
                event_type=event_type, outcome=outcome, severity=severity, mode=mode,
                correlation_id=correlation, causation_id=operation.id,
                input_hash=input_hash, evidence=evidence, code=code,
                receipt_ref=receipt_ref, subject_state=subject_state or None,
            )

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
