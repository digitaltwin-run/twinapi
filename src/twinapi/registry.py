"""Wiązanie operacji ze słownika z kodem, który ją wykonuje.

Rejestr jest jedynym miejscem, gdzie projekt-gospodarz mówi „tę operację umiem".
Wszystko inne — cztery transporty, plany, pokwitowania — bierze się z tego
wiązania i ze słownika. Zarejestrować da się wyłącznie operację, którą standard
zna: to jest ta sama granica, co przy regułach, tylko od strony zmian.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .vocabulary import Vocabulary, VocabularyError

Handler = Callable[[dict[str, Any]], dict[str, Any]]
# Bramka dostaje wynik operacji i zwraca orzeczenie w kształcie, który znają
# wszystkie bramki tego projektu: `status`, `blocking`, `codes`.
Gate = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class Registry:
    """Operacja → funkcja, która buduje kandydata i zwraca opis wyniku."""

    vocabulary: Vocabulary
    handlers: dict[str, Handler] = field(default_factory=dict)
    gates: dict[str, Gate] = field(default_factory=dict)
    promoter: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    def register(self, operation_id: str, handler: Handler) -> None:
        self.vocabulary.get(operation_id)  # nieznana operacja to błąd, nie rozszerzenie
        if operation_id in self.handlers:
            raise VocabularyError(f"operacja {operation_id} ma już wykonawcę")
        self.handlers[operation_id] = handler

    def handler(self, operation_id: str) -> Handler:
        try:
            return self.handlers[operation_id]
        except KeyError:
            self.vocabulary.get(operation_id)
            raise VocabularyError(
                f"operacja {operation_id} jest w słowniku, ale ten projekt jej nie umie"
            ) from None

    def register_gate(self, name: str, gate: Gate) -> None:
        """Wiąże nazwę bramki ze słownika z kodem, który ją wykonuje.

        Operacje deklarują bramki po nazwie (`drc_no_regression`, `net_parity`,
        …). Gdyby weryfikacja była wpisana w kod powierzchni, dodanie bramki do
        standardu wymagałoby zmiany w każdym adopterze — a tak wymaga jednej
        rejestracji w tym, który ją umie.
        """
        known = {name for operation in self.vocabulary for name in operation.verify}
        if name not in known:
            raise VocabularyError(
                f"bramka {name!r} nie występuje w żadnej operacji słownika; "
                f"słownik zna: {', '.join(sorted(known))}"
            )
        self.gates[name] = gate

    def gate(self, name: str) -> Gate | None:
        return self.gates.get(name)

    def register_promoter(self, promoter: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        """Kod, który wpisuje przyjętego kandydata do projektu.

        Rejestracja jest osobna od wykonawców, bo to jedyne miejsce w całym
        łańcuchu, które **zmienia projekt**, a nie tylko produkuje propozycję.
        Projekt, który nie zarejestruje promotora, jest propose-only i nie da się
        tego obejść żadnym parametrem.
        """
        self.promoter = promoter

    @property
    def implemented(self) -> tuple[str, ...]:
        return tuple(sorted(self.handlers))

    @property
    def declared_only(self) -> tuple[str, ...]:
        """Operacje, które standard zna, a projekt jeszcze nie umie.

        To nie jest defekt — to jest lista rzeczy, których nie wolno udawać, że
        się potrafi. Transporty pokazują ją wprost, zamiast milczeć.
        """
        return tuple(sorted(item.id for item in self.vocabulary
                            if item.id not in self.handlers))
