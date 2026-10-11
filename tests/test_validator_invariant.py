"""THE invariant: the validator must never flag generator output.

Every generator, format, and locale is run through synthgen.validators.validate
and the standalone validate_synthetic checks. A failure here means either the
generator leaked a real-looking identifier or the validator is too strict —
both are release blockers.
"""

import random

import pytest
from faker import Faker

from synthgen.bundle import LOCALES, apply_dirty_mode, generate_clinical_cohort
from synthgen.formatters import to_csv, to_json, to_sql
from synthgen.notes import NOTE_TYPES, generate_notes_dataframe
from synthgen.schema import parse_ddl
from synthgen.tables import generate_all
from synthgen.validators import validate

EXAMPLE_DDL = """
CREATE TABLE patients (
    patient_id VARCHAR(20) PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    dob DATE, ssn CHAR(11), email VARCHAR(255), phone VARCHAR(20),
    address VARCHAR(255), city VARCHAR(100), state CHAR(2), zip CHAR(10),
    mrn VARCHAR(20), created_at TIMESTAMP
);
CREATE TABLE encounters (
    encounter_id VARCHAR(20) PRIMARY KEY,
    patient_id VARCHAR(20) REFERENCES patients(patient_id),
    note_text TEXT, dictation_text TEXT, note_type VARCHAR(40),
    author VARCHAR(80), transcription_status VARCHAR(20),
    admit_datetime TIMESTAMP NOT NULL
);
"""


def _assert_clean(result, context):
    assert result["critical"] == [], f"{context}: CRITICAL {result['critical'][:3]}"
    assert result["warnings"] == [], f"{context}: WARNING {result['warnings'][:3]}"


@pytest.mark.parametrize("fmt_name", ["csv", "json", "sql"])
def test_schema_generation_clean(fmt_name, fake):
    tables = parse_ddl(EXAMPLE_DDL)
    results = generate_all(tables, 25, fake)
    for name, df in results.items():
        content = {"csv": lambda d: to_csv(d),
                   "json": lambda d: to_json(d),
                   "sql": lambda d: to_sql(d, name)}[fmt_name](df)
        _assert_clean(validate(content), f"schema/{name}/{fmt_name}")


def test_notes_clean_all_types(fake):
    for note_type in NOTE_TYPES:
        df = generate_notes_dataframe(3, fake, note_type)
        _assert_clean(validate(to_csv(df)), f"notes/{note_type}")


@pytest.mark.parametrize("locale", sorted(LOCALES))
def test_bundle_clean_all_locales(locale):
    random.seed(42)
    Faker.seed(42)
    cohort = generate_clinical_cohort(20, Faker(), locale=locale)
    for name, df in cohort.items():
        _assert_clean(validate(to_csv(df)), f"bundle/{locale}/{name}")


def test_bundle_dirty_mode_still_clean():
    # dirty mode degrades FORMATS, never identifier safety
    random.seed(42)
    Faker.seed(42)
    cohort = generate_clinical_cohort(30, Faker())
    apply_dirty_mode(cohort)
    for name, df in cohort.items():
        _assert_clean(validate(to_csv(df)), f"dirty/{name}")


def test_fhir_and_hl7_clean():
    import json as _json
    from synthgen.fhir import cohort_to_bundles
    from synthgen.hl7 import cohort_to_hl7_messages
    random.seed(42)
    Faker.seed(42)
    cohort = generate_clinical_cohort(15, Faker())
    for fname, bundle in cohort_to_bundles(cohort):
        _assert_clean(validate(_json.dumps(bundle)), f"fhir/{fname}")
    for fname, text in cohort_to_hl7_messages(cohort):
        _assert_clean(validate(text), f"hl7/{fname}")
