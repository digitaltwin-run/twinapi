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


@dataclass
class Registry:
    """Operacja → funkcja, która buduje kandydata i zwraca opis wyniku."""

    vocabulary: Vocabulary
    handlers: dict[str, Handler] = field(default_factory=dict)

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
