"""Semantic generator tests: mapping, safety, overrides, reconciliation."""

import re


from synthgen.generators import (GENERATOR_REGISTRY, describe_generator,
                                 generate_value, null_rate)
from synthgen.schema import parse_ddl
from synthgen.tables import generate_table


def col(ddl_fragment, name):
    tables = parse_ddl(f"CREATE TABLE t ({ddl_fragment});")
    return next(c for c in tables[0].columns if c.name == name)


class TestSemanticMapping:
    def test_first_last_name(self, fake):
        assert generate_value(col("first_name VARCHAR(50)", "first_name"), fake, [], 0).isalpha()
        assert generate_value(col("last_name VARCHAR(50)", "last_name"), fake, [], 0).isalpha()

    def test_email_safe_domain(self, fake):
        v = generate_value(col("email VARCHAR(100)", "email"), fake, [], 0)
        assert re.search(r"@(example\.(com|org|net)|test\.invalid)$", v)

    def test_ssn_safe_range(self, fake):
        for _ in range(20):
            v = generate_value(col("ssn CHAR(11)", "ssn"), fake, [], 0)
            assert v.startswith("987-65-")

    def test_phone_safe_range(self, fake):
        for _ in range(20):
            v = generate_value(col("phone VARCHAR(20)", "phone"), fake, [], 0)
            assert v.startswith("555-01")

    def test_npi_ten_digits_starting_9(self, fake):
        v = generate_value(col("npi VARCHAR(10)", "npi"), fake, [], 0)
        assert re.fullmatch(r"9\d{9}", v)

    def test_mrn_prefix(self, fake):
        v = generate_value(col("mrn VARCHAR(20)", "mrn"), fake, [], 3)
        assert v.startswith("MRN-224")

    def test_icd10_pool(self, fake):
        v = generate_value(col("icd10_code VARCHAR(10)", "icd10_code"), fake, [], 0)
        assert re.match(r"[A-Z]\d{2}", v)

    def test_note_text_is_narrative(self, fake):
        v = generate_value(col("note_text TEXT", "note_text"), fake, [], 0)
        assert len(v) > 150 and "Patient" in v

    def test_dictation_text_is_raw(self, fake):
        v = generate_value(col("dictation_text TEXT", "dictation_text"), fake, [], 0)
        assert v.startswith("BEGIN DICTATION")

    def test_varchar_truncation(self, fake):
        v = generate_value(col("note_text VARCHAR(120)", "note_text"), fake, [], 0)
        assert len(v) <= 120


class TestOverrides:
    def test_registry_override_wins(self, fake):
        c = col("city VARCHAR(50)", "city")
        key = next(k for k in GENERATOR_REGISTRY if k.startswith("City"))
        v = generate_value(c, fake, [], 0, override=key)
        assert isinstance(v, str) and len(v) > 1

    def test_always_null(self, fake):
        c = col("zip VARCHAR(10)", "zip")
        v = generate_value(c, fake, [], 0, override="Always NULL")
        assert v is None

    def test_pk_not_overridable(self, fake):
        c = col("id INT PRIMARY KEY", "id")
        v = generate_value(c, fake, [], 7, override="Random word")
        assert v == 8  # sequential integer PK preserved


class TestNullRates:
    def test_pk_never_null(self):
        assert null_rate(col("id INT PRIMARY KEY", "id")) == 0.0

    def test_notes_high_null(self):
        assert null_rate(col("notes TEXT", "notes")) == 0.38

    def test_default_low_null(self):
        assert 0 < null_rate(col("middle_name VARCHAR(50)", "middle_name")) > 0


class TestAgeReconciliation:
    def test_age_derived_from_dob(self, fake):
        tables = parse_ddl("CREATE TABLE t (id INT PRIMARY KEY, dob DATE, age INT);")
        df = generate_table(tables[0], 25, fake)
        from datetime import date
        for _, r in df.iterrows():
            if r["dob"] is None:
                continue
            expected = (date.today() - date.fromisoformat(r["dob"])).days // 365
            assert abs(r["age"] - expected) <= 1


def test_describe_generator_smoke(fake):
    for frag, name in [("first_name VARCHAR(50)", "first_name"),
                       ("ssn CHAR(11)", "ssn"),
                       ("note_text TEXT", "note_text")]:
        label = describe_generator(col(frag, name))
        assert isinstance(label, str) and label
