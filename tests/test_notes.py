"""Clinical notes tests: rendering, PHI span correctness, safety."""

import json
import re

import pytest
from faker import Faker

from synthgen.notes import (NON_DICTATABLE, NOTE_TYPES, generate_note,
                            generate_notes_dataframe)


ALL_TYPES = [t for t in NOTE_TYPES]


@pytest.mark.parametrize("note_type", ALL_TYPES)
def test_every_type_renders(note_type):
    row = generate_note(0, Faker(), note_type, dictation_ratio=0.0)
    assert len(row["note_text"]) > 120
    assert row["note_type"] == note_type
    assert row["word_count"] > 10


def test_spans_offsets_are_exact():
    row = generate_note(0, Faker(), "progress_note", dictation_ratio=0.0)
    spans = json.loads(row["phi_spans"])
    assert spans, "expected ground-truth spans"
    text = row["note_text"]
    for s in spans[:20]:
        assert text[s["start"]:s["end"]] == s["text"], f"span misaligned: {s}"


def test_span_types_cover_expected_phi():
    row = generate_note(0, Faker(), "progress_note", dictation_ratio=0.0)
    types = {s["type"] for s in json.loads(row["phi_spans"])}
    assert "PATIENT" in types
    assert "MRN" in types
    assert "DOB" in types
    assert "PROVIDER" in types


def test_dictation_has_spoken_punctuation():
    row = generate_note(0, Faker(), "progress_note", dictation_ratio=1.0)
    assert row["note_text"].startswith("BEGIN DICTATION")
    assert row["dictation_flag"] is True
    assert " period " in row["note_text"] or " colon " in row["note_text"]


@pytest.mark.parametrize("note_type", sorted(NON_DICTATABLE))
def test_non_dictatable_never_dictated(note_type):
    for _ in range(5):
        row = generate_note(0, Faker(), note_type, dictation_ratio=1.0)
        assert row["dictation_flag"] is False
        assert not row["note_text"].startswith("BEGIN DICTATION")


def test_all_identifiers_in_safe_ranges():
    df = generate_notes_dataframe(15, Faker())
    for ssn in df["mrn"]:
        assert ssn.startswith("MRN-224")
    for npi in df["author_npi"]:
        assert re.fullmatch(r"9\d{9}", npi)


def test_behavioral_note_has_confidentiality_banner():
    for _ in range(10):
        row = generate_note(0, Faker(), "behavioral_health_note", dictation_ratio=0.0)
        assert "CONFIDENTIAL" in row["note_text"]


def test_portal_message_has_email_phi():
    row = generate_note(0, Faker(), "patient_portal_message", dictation_ratio=0.0)
    types = {s["type"] for s in json.loads(row["phi_spans"])}
    assert "EMAIL" in types or "DOB" in types


def test_determinism_with_frozen_clock(frozen_clock):
    import random
    random.seed(42)
    Faker.seed(42)
    a = generate_notes_dataframe(5, Faker(), "progress_note", 0.3).to_dict()
    random.seed(42)
    Faker.seed(42)
    b = generate_notes_dataframe(5, Faker(), "progress_note", 0.3).to_dict()
    assert a == b
