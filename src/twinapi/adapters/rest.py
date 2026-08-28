"""REST: ten sam słownik jako zasoby, plan jako osobny krok.

Endpointy nie znają operacji z osobna — `{operation}` jest parametrem ścieżki
sprawdzanym wobec słownika. Plan ma własny endpoint, bo „pokaż, co zrobisz"
i „zrób" to dwie różne decyzje i nie powinny dzielić jednego wywołania.
"""
from __future__ import annotations

from typing import Any

from ..surface import Surface, SurfaceError, receipt_of
from ..vocabulary import VocabularyError


def build_router(surface: Surface, prefix: str = "/api/twinapi"):
    """Router FastAPI wygenerowany ze słownika; wymaga zainstalowanego fastapi."""
    try:
        from fastapi import APIRouter, Body, HTTPException
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover - zależność opcjonalna
        raise RuntimeError("adapter REST wymaga fastapi (extras: twinapi[rest])") from exc

    router = APIRouter(prefix=prefix, tags=["twinapi"])
    # FastAPI wymaga wywołania Body() jako domyślnej; wyciągamy je poza sygnaturę,
    # żeby nie budować obiektu przy każdym wywołaniu.
    json_body = Body(default_factory=dict)

    @router.get("/operations")
    def operations() -> JSONResponse:
        return JSONResponse(surface.describe())

    @router.get("/operations/{operation}")
    def process(operation: str) -> JSONResponse:
        try:
            return JSONResponse(surface.process(operation))
        except VocabularyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/repairs/{rule}")
    def repairs(rule: str) -> JSONResponse:
        return JSONResponse({"rule": rule, "operations": surface.repairs_for(rule)})

    @router.post("/plan/{operation}")
    def plan(operation: str, payload: dict[str, Any] = json_body) -> JSONResponse:
        try:
            return JSONResponse(surface.plan(operation, payload))
        except VocabularyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/run/{operation}")
    def run(operation: str, body: dict[str, Any] = json_body) -> JSONResponse:
        try:
            result = surface.execute(
                operation,
                body.get("input") or {},
                plan=body.get("plan"),
                approved=bool(body.get("approved")),
            )
        except VocabularyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except SurfaceError as exc:
            receipt = receipt_of(exc)
            # 409, nie 500: żądanie było zrozumiałe, ale stan albo zgoda go nie
            # dopuszczają. Pokwitowanie porażki jedzie w treści, żeby nie ginęło.
            raise HTTPException(409, {"error": str(exc), "receipt": receipt}) from exc
        return JSONResponse(result)

    return router
