"""Bundle tests: integrity, correlations, locales, dirty mode, determinism."""

import random

import pytest
from faker import Faker

from synthgen.bundle import (LOCALES, apply_dirty_mode, check_integrity,
                             generate_clinical_cohort)


@pytest.mark.parametrize("seed", [1, 42, 99, 123, 2026])
def test_integrity_across_seeds(seed):
    random.seed(seed)
    Faker.seed(seed)
    cohort = generate_clinical_cohort(40, Faker())
    errors = check_integrity(cohort)
    assert errors == [], errors[:5]


def test_medications_correlate_with_diagnoses():
    random.seed(7)
    Faker.seed(7)
    cohort = generate_clinical_cohort(60, Faker())
    dx = cohort["diagnoses"]
    meds = cohort["medications"]
    from synthgen.bundle import CONDITIONS
    cond_meds = {n: set(d["meds"]) for n, d in CONDITIONS.items()}
    linked = 0
    for _, m in meds.iterrows():
        enc_dx = dx[dx["encounter_id"] == m["encounter_id"]]
        if any(m["medication"] in cond_meds.get(d["description"], set())
               for _, d in enc_dx.iterrows()):
            linked += 1
    assert linked == len(meds), f"{len(meds) - linked} medications uncorrelated"


def test_diabetes_labs_biased_high():
    random.seed(42)
    Faker.seed(42)
    cohort = generate_clinical_cohort(120, Faker())
    labs = cohort["lab_results"].merge(
        cohort["diagnoses"][cohort["diagnoses"]["dx_type"] == "Principal"]
        [["encounter_id", "description"]], on="encounter_id")
    dm_hba1c = labs[(labs["description"] == "Type 2 diabetes mellitus")
                    & (labs["loinc_code"] == "4548-4")]["value"]
    assert len(dm_hba1c) > 0
    assert dm_hba1c.mean() > 6.5, "expected diabetic HbA1c values biased high"


@pytest.mark.parametrize("locale", sorted(LOCALES))
def test_locale_packs(locale):
    random.seed(11)
    Faker.seed(11)
    cohort = generate_clinical_cohort(15, Faker(), locale=locale)
    assert check_integrity(cohort) == []
    pats = cohort["patients"]
    if locale != "us":
        assert pats["ssn"].isna().all(), "non-US patients must not have SSNs"


def test_dirty_mode_breaks_formats_not_integrity():
    random.seed(5)
    Faker.seed(5)
    cohort = generate_clinical_cohort(60, Faker())
    assert check_integrity(cohort) == []
    clean_dob_formats = cohort["patients"]["dob"].str.match(r"\d{4}-\d{2}-\d{2}").all()
    assert clean_dob_formats
    apply_dirty_mode(cohort)
    mixed = cohort["patients"]["dob"].str.match(r"\d{4}-\d{2}-\d{2}")
    assert not mixed.all(), "dirty mode should mix date formats"
    # FK integrity survives dirty mode (values untouched, formats only)
    ids = set(cohort["patients"]["patient_id"])
    assert set(cohort["encounters"]["patient_id"]) <= ids


def test_determinism_with_frozen_clock(frozen_clock):
    random.seed(42)
    Faker.seed(42)
    a = generate_clinical_cohort(25, Faker())
    random.seed(42)
    Faker.seed(42)
    b = generate_clinical_cohort(25, Faker())
    import pandas as pd
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name])


def test_all_ten_note_types_present_in_volume():
    random.seed(3)
    Faker.seed(3)
    cohort = generate_clinical_cohort(400, Faker(), note_probability=1.0)
    types = set(cohort["clinical_notes"]["note_type"].str.replace("_dictation", ""))
    assert len(types) >= 8, f"expected broad note-type coverage, got {sorted(types)}"
