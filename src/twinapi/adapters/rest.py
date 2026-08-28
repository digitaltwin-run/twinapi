"""REST: ten sam słownik jako zasoby, plan jako osobny krok.

Endpointy nie znają operacji z osobna — `{operation}` jest parametrem ścieżki
sprawdzanym wobec słownika. Plan ma własny endpoint, bo „pokaż, co zrobisz"
i „zrób" to dwie różne decyzje i nie powinny dzielić jednego wywołania.
"""
from __future__ import annotations

from typing import Any

from ..surface import Surface, SurfaceError, receipt_of
from ..vocabulary import VocabularyError
from . import a2a as _a2a


def build_router(surface: Surface, prefix: str = "/api/twinapi",
                 base_url: str | None = None):
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

    # Odczyt historii jest osobną drogą niż dopisywanie do niej — strumień jest
    # tylko dopisywalny i ma taki zostać.
    # Jedno wywołanie daje modelowi stan, słownik i granice naraz. Zbieranie tego
    # z sześciu endpointów kończy się tym, że model zgaduje brakującą część.
    @router.get("/ssot")
    def ssot(history: int = 10) -> JSONResponse:
        return JSONResponse(surface.ssot(history))

    @router.get("/history")
    def history(limit: int = 20, event_type: str | None = None,
                source: str | None = None) -> JSONResponse:
        return JSONResponse(surface.history(limit, event_type=event_type, source=source))

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

    # A2A jedzie tym samym routerem, bo to ten sam serwer i ta sama powierzchnia.
    # Karta agenta wymienia wyłącznie umiejętności, które projekt naprawdę ma;
    # zadanie idzie w dwóch krokach — plan, potem wykonanie — tak samo jak dla
    # człowieka w powłoce.
    # Adres w karcie jest parametrem, nie odczytem z żądania: karta ma być taka
    # sama niezależnie od tego, przez jaki proxy przyszło pytanie, bo drugi agent
    # zapisuje ją sobie i wraca później.
    @router.get("/a2a/card")
    def card() -> JSONResponse:
        return JSONResponse(_a2a.agent_card(
            surface, name=f"twinapi:{surface.target}",
            url=(base_url or prefix) + "/a2a"))

    @router.post("/a2a/task")
    def task(body: dict[str, Any] = json_body) -> JSONResponse:
        answer = _a2a.handle_task(surface, body)
        return JSONResponse(answer, status_code=200 if answer["state"] != "failed" else 409)

    return router
