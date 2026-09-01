"""Słownik jest danymi z paczki standardu, nie stałą w kodzie."""
from __future__ import annotations

import json

import pytest

from twinapi import VocabularyError, load_vocabulary
from twinapi.vocabulary import describe


def test_the_vocabulary_comes_from_the_standard_packs() -> None:
    vocabulary = load_vocabulary("pcb", "sch")

    assert len(vocabulary) >= 20
    assert {pack for pack, _version in vocabulary.packs} == {"wellmanifest/pcb", "wellmanifest/sch"}
    assert {pack for pack, _sha256 in vocabulary.pack_sha256} == {
        "wellmanifest/pcb", "wellmanifest/sch",
    }
    assert all(len(sha256) == 64 for _pack, sha256 in vocabulary.pack_sha256)


def test_an_operation_outside_the_vocabulary_is_an_error_not_an_extension() -> None:
    vocabulary = load_vocabulary("pcb")

    with pytest.raises(VocabularyError, match="nieznana operacja"):
        vocabulary.get("rewrite_everything")


def test_the_same_operation_declared_twice_is_refused(tmp_path) -> None:
    """Dwie paczki nie mogą się spierać o znaczenie jednego czasownika."""
    from twinapi.vocabulary import Operation, Vocabulary

    duplicate = Operation(id="move", scope="pcb", entity="footprint", changes="placement",
                          clears=(), verify=(), reversible=True, why="x", pack="a")
    other = Operation(**{**duplicate.__dict__, "pack": "b"})

    with pytest.raises(VocabularyError, match="w dwóch paczkach"):
        Vocabulary((duplicate, other), ())


def test_changing_the_bill_of_materials_reaches_outside_the_project() -> None:
    """Dokładanie części zmienia świat poza plikiem i skutek to odnotowuje."""
    vocabulary = load_vocabulary("pcb")
    adding = vocabulary.get("add_decoupling_capacitor")
    widening = vocabulary.get("set_track_width")

    assert "external_write" in adding.effects
    assert "external_write" not in widening.effects
    assert adding.requires_approval and not adding.reversible


def test_placement_requires_the_same_explicit_approval_as_copper() -> None:
    vocabulary = load_vocabulary("pcb")

    assert vocabulary.get("move").requires_approval is True
    assert vocabulary.get("optimize_placement_and_routing").requires_approval is True


def test_the_vocabulary_bridges_a_violation_to_its_repairs() -> None:
    vocabulary = load_vocabulary("pcb", "sch")

    repairs = {item.id for item in vocabulary.clearing("RULE_SILK_OVER_PAD")}
    assert repairs == {"trim_silkscreen"}
    assert {item.id for item in vocabulary.clearing("RULE_SCH_COMMON_GRID")} == \
        {"move_symbol", "snap_to_common_grid"}


def test_the_description_is_json_serialisable_for_every_transport() -> None:
    document = describe(load_vocabulary("pcb", "sch"))

    assert json.loads(json.dumps(document, ensure_ascii=False))["schema_id"] == \
        "twinapi.vocabulary/v1"
    assert all(len(pack["sha256"]) == 64 for pack in document["packs"])


def test_a_shallow_install_reports_a_missing_pack_instead_of_crashing(
        monkeypatch, tmp_path) -> None:
    """W kontenerze pakiet leży płytko; brak sąsiada to nie jest awaria ścieżki."""
    import twinapi.vocabulary as module

    monkeypatch.setattr(module.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("WELLMANIFEST_PCB_STANDARD", raising=False)
    monkeypatch.setattr(module, "__file__", str(tmp_path / "vocabulary.py"))

    with pytest.raises(VocabularyError, match="nie znaleziono paczki"):
        module._find_pack("pcb")
