"""Jeden zadeklarowany słownik zmian, wystawiony tak samo w czterech transportach.

Projekt, który pozwala coś zmieniać, prędzej czy później wystawia to na cztery
sposoby: z powłoki, przez REST, przez MCP dla modelu i przez A2A dla drugiego
agenta. Zwykle powstają wtedy cztery listy operacji, które rozjeżdżają się po
pierwszym tygodniu — bo każda warstwa ma własny zestaw czasowników, własną
walidację i własne pojęcie tego, co znaczy „ta sama zmiana".

`twinapi` odwraca zależność: słownik operacji jest **danymi** (paczka standardu
`wellmanifest/*`), a cztery transporty są jego rzutami. Adapter nie może wystawić
operacji, której nie ma w słowniku, bo nie ma skąd jej wziąć.

Wykonanie idzie ścieżką POA (`wellmanifest/poa`): żądanie → plan z hashem →
wykonanie związane tym hashem → pokwitowanie. Dzięki temu „co się stanie" da się
obejrzeć przed zmianą, a „co się stało" jest zapisane niezależnie od tego, przez
który transport przyszło żądanie.
"""
from .journal import Journal, JournalError, evidence_for
from .poa import PlanError, build_plan, build_process, canonical, digest
from .processes import ProcessError, bind, load_processes, routing
from .registry import Handler, Registry
from .ssot import request_schema
from .surface import Surface, SurfaceError
from .vocabulary import Operation, Vocabulary, VocabularyError, load_vocabulary

__all__ = [
    "Handler",
    "Journal",
    "JournalError",
    "Operation",
    "PlanError",
    "ProcessError",
    "Registry",
    "Surface",
    "SurfaceError",
    "Vocabulary",
    "VocabularyError",
    "bind",
    "build_plan",
    "build_process",
    "canonical",
    "digest",
    "evidence_for",
    "load_processes",
    "load_vocabulary",
    "request_schema",
    "routing",
]

__version__ = "0.1.0"
