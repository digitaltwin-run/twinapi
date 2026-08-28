"""Słownik operacji wczytany z paczki standardu, nie wpisany w kod.

Kod, który zna listę dozwolonych zmian z własnych stałych, jest jedyną wersją
prawdy do chwili, gdy ktoś doda piątą zmianę w innym miejscu. Tutaj słownik jest
danymi: paczka `wellmanifest/pcb` albo `wellmanifest/sch` deklaruje operacje,
a `twinapi` je tylko czyta. Operacji spoza słownika nie da się wystawić, bo nie
ma jej skąd wziąć.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STANDARD_FILES = {
    "pcb": "pcb-standard.json",
    "sch": "sch-standard.json",
}

DISCOVERY = (
    "$WELLMANIFEST_{PACK}_STANDARD",
    "~/github/wellmanifest/{pack}",
    "../wellmanifest/{pack}",
)


class VocabularyError(RuntimeError):
    """Brak słownika albo słownik niezgodny z własną deklaracją."""


@dataclass(frozen=True)
class Operation:
    """Jedna dozwolona zmiana, tak jak opisuje ją standard."""

    id: str
    scope: str
    entity: str
    changes: str
    clears: tuple[str, ...]
    verify: tuple[str, ...]
    reversible: bool
    why: str
    pack: str

    @property
    def kind(self) -> str:
        """POA rozróżnia odczyt od zmiany; każda operacja tutaj zmienia stan."""
        return "command"

    @property
    def effects(self) -> tuple[str, ...]:
        """Skutki w słowniku POA — z tego, co operacja rusza.

        `bom` jest jedynym skutkiem, który wychodzi poza pliki projektu: dokłada
        albo usuwa część, więc zmienia listę zakupów i montaż.
        """
        if self.changes == "bom":
            return ("local_write", "external_write")
        return ("local_write",)

    @property
    def requires_approval(self) -> bool:
        """Nieodwracalne i dotykające miedzi wymagają zgody człowieka."""
        return not self.reversible or self.changes in {"copper", "bom", "netlist"}


@dataclass(frozen=True)
class Vocabulary:
    """Wszystkie operacje z jednej albo wielu paczek standardu."""

    operations: tuple[Operation, ...]
    packs: tuple[tuple[str, str], ...]  # (id paczki, wersja)

    def __post_init__(self) -> None:
        seen: dict[str, str] = {}
        for operation in self.operations:
            if operation.id in seen:
                raise VocabularyError(
                    f"operacja {operation.id} zadeklarowana w dwóch paczkach: "
                    f"{seen[operation.id]} i {operation.pack}"
                )
            seen[operation.id] = operation.pack

    def __iter__(self):
        return iter(self.operations)

    def __len__(self) -> int:
        return len(self.operations)

    def get(self, operation_id: str) -> Operation:
        for operation in self.operations:
            if operation.id == operation_id:
                return operation
        known = ", ".join(sorted(item.id for item in self.operations))
        raise VocabularyError(f"nieznana operacja {operation_id!r}; słownik zna: {known}")

    def scoped(self, scope: str) -> tuple[Operation, ...]:
        return tuple(item for item in self.operations if item.scope == scope)

    def clearing(self, rule_id: str) -> tuple[Operation, ...]:
        """Operacje, którymi da się zamknąć to naruszenie.

        To jest most między raportem a naprawą: reguła mówi, co jest defektem,
        a ta metoda odpowiada, co wolno z tym zrobić.
        """
        return tuple(item for item in self.operations if rule_id in item.clears)


def _find_pack(pack: str) -> Path:
    override = os.environ.get(f"WELLMANIFEST_{pack.upper()}_STANDARD")
    candidates = [Path(override)] if override else []
    candidates.append(Path.home() / "github" / "wellmanifest" / pack)
    # Repozytorium siostrzane obok naszego. W kontenerze pakiet bywa zainstalowany
    # płytko, więc sięganie w górę musi znieść brak katalogów — inaczej brak
    # sąsiada jest awarią zamiast po prostu kolejnym nietrafionym miejscem.
    here = Path(__file__).resolve()
    for level in (3, 4):
        try:
            candidates.append(here.parents[level] / "wellmanifest" / pack)
        except IndexError:
            break
    for candidate in candidates:
        if (candidate / STANDARD_FILES[pack]).is_file():
            return candidate
    raise VocabularyError(
        f"nie znaleziono paczki wellmanifest/{pack}; wskaż ją przez "
        f"WELLMANIFEST_{pack.upper()}_STANDARD"
    )


def load_vocabulary(*packs: str, roots: dict[str, Path] | None = None) -> Vocabulary:
    """Wczytuje operacje z paczek standardu i zszywa je w jeden słownik."""
    if not packs:
        packs = tuple(STANDARD_FILES)
    operations: list[Operation] = []
    versions: list[tuple[str, str]] = []
    for pack in packs:
        if pack not in STANDARD_FILES:
            raise VocabularyError(f"nieznana paczka standardu {pack!r}")
        root = (roots or {}).get(pack) or _find_pack(pack)
        document = json.loads((root / STANDARD_FILES[pack]).read_text(encoding="utf-8"))
        declared = document.get("operations")
        if not declared:
            raise VocabularyError(
                f"wellmanifest/{pack} {document.get('version')} nie deklaruje operacji — "
                "potrzebna paczka ze słownikiem zmian"
            )
        versions.append((document["id"], document["version"]))
        for item in declared:
            operations.append(Operation(
                id=item["id"], scope=item["scope"], entity=item["entity"],
                changes=item["changes"], clears=tuple(item["clears"]),
                verify=tuple(item["verify"]), reversible=bool(item["reversible"]),
                why=item["why"], pack=document["id"],
            ))
    return Vocabulary(tuple(operations), tuple(versions))


def describe(vocabulary: Vocabulary) -> dict[str, Any]:
    """Słownik w postaci, którą da się oddać każdemu z czterech transportów."""
    return {
        "schema_id": "twinapi.vocabulary/v1",
        "packs": [{"id": pack, "version": version} for pack, version in vocabulary.packs],
        "operations": [
            {
                "id": operation.id,
                "scope": operation.scope,
                "entity": operation.entity,
                "changes": operation.changes,
                "clears": list(operation.clears),
                "verify": list(operation.verify),
                "reversible": operation.reversible,
                "requires_approval": operation.requires_approval,
                "why": operation.why,
                "pack": operation.pack,
            }
            for operation in vocabulary
        ],
    }
