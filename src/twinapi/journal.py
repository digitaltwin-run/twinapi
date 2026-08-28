"""Historia zmian jako łańcuch haszy — dopisywana, nie nadpisywana.

Projekt miał już strumień zdarzeń w kształcie `wellmanifest.logs/event/v1`:
203 wpisy, łańcuch bez przerwania, pełny cykl życia zmiany od `change_planned`
po `revision_promoted`. Nie miał w nim natomiast **żadnej** zmiany zrobionej
z powłoki — bo strumień karmił tylko backend, a skrypty pisały kandydatów obok.
Pięciu kandydatów powstało bez jednego śladu w historii projektu.

Ten moduł domyka tę lukę: każde wykonanie przez `twinapi`, niezależnie od
transportu, dopisuje wpis do tego samego strumienia. Kanonizacja jest ta sama,
której używa reszta pakietu (posortowane klucze, zapis zwarty, SHA-256), więc
łańcuch zostaje policzalny dla każdego, kto go czyta — sprawdziłem to na
istniejącym pliku, zanim cokolwiek dopisałem.

Dwie rzeczy są tu ważniejsze, niż wyglądają:

* **Dowody.** Wpis niosący samą nazwę operacji mówi, że coś się stało, ale nie
  pozwala tego sprawdzić. `evidence` to ścieżki z sumami — dopiero one czynią
  historię weryfikowalną, a nie tylko czytelną.
* **Blokada pliku.** Do strumienia pisze też ktoś inny. Łańcuch haszy, którego
  ogon czyta się bez zamka, rozpada się przy pierwszym równoległym zapisie —
  i to w sposób, który wychodzi dopiero przy audycie.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "wellmanifest.logs/event/v1"
SEVERITIES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
OUTCOMES = ("OBSERVED", "ACCEPTED", "REJECTED", "SUCCEEDED", "FAILED")
MODES = ("PLAN", "APPLY")
# Pierwszy wpis nie ma poprzednika, ale musi mieć czym się zakotwiczyć.
# Strumień, do którego dopisujemy, używa hasza zerowego — przejmujemy tę
# konwencję zamiast narzucać własną, żeby świeży strumień wyglądał jak ten,
# który już istnieje.
GENESIS = "0" * 64


class JournalError(RuntimeError):
    """Wpis, którego nie wolno dopisać, albo łańcuch, któremu nie wolno ufać."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def digest_of(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def evidence_for(paths: list[Path | str], root: Path | None = None) -> list[dict[str, str]]:
    """Ścieżki z sumami — to one czynią wpis weryfikowalnym, a nie tylko czytelnym."""
    entries: list[dict[str, str]] = []
    for item in paths:
        path = Path(item)
        if not path.is_file():
            continue
        relative = path.relative_to(root) if root and path.is_relative_to(root) else path
        entries.append({
            "path": relative.as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    return entries


@dataclass
class Journal:
    """Dopisywalny strumień zdarzeń w kształcie `wellmanifest.logs`."""

    path: Path
    stream: str = "eda"
    source: str = "twinapi"
    producer: str = "human:operator"
    subject_ref: str = "twinapi:project"
    _lock: Any = field(default=None, repr=False)

    def tail(self) -> tuple[int, str]:
        """Numer i hasz ostatniego wpisu — punkt zaczepienia dla następnego."""
        if not self.path.is_file():
            return 0, GENESIS
        last = None
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    last = line
        if last is None:
            return 0, GENESIS
        entry = json.loads(last)
        return int(entry.get("sequence") or 0), entry.get("eventHash")

    def append(self, *, event_type: str, outcome: str, severity: str = "INFO",
               mode: str = "APPLY", correlation_id: str, causation_id: str | None = None,
               input_hash: str, evidence: list[dict[str, str]] | None = None,
               code: str | None = None, receipt_ref: str | None = None,
               subject_state: str | None = None) -> dict[str, Any]:
        """Dopisuje wpis, licząc ogon łańcucha pod zamkiem."""
        if severity not in SEVERITIES:
            raise JournalError(f"waga {severity!r} spoza słownika {SEVERITIES}")
        if outcome not in OUTCOMES:
            raise JournalError(f"wynik {outcome!r} spoza słownika {OUTCOMES}")
        if mode not in MODES:
            raise JournalError(f"tryb {mode!r} spoza słownika {MODES}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        with self.path.open("r+", encoding="utf-8") as handle:
            self._acquire(handle)
            try:
                sequence, previous = self.tail()
                entry: dict[str, Any] = {
                    "schema": SCHEMA,
                    "stream": self.stream,
                    "source": self.source,
                    "producer": self.producer,
                    "sequence": sequence + 1,
                    "eventId": f"event:{self.source}:{correlation_id}:{sequence + 1}",
                    "eventType": event_type,
                    "occurredAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    "severity": severity,
                    "outcome": outcome,
                    "mode": mode,
                    "correlationId": correlation_id,
                    "causationId": causation_id,
                    "code": code,
                    "evidence": evidence or [],
                    "inputHash": input_hash,
                    "previousHash": previous,
                    "receiptRef": receipt_ref,
                    "subjectRef": self.subject_ref,
                    "subjectState": subject_state,
                    "rawOutputIncluded": False,
                    "secretMaterialIncluded": False,
                }
                entry["eventHash"] = digest_of(entry)
                handle.seek(0, os.SEEK_END)
                handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                self._release(handle)
        return entry

    def read(self, limit: int = 20, *, event_type: str | None = None,
             source: str | None = None) -> list[dict[str, Any]]:
        """Ostatnie wpisy — droga odczytu, oddzielona od dopisywania.

        CQRS nie jest tu ozdobą: strumień jest dopisywalny i tylko dopisywalny,
        więc czytanie nie może dzielić kodu z zapisem, żeby nie kusiło do
        „poprawienia" historii przy okazji.
        """
        if not self.path.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if event_type and entry.get("eventType") != event_type:
                continue
            if source and entry.get("source") != source:
                continue
            entries.append(entry)
        return entries[-limit:] if limit > 0 else entries

    def verify(self) -> list[str]:
        """Przerwania łańcucha i podmienione wpisy — z numerami, nie ogólnikami."""
        problems: list[str] = []
        if not self.path.is_file():
            return problems
        previous = GENESIS
        expected = 0
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            expected += 1
            if entry.get("sequence") != expected:
                problems.append(
                    f"wiersz {number}: numer {entry.get('sequence')}, oczekiwano {expected}")
            if entry.get("previousHash") != previous:
                problems.append(f"wiersz {number}: łańcuch przerwany")
            body = {key: value for key, value in entry.items() if key != "eventHash"}
            if digest_of(body) != entry.get("eventHash"):
                problems.append(f"wiersz {number}: hasz nie odpowiada treści wpisu")
            previous = entry.get("eventHash")
        return problems

    # — zamek —

    @staticmethod
    def _acquire(handle) -> None:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            # Bez blokady zapis nadal działa; ryzykiem jest wyścig przy zapisie
            # równoległym, nie poprawność pojedynczego wpisu.
            pass

    @staticmethod
    def _release(handle) -> None:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
