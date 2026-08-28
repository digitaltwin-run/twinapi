"""MCP: każda operacja jako narzędzie, plan jako narzędzie osobne.

Model dostaje dokładnie ten sam słownik, co człowiek w powłoce — łącznie
z informacją, które operacje wymagają zgody. Narzędzie zmieniające stan nie
wykona się bez `approved`, więc „poproś o zgodę" nie jest uprzejmością warstwy
wyżej, tylko własnością kontraktu.
"""
from __future__ import annotations

from typing import Any

from ..surface import Surface, SurfaceError, receipt_of
from ..vocabulary import VocabularyError


def _schema(operation) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "input": {
            "type": "object",
            "description": "Wejście operacji zgodne z jej kontacktem DSL.",
        }
    }
    required: list[str] = []
    if operation.requires_approval:
        properties["approved"] = {
            "type": "boolean",
            "description": (
                f"Zgoda na zmianę: operacja rusza {operation.changes} i jest "
                + ("nieodwracalna." if not operation.reversible else "odwracalna.")
            ),
        }
        required.append("approved")
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


def list_tools(surface: Surface) -> list[dict[str, Any]]:
    """Lista narzędzi MCP zbudowana ze słownika, nie z ręcznej tabeli."""
    tools: list[dict[str, Any]] = [{
        "name": "twinapi_list",
        "description": "Słownik dozwolonych zmian wraz z tym, które są zaimplementowane.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    }, {
        "name": "twinapi_plan",
        "description": "Pokaż plan zmiany i jego hash, nie zmieniając niczego.",
        "inputSchema": {
            "type": "object",
            "properties": {"operation": {"type": "string"}, "input": {"type": "object"}},
            "required": ["operation"],
            "additionalProperties": False,
        },
    }]
    for operation in surface.vocabulary:
        if operation.id not in surface.registry.handlers:
            continue
        tools.append({
            "name": f"twinapi_{operation.id}",
            "description": f"{operation.why} Zamyka: "
                           f"{', '.join(operation.clears) or 'nic wprost'}.",
            "inputSchema": _schema(operation),
        })
    return tools


def call_tool(surface: Surface, name: str, arguments: dict[str, Any] | None = None
              ) -> dict[str, Any]:
    """Wywołanie narzędzia MCP; błąd wraca jako treść, nie jako wyjątek transportu."""
    arguments = arguments or {}
    try:
        if name == "twinapi_list":
            return {"isError": False, "content": surface.describe()}
        if name == "twinapi_plan":
            return {"isError": False,
                    "content": surface.plan(arguments["operation"], arguments.get("input") or {})}
        if not name.startswith("twinapi_"):
            raise VocabularyError(f"nieznane narzędzie {name!r}")
        operation_id = name[len("twinapi_"):]
        result = surface.execute(operation_id, arguments.get("input") or {},
                                 approved=bool(arguments.get("approved")))
        return {"isError": False, "content": result}
    except SurfaceError as exc:
        return {"isError": True, "content": {"error": str(exc), "receipt": receipt_of(exc)}}
    except (VocabularyError, KeyError) as exc:
        return {"isError": True, "content": {"error": str(exc)}}
