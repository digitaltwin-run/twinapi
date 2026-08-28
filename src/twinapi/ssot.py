"""Jedno źródło prawdy dla modelu — stan, słownik i granice w jednym dokumencie.

Model, który ma zaproponować dobrą zmianę, potrzebuje sześciu rzeczy naraz: co
jest teraz nie tak, jakie czasowniki wolno mu użyć, który czasownik zamyka które
naruszenie, co zostanie sprawdzone, kto rozstrzyga spory między plikami i co już
się w tym projekcie działo. Zbieranie tego z sześciu miejsc kończy się tym, że
model zgaduje brakującą część.

`build()` składa to w jeden dokument o zamkniętym kształcie. Wszystkie nazwy
w nim pochodzą ze standardu — reguły, operacje, bramki, kody diagnostyczne —
więc model nie ma skąd wziąć czasownika, którego nie ma.

`request_schema()` domyka to z drugiej strony: opisuje, co model **może
odpowiedzieć**. Nie jest to opis swobodny — `operation` ma wyliczenie ze
słownika, a operacja wymagająca zgody ma `approved` jako pole wymagane. Model
generujący pod tym schematem nie umie poprosić o zmianę, której nie wolno
zaproponować.
"""
from __future__ import annotations

from typing import Any

SCHEMA = "twinapi.ssot/v1"


def request_schema(vocabulary, *, implemented: set[str] | None = None) -> dict[str, Any]:
    """Zamknięty kształt żądania zmiany — do generowania pod ograniczeniem."""
    allowed = sorted(item.id for item in vocabulary
                     if implemented is None or item.id in implemented)
    needing_consent = sorted(item.id for item in vocabulary
                             if item.requires_approval
                             and (implemented is None or item.id in implemented))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://digitaltwin.run/schemas/twinapi/change-request.v1.json",
        "title": "Żądanie zmiany ograniczone do słownika standardu",
        "type": "object",
        "additionalProperties": False,
        "required": ["operation", "input", "why"],
        "properties": {
            "operation": {"enum": allowed,
                          "description": "Czasownik ze słownika; innego nie ma."},
            "input": {"type": "object",
                      "description": "Wejście operacji. Wymiary podawaj jako liczby "
                                     "całkowite w mikrometrach (`at_um`), nie jako ułamki "
                                     "milimetra — plan jest wiązany haszem kanonicznym, "
                                     "a ten nie ma jednoznacznego zapisu dla `float`."},
            "why": {"type": "string", "minLength": 1,
                    "description": "Które naruszenie ta zmiana zamyka i dlaczego akurat ta "
                                   "operacja."},
            "approved": {"type": "boolean",
                         "description": "Zgoda człowieka. Wymagana dla: "
                                        + ", ".join(needing_consent)},
        },
        "allOf": [
            {
                "if": {"properties": {"operation": {"const": name}},
                       "required": ["operation"]},
                "then": {"required": ["operation", "input", "why", "approved"],
                         "properties": {"approved": {"const": True}}},
            }
            for name in needing_consent
        ],
    }


def build(surface, *, history_limit: int = 10) -> dict[str, Any]:
    """Stan, słownik, granice i pamięć projektu w jednym dokumencie."""
    description = surface.describe()
    implemented = set(description["implemented"])
    findings = list(surface.registry.reporter() if surface.registry.reporter else [])
    for finding in findings:
        finding["repairs"] = surface.repairs_for(str(finding.get("rule") or ""))
    history = surface.history(history_limit)
    return {
        "schema_id": SCHEMA,
        "target": surface.target,
        "standards": description["packs"],
        "state": {
            "findings": findings,
            "unrepairable": [item["rule"] for item in findings
                             if not any(repair["implemented"] for repair in item["repairs"])],
        },
        "vocabulary": {
            "operations": description["operations"],
            "implemented": description["implemented"],
            "declared_only": description["declared_only"],
        },
        "routing": {
            "process_uris": {
                entry["id"]: surface.plan(entry["id"], {})["steps"][0]["process_uri"]
                for entry in description["operations"] if entry["id"] in implemented
            },
        },
        "gates": sorted({name for item in surface.vocabulary for name in item.verify}),
        "gates_implemented": sorted(surface.registry.gates),
        "history": {
            "entries": history.get("entries", []),
            "chain": history.get("chain", []),
        },
        "request_schema": request_schema(surface.vocabulary, implemented=implemented),
        "how_to_answer": (
            "Odpowiedz jednym obiektem zgodnym z `request_schema`. Wybierz operację, "
            "która zamyka naruszenie z `state.findings` — pole `repairs` przy każdym "
            "naruszeniu mówi, które to są. Operacja spoza `vocabulary.implemented` nie "
            "zostanie wykonana; operacja z `requires_approval` bez `approved: true` "
            "zostanie odrzucona przed dotknięciem plików."
        ),
    }
