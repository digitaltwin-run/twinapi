"""Historia zmian: łańcuch haszy, dowody i odporność na zapis równoległy."""
from __future__ import annotations

import json

import pytest

from twinapi import (
    Journal,
    JournalError,
    Registry,
    Surface,
    SurfaceError,
    evidence_for,
    load_vocabulary,
)


def _journal(tmp_path):
    return Journal(tmp_path / "logs" / "eda.jsonl", subject_ref="twinapi:project/test")


def _surface(tmp_path, *, failing: bool = False) -> Surface:
    registry = Registry(load_vocabulary("pcb", "sch"))

    def handler(payload):
        if failing:
            raise ValueError("nie da się")
        return {"candidate": "rev-1", "evidence": [{"path": "pcb/x.kicad_pcb", "sha256": "a" * 64}]}

    registry.register("trim_silkscreen", handler)
    return Surface(registry, target="panel9", journal=_journal(tmp_path))


def test_an_execution_leaves_a_verifiable_trace(tmp_path) -> None:
    surface = _surface(tmp_path)

    surface.execute("trim_silkscreen", {})

    entries = [json.loads(line) for line in surface.journal.path.read_text().splitlines()]
    assert [entry["eventType"] for entry in entries] == \
        ["eda.change_planned", "eda.candidate_created"]
    assert surface.journal.verify() == []
    assert entries[-1]["evidence"][0]["path"] == "pcb/x.kicad_pcb"
    assert entries[-1]["receiptRef"].startswith("receipt://")
    assert entries[-1]["subjectState"] == "created"


def test_a_failure_is_recorded_too_with_its_code(tmp_path) -> None:
    """Nieudana zmiana znika bez śladu tylko wtedy, gdy nikt jej nie zapisze."""
    surface = _surface(tmp_path, failing=True)

    with pytest.raises(SurfaceError):
        surface.execute("trim_silkscreen", {})

    entries = [json.loads(line) for line in surface.journal.path.read_text().splitlines()]
    assert entries[-1]["eventType"] == "eda.change_plan_failed"
    assert entries[-1]["outcome"] == "FAILED"
    assert entries[-1]["code"] == "TWINAPI-HANDLER-FAILED"
    assert entries[-1]["severity"] == "ERROR"


def test_the_chain_notices_an_edited_entry(tmp_path) -> None:
    surface = _surface(tmp_path)
    surface.execute("trim_silkscreen", {})
    surface.execute("trim_silkscreen", {})

    lines = surface.journal.path.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["outcome"] = "ACCEPTED"
    lines[1] = json.dumps(tampered, ensure_ascii=False, sort_keys=True)
    surface.journal.path.write_text("\n".join(lines) + "\n")

    problems = surface.journal.verify()
    assert any("hasz nie odpowiada" in problem for problem in problems)


def test_appending_continues_a_stream_someone_else_started(tmp_path) -> None:
    """Do strumienia pisze też backend — dopisujemy, a nie zaczynamy od nowa."""
    journal = _journal(tmp_path)
    first = journal.append(event_type="eda.pcb_analyzed", outcome="OBSERVED",
                           correlation_id="abc", input_hash="0" * 64)
    second = journal.append(event_type="eda.candidate_created", outcome="SUCCEEDED",
                            correlation_id="abc", input_hash="1" * 64)

    assert first["sequence"] == 1 and second["sequence"] == 2
    assert second["previousHash"] == first["eventHash"]
    assert journal.verify() == []


def test_the_first_entry_anchors_on_the_zero_hash_like_the_stream_it_joins(tmp_path) -> None:
    """Świeży strumień ma wyglądać jak ten, który już istnieje."""
    from twinapi.journal import GENESIS

    journal = _journal(tmp_path)
    first = journal.append(event_type="eda.pcb_analyzed", outcome="OBSERVED",
                           correlation_id="abc", input_hash="0" * 64)

    assert first["previousHash"] == GENESIS
    assert journal.verify() == []


def test_a_severity_outside_the_vocabulary_is_refused(tmp_path) -> None:
    with pytest.raises(JournalError, match="waga"):
        _journal(tmp_path).append(event_type="x", outcome="OBSERVED", severity="LOUD",
                                  correlation_id="abc", input_hash="0" * 64)


def test_evidence_carries_the_digest_not_only_the_name(tmp_path) -> None:
    """Wpis z samą nazwą mówi, że coś się stało; suma pozwala to sprawdzić."""
    target = tmp_path / "pcb" / "panel9.kicad_pcb"
    target.parent.mkdir(parents=True)
    target.write_text("(kicad_pcb)\n", encoding="utf-8")

    found = evidence_for([target, tmp_path / "nie-ma.kicad_pcb"], root=tmp_path)

    assert found == [{"path": "pcb/panel9.kicad_pcb", "sha256":
                      __import__("hashlib").sha256(target.read_bytes()).hexdigest()}]


def test_a_broken_journal_does_not_break_the_change(tmp_path) -> None:
    """Historia jest świadkiem, nie warunkiem: zapis do niej nie może cofnąć zmiany."""
    surface = _surface(tmp_path)
    surface.journal.path = tmp_path / "nie-ma" / "katalogu" / "\x00zły.jsonl"

    result = surface.execute("trim_silkscreen", {})

    assert result["receipt"]["state"] == "succeeded"


def test_a_state_that_is_not_a_state_name_is_refused(tmp_path) -> None:
    """`subjectState` to nazwa stanu, nie identyfikator rewizji.

    Pierwsza wersja wpisywała tam `20260828T065637Z-pcb-cf89879bb809` i napisała
    29 wpisów łamiących kontrakt, zanim ktokolwiek porównał je ze schematem.
    """
    journal = _journal(tmp_path)

    with pytest.raises(JournalError, match="subjectState"):
        journal.append(event_type="eda.candidate_created", outcome="SUCCEEDED",
                       correlation_id="abc", input_hash="0" * 64,
                       subject_state="20260828T065637Z-pcb-cf89879bb809")


def test_a_receipt_reference_must_use_its_own_scheme(tmp_path) -> None:
    journal = _journal(tmp_path)

    with pytest.raises(JournalError, match="receiptRef"):
        journal.append(event_type="eda.candidate_created", outcome="SUCCEEDED",
                       correlation_id="abc", input_hash="0" * 64,
                       receipt_ref="sha256:" + "a" * 64)


def test_a_python_exception_name_is_not_a_diagnostic_code(tmp_path) -> None:
    """Kod diagnostyczny to WIELKIE-LITERY z myślnikiem, nie `ValueError`."""
    journal = _journal(tmp_path)

    with pytest.raises(JournalError, match="code"):
        journal.append(event_type="eda.change_plan_failed", outcome="FAILED",
                       severity="ERROR", correlation_id="abc", input_hash="0" * 64,
                       code="ValueError")


def test_a_hash_that_is_not_a_hash_is_refused(tmp_path) -> None:
    journal = _journal(tmp_path)

    with pytest.raises(JournalError, match="inputHash"):
        journal.append(event_type="eda.pcb_analyzed", outcome="OBSERVED",
                       correlation_id="abc", input_hash="nie-hasz")
