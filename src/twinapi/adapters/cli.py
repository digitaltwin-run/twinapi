"""Powłoka: ta sama powierzchnia, tylko z argparse przed nią.

Podkomendy nie są wpisane w kod — powstają ze słownika. Dodanie operacji do
standardu i wykonawcy do rejestru wystarcza, żeby pojawiła się w `--help`.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from ..surface import Surface, SurfaceError, receipt_of


def build_parser(surface: Surface, prog: str = "twinapi") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Wypisz słownik operacji i to, które są zaimplementowane.")

    describe = sub.add_parser("describe", help="Deklaracja procesu POA dla operacji.")
    describe.add_argument("operation")

    repairs = sub.add_parser("repairs", help="Czym wolno zamknąć to naruszenie reguły.")
    repairs.add_argument("rule")

    history = sub.add_parser("history", help="Historia zmian projektu i spójność łańcucha.")
    history.add_argument("--limit", type=int, default=15)
    history.add_argument("--event-type")
    history.add_argument("--source")

    for verb, help_text in (("plan", "Pokaż plan, nie zmieniając niczego."),
                            ("run", "Wykonaj operację i wypisz pokwitowanie."),
                            ("apply",
                             "Wykonaj, sprawdź bramkami i opcjonalnie wpisz do projektu.")):
        command = sub.add_parser(verb, help=help_text)
        command.add_argument("operation")
        command.add_argument("--input", default="{}",
                             help="Wejście operacji jako JSON albo @plik.")
        if verb in {"run", "apply"}:
            command.add_argument("--approve", action="store_true",
                                 help="Zgoda na zmianę wymagającą akceptacji.")
        if verb == "run":
            command.add_argument("--plan", help="Plik z planem, którym wykonanie ma być związane.")
        if verb == "apply":
            command.add_argument("--promote", action="store_true",
                                 help="Wpisz kandydata do projektu, gdy wszystkie bramki przejdą.")
    return parser


def _payload(value: str) -> dict[str, Any]:
    if value.startswith("@"):
        with open(value[1:], encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(value)


def main(surface: Surface, argv: list[str] | None = None, prog: str = "twinapi") -> int:
    args = build_parser(surface, prog).parse_args(argv)
    as_json = args.format == "json"

    if args.command == "list":
        document = surface.describe()
        if as_json:
            print(json.dumps(document, ensure_ascii=False, indent=2))
            return 0
        print(f"cel: {document['target']}")
        for pack in document["packs"]:
            print(f"słownik: {pack['id']} {pack['version']}")
        for entry in document["operations"]:
            mark = "✔" if entry["implemented"] else "·"
            approval = " (wymaga zgody)" if entry["requires_approval"] else ""
            print(f"  {mark} {entry['id']:30} {entry['scope']:9} {entry['changes']:10}{approval}")
        return 0

    if args.command == "describe":
        print(json.dumps(surface.process(args.operation), ensure_ascii=False, indent=2))
        return 0

    if args.command == "repairs":
        found = surface.repairs_for(args.rule)
        if as_json:
            print(json.dumps(found, ensure_ascii=False, indent=2))
            return 0
        if not found:
            print(f"żadna operacja nie zamyka {args.rule}")
            return 1
        for entry in found:
            mark = "✔" if entry["implemented"] else "·"
            print(f"  {mark} {entry['operation']}: {entry['why']}")
        return 0

    if args.command == "history":
        document = surface.history(args.limit, event_type=args.event_type, source=args.source)
        if as_json:
            print(json.dumps(document, ensure_ascii=False, indent=2))
            return 0
        if not document["available"]:
            print(document["chain"][0])
            return 1
        for entry in document["entries"]:
            evidence = len(entry.get("evidence") or [])
            print(f"  #{entry['sequence']:>4} {entry['occurredAt'][:19]} "
                  f"{entry['eventType']:28} {entry['outcome']:10} "
                  f"{entry.get('source', ''):10} dowodów={evidence}")
        problems = document["chain"]
        print(f"łańcuch: {'spójny' if not problems else problems[0]}")
        return 1 if problems else 0

    payload = _payload(args.input)
    if args.command == "plan":
        print(json.dumps(surface.plan(args.operation, payload), ensure_ascii=False, indent=2))
        return 0

    if args.command == "apply":
        try:
            result = surface.apply(args.operation, payload, approved=args.approve,
                                   promote=args.promote)
        except SurfaceError as exc:
            print(f"twinapi: {exc}", file=sys.stderr)
            return 1
        if as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        verification = result["verification"]
        print(f"{result['operation']}: {result['receipt']['state']}")
        for key, value in result["output"].items():
            if key == "evidence" and isinstance(value, list):
                print(f"  dowodów: {len(value)}")
                continue
            print(f"  {key}: {value}")
        for name, gate in verification["gates"].items():
            codes = ", ".join(gate.get("codes") or []) or "—"
            print(f"  bramka {name:24} {gate.get('status', '?'):12} {codes}")
        print(f"weryfikacja: {verification['status']}"
              + (f" ({', '.join(verification['blocking'])})" if verification["blocking"] else ""))
        print("wpisane do projektu" if result["promoted"] else "kandydat czeka na decyzję")
        return 0 if verification["status"] == "passed" else 1

    plan = None
    if getattr(args, "plan", None):
        with open(args.plan, encoding="utf-8") as handle:
            plan = json.load(handle)
    try:
        result = surface.execute(args.operation, payload, plan=plan, approved=args.approve)
    except SurfaceError as exc:
        print(f"twinapi: {exc}", file=sys.stderr)
        receipt = receipt_of(exc)
        if receipt is not None and as_json:
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 1
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['operation']}: {result['receipt']['state']}")
        for key, value in result["output"].items():
            # Dowody to lista plików z sumami; w trybie tekstowym liczy się ich
            # liczba, a nie sześć linii skrótów, które i tak trzeba porównywać
            # maszynowo. Pełna lista jest w `--format json`.
            if key == "evidence" and isinstance(value, list):
                print(f"  dowodów: {len(value)}")
                continue
            print(f"  {key}: {value}")
        print(f"pokwitowanie: sha256:{result['receipt']['receipt_hash']}")
    return 0
