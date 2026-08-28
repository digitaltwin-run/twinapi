"""Routing procesów jako deklaracja, nie jako słownik w kodzie.

Plan POA twierdzi `transport_from_registry: true` — że to, co zostanie wykonane,
wynika z rejestru, a nie z tego, co akurat wywoła adapter. Dopóki wiązanie
operacji z funkcją było literałem w kodzie adoptera, to twierdzenie nie miało
pokrycia: rejestr *był* kodem, a dodanie operacji wymagało edycji tego samego
pliku, który ją potem wykonuje.

Tutaj rejestr jest **danymi**: manifest wiąże URI procesu z funkcją po nazwie,
a `bind()` importuje ją dopiero przy budowie powierzchni. Dodanie operacji to
wpis w manifeście i funkcja — bez dotykania kodu powierzchni, adapterów ani
planowania.

Manifest nie może wymyślić operacji: każdy wpis musi wskazywać czasownik,
który zna słownik standardu. Routing jest wolny, słownik zamknięty.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .poa import (
    capability_ref,
    digest,
    process_ref,
    process_uri,
    target_ref,
    verification_ref,
)
from .registry import Registry
from .vocabulary import Vocabulary, VocabularyError, describe

SCHEMA = "twinapi.processes/v1"
ROUTING_SCHEMA = "twinapi.routing/v1"
HANDLER_ADAPTER_REF = "adapter://digitaltwin.run/twinapi/python-handler/v1"


class ProcessError(RuntimeError):
    """Manifest, którego nie da się związać z kodem bez zgadywania."""


@dataclass(frozen=True)
class Binding:
    """Jedno wiązanie: URI procesu → funkcja, która je wykonuje."""

    uri: str
    operation: str
    handler: str


def _resolve(reference: str):
    """`moduł:funkcja` → wywoływalne. Import dopiero tutaj, nie przy starcie."""
    if ":" not in reference:
        raise ProcessError(
            f"wiązanie {reference!r} musi mieć postać `moduł:funkcja`"
        )
    module_name, attribute = reference.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ProcessError(f"nie da się zaimportować {module_name!r}: {exc}") from exc
    try:
        found = getattr(module, attribute)
    except AttributeError as exc:
        raise ProcessError(f"{module_name!r} nie ma {attribute!r}") from exc
    if not callable(found):
        raise ProcessError(f"{reference!r} nie jest wywoływalne")
    return found


def load_processes(path: Path) -> dict[str, Any]:
    """Wczytuje manifest routingu i sprawdza jego własny kształt."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProcessError(f"nie da się wczytać manifestu procesów {path}: {exc}") from exc
    if document.get("schema_id") != SCHEMA:
        raise ProcessError(f"manifest procesów musi deklarować schema_id {SCHEMA}")
    if not document.get("processes"):
        raise ProcessError("manifest nie wiąże ani jednego procesu")
    return document


def bindings(document: dict[str, Any], vocabulary: Vocabulary, target: str) -> list[Binding]:
    """Wiązania sprawdzone wobec słownika — manifest nie wymyśli czasownika."""
    found: list[Binding] = []
    seen: set[str] = set()
    for entry in document["processes"]:
        operation_id = str(entry.get("operation") or "")
        operation = vocabulary.get(operation_id)  # nieznana operacja to błąd
        expected = process_uri(operation, target)
        uri = str(entry.get("uri") or expected)
        if uri != expected:
            raise ProcessError(
                f"wiązanie {operation_id} deklaruje URI {uri!r}, a proces tej operacji "
                f"na celu {target!r} to {expected!r} — rozjazd routingu z planem"
            )
        if uri in seen:
            raise ProcessError(f"URI {uri} związany dwa razy")
        seen.add(uri)
        found.append(Binding(uri=uri, operation=operation_id,
                             handler=str(entry.get("handler") or "")))
    return found


def bind(vocabulary: Vocabulary, document: dict[str, Any], *, target: str,
         allow_promotion: bool = False) -> Registry:
    """Buduje rejestr z manifestu: wykonawcy, bramki i — opcjonalnie — promotor."""
    registry = Registry(vocabulary)
    for binding in bindings(document, vocabulary, target):
        registry.register(binding.operation, _resolve(binding.handler))
    for entry in document.get("gates") or []:
        try:
            registry.register_gate(str(entry.get("name")), _resolve(str(entry.get("handler"))))
        except VocabularyError as exc:
            raise ProcessError(str(exc)) from exc
    promoter = document.get("promoter")
    if promoter and allow_promotion:
        registry.register_promoter(_resolve(str(promoter)))
    return registry


def routing(document: dict[str, Any], vocabulary: Vocabulary, target: str) -> dict[str, Any]:
    """Tablica routingu z tymi samymi referencjami, które trafią do planu POA."""
    resolved = bindings(document, vocabulary, target)
    projection = {
        "schema_id": ROUTING_SCHEMA,
        "registry_schema_id": SCHEMA,
        "registry_sha256": digest(document),
        "target": target,
        "target_ref": target_ref(target),
        "standards": describe(vocabulary)["packs"],
        "processes": [
            {
                "uri": binding.uri,
                "process_uri": binding.uri,
                "process_ref": process_ref(vocabulary.get(binding.operation)),
                "capability_ref": capability_ref(vocabulary.get(binding.operation)),
                "adapter_ref": HANDLER_ADAPTER_REF,
                "operation": binding.operation,
                "handler": binding.handler,
            }
            for binding in resolved
        ],
        "gates": [entry.get("name") for entry in document.get("gates") or []],
        "verification": [
            {
                "name": str(entry.get("name")),
                **verification_ref(str(entry.get("name"))),
                "adapter_ref": HANDLER_ADAPTER_REF,
                "handler": entry.get("handler"),
            }
            for entry in document.get("gates") or []
        ],
        "promoter": document.get("promoter"),
    }
    projection["routing_sha256"] = digest(projection)
    return projection
