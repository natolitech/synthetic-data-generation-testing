#!/usr/bin/env python3
"""
Schema-Driven Synthetic Data Generator
=======================================
Paste or upload a SQL DDL schema and generate realistic synthetic data.
All data is entirely fictional — zero real PII/PHI.

Run:
    streamlit run schema_app.py
"""

import io
import json
import random
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from faker import Faker

try:
    from clinical_notes import generate_note as _note_gen
except ImportError:  # pragma: no cover - module lives next to this script
    _note_gen = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAFE_SSN_PREFIX = "987-65"
SAFE_EMAIL_DOMAINS = ["example.com", "example.org", "test.invalid"]
SAFE_PHONE_PREFIX = "555-01"

EDGE_CASE_NAMES = [
    ("María", "García-López"),
    ("James", "O'Brien"),
    ("Sœren", "Müller-Björk"),
    ("李", "王小明"),
    ("Александр", "Čapek"),
    ("J", "de la Cruz"),
    ("Mohammed bin Rashid", "Al-Maktoum"),
    ("Mary Anne Elizabeth", "van der Berg-Smithington III"),
]

RACE_OPTIONS = [
    ("White", 0.58), ("Black or African American", 0.13),
    ("Asian", 0.12), ("Two or More Races", 0.08),
    ("American Indian or Alaska Native", 0.02),
    ("Native Hawaiian or Other Pacific Islander", 0.01),
    ("Unknown", 0.06),
]

ETHNICITY_OPTIONS = [
    ("Not Hispanic or Latino", 0.80),
    ("Hispanic or Latino", 0.18),
    ("Unknown", 0.02),
]

LANGUAGES = [
    ("English", 0.70), ("Spanish", 0.15), ("Mandarin", 0.05),
    ("Arabic", 0.03), ("Tagalog", 0.02), ("Korean", 0.02),
    ("Hindi", 0.01), ("French", 0.01), ("Vietnamese", 0.01),
]

ICD10_POOL = [
    "E11.9", "E11.65", "I10", "I11.9", "I25.10", "I48.91",
    "J06.9", "J18.9", "F32.1", "F41.1", "M54.5", "M17.11",
]

CPT_POOL = ["99213", "99214", "99215", "99223", "99232", "99283", "99285", "36415", "71046", "93000"]

LOINC_POOL = ["2951-2", "2823-3", "2075-0", "3094-0", "2160-0", "2345-7", "6690-2", "718-7", "4548-4"]

MEDICATIONS = [
    "metformin 500mg", "lisinopril 10mg", "atorvastatin 40mg", "sertraline 50mg",
    "amoxicillin 500mg", "amlodipine 5mg", "omeprazole 20mg", "levothyroxine 50mcg",
    "aspirin 81mg", "gabapentin 300mg", "fluoxetine 20mg", "losartan 50mg",
]

DEPARTMENTS = [
    "Engineering", "Marketing", "Sales", "HR", "Finance",
    "Legal", "Operations", "IT", "Research", "Customer Support",
]

ENCOUNTER_TYPES = ["Outpatient", "Inpatient", "ED", "Telehealth", "Observation", "Urgent Care"]

EXAMPLE_DDL = """\
CREATE TABLE patients (
    patient_id    VARCHAR(20)  PRIMARY KEY,
    first_name    VARCHAR(100) NOT NULL,
    last_name     VARCHAR(100) NOT NULL,
    dob           DATE,
    gender        VARCHAR(20),
    ssn           CHAR(11),
    email         VARCHAR(255),
    phone         VARCHAR(20),
    address       VARCHAR(255),
    city          VARCHAR(100),
    state         CHAR(2),
    zip           CHAR(10),
    mrn           VARCHAR(20),
    created_at    TIMESTAMP,
    deceased_flag BOOLEAN
);

CREATE TABLE encounters (
    encounter_id       VARCHAR(20) PRIMARY KEY,
    patient_id         VARCHAR(20) REFERENCES patients(patient_id),
    encounter_type     VARCHAR(50) NOT NULL,
    admit_datetime     TIMESTAMP   NOT NULL,
    discharge_datetime TIMESTAMP,
    department         VARCHAR(100),
    attending_npi      VARCHAR(10)
);"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def weighted_choice(options):
    values, weights = zip(*options)
    return random.choices(values, weights=weights, k=1)[0]


def safe_email(fake: Faker) -> str:
    first = re.sub(r"[^a-zA-Z0-9]", "", fake.first_name().lower())
    last = re.sub(r"[^a-zA-Z0-9]", "", fake.last_name().lower())
    return f"{first}.{last}@{random.choice(SAFE_EMAIL_DOMAINS)}"


def safe_ssn() -> str:
    return f"{SAFE_SSN_PREFIX}-{random.randint(0, 9999):04d}"


def safe_phone() -> str:
    return f"{SAFE_PHONE_PREFIX}{random.randint(0, 99):02d}"


# ---------------------------------------------------------------------------
# Schema Parsing
# ---------------------------------------------------------------------------

@dataclass
class ColumnDef:
    name: str
    sql_type: str
    base_type: str
    nullable: bool = True
    is_pk: bool = False
    fk_table: Optional[str] = None
    fk_col: Optional[str] = None


@dataclass
class TableDef:
    name: str
    columns: List[ColumnDef] = field(default_factory=list)


def _split_top_level(text: str) -> List[str]:
    """Split by comma, ignoring commas inside parentheses."""
    depth, parts, current = 0, [], []
    for ch in text:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return [p for p in parts if p.strip()]


def _parse_column_token(token: str) -> Optional[ColumnDef]:
    token = token.strip()
    if not token:
        return None
    upper = token.upper().lstrip()
    if re.match(r"^(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|INDEX|KEY\b|CONSTRAINT|CHECK\s*\(|FULLTEXT|SPATIAL)", upper):
        return None

    name_match = re.match(r'^[`"\[]?([\w]+)[`"\]]?\s+', token)
    if not name_match:
        return None
    name = name_match.group(1)
    rest = token[name_match.end():]

    type_match = re.match(r"([\w]+(?:\s*\([^)]*\))?(?:\s+(?:UNSIGNED|ZEROFILL))*)", rest, re.IGNORECASE)
    if not type_match:
        return None
    sql_type = type_match.group(1).strip()
    base_type = sql_type.split("(")[0].strip().lower()
    rest_upper = rest[type_match.end():].upper()

    is_pk = bool(re.search(r"\bPRIMARY\s+KEY\b", rest_upper))
    nullable = "NOT NULL" not in rest_upper
    if is_pk:
        nullable = False

    fk_table = fk_col = None
    fk_match = re.search(r"REFERENCES\s+[`\"]?([\w]+)[`\"]?\s*\(\s*[`\"]?([\w]+)[`\"]?\s*\)", token, re.IGNORECASE)
    if fk_match:
        fk_table, fk_col = fk_match.group(1), fk_match.group(2)

    return ColumnDef(name=name, sql_type=sql_type, base_type=base_type,
                     nullable=nullable, is_pk=is_pk, fk_table=fk_table, fk_col=fk_col)


def parse_ddl(text: str) -> List[TableDef]:
    text = re.sub(r"--[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    tables = []
    create_re = re.compile(
        r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"(?:[`\"\[]?[\w]+[`\"\]]?\s*\.\s*)?[`\"\[]?([\w]+)[`\"\]]?\s*\(",
        re.IGNORECASE,
    )
    for m in create_re.finditer(text):
        table_name = m.group(1)
        start, depth, i = m.end(), 1, m.end()
        while i < len(text) and depth > 0:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        body = text[start:i - 1]

        columns, pk_cols = [], set()
        for token in _split_top_level(body):
            stripped_upper = token.strip().upper()
            pk_match = re.match(r"PRIMARY\s+KEY\s*\(([^)]+)\)", stripped_upper)
            if pk_match:
                for c in pk_match.group(1).split(","):
                    pk_cols.add(re.sub(r"[`\"\[\]]", "", c.strip()).lower())
                continue
            col = _parse_column_token(token)
            if col:
                columns.append(col)

        for col in columns:
            if col.name.lower() in pk_cols:
                col.is_pk = True
                col.nullable = False

        if columns:
            tables.append(TableDef(name=table_name, columns=columns))

    return tables


# ---------------------------------------------------------------------------
# Generator registry (in-app override support)
# ---------------------------------------------------------------------------

def _gen_first(col, fake, i): return fake.first_name()
def _gen_last(col, fake, i): return fake.last_name()
def _gen_full(col, fake, i): return fake.name()
def _gen_email(col, fake, i): return safe_email(fake)
def _gen_phone(col, fake, i): return safe_phone()
def _gen_ssn(col, fake, i): return safe_ssn()
def _gen_mrn(col, fake, i): return f"MRN-{2240000 + i}"
def _gen_npi(col, fake, i): return f"9{random.randint(100000000, 999999999)}"
def _gen_dob(col, fake, i):
    age = random.randint(0, 90)
    return (date.today() - timedelta(days=age * 365 + random.randint(0, 364))).isoformat()
def _gen_gender(col, fake, i):
    return random.choices(["Female", "Male", "Non-binary", "Unknown"],
                          weights=[0.49, 0.49, 0.015, 0.005])[0]
def _gen_address(col, fake, i): return fake.street_address()
def _gen_city(col, fake, i): return fake.city()
def _gen_state(col, fake, i): return fake.state_abbr()
def _gen_zip(col, fake, i): return fake.zipcode()
def _gen_recent_ts(col, fake, i):
    return (datetime.now() - timedelta(days=random.randint(1, 730))).isoformat(timespec="minutes")
def _gen_past_date(col, fake, i):
    return (date.today() - timedelta(days=random.randint(1, 3650))).isoformat()
def _gen_salary(col, fake, i): return random.randint(35000, 250000)
def _gen_amount(col, fake, i): return round(random.uniform(10.0, 5000.0), 2)
def _gen_icd10(col, fake, i): return random.choice(ICD10_POOL)
def _gen_cpt(col, fake, i): return random.choice(CPT_POOL)
def _gen_loinc(col, fake, i): return random.choice(LOINC_POOL)
def _gen_med(col, fake, i): return random.choice(MEDICATIONS)
def _gen_dept(col, fake, i): return random.choice(DEPARTMENTS)
def _gen_enc_type(col, fake, i):
    return random.choices(ENCOUNTER_TYPES, weights=[0.60, 0.10, 0.15, 0.10, 0.04, 0.01])[0]
def _gen_note(col, fake, i):
    if _note_gen is not None:
        return _truncate_to_col(_note_gen(i, fake, "mix", dictation_ratio=0.0)["note_text"], col)
    return _truncate_to_col("Patient seen and evaluated. Condition stable, continue current plan.", col)
def _gen_dictation(col, fake, i):
    if _note_gen is not None:
        return _truncate_to_col(_note_gen(i, fake, "mix", dictation_ratio=1.0)["note_text"], col)
    return _truncate_to_col("Dictation received; transcription pending review.", col)
def _gen_uuid(col, fake, i): return str(uuid.uuid4())
def _gen_int(col, fake, i): return random.randint(1, 10000)
def _gen_float(col, fake, i): return round(random.uniform(0.0, 1000.0), 2)
def _gen_word(col, fake, i): return fake.word()
def _gen_sentence(col, fake, i): return fake.sentence()
def _gen_null(col, fake, i): return None


GENERATOR_REGISTRY = {
    "First name (Faker)": _gen_first,
    "Last name (Faker)": _gen_last,
    "Full name (Faker)": _gen_full,
    "Email — safe @example.com": _gen_email,
    "Phone — safe 555-01xx": _gen_phone,
    "SSN — safe 987-65-xxxx": _gen_ssn,
    "MRN — MRN-224xxxx": _gen_mrn,
    "NPI — 9xxxxxxxxx": _gen_npi,
    "Date of birth": _gen_dob,
    "Gender (weighted)": _gen_gender,
    "Street address": _gen_address,
    "City": _gen_city,
    "State (abbr)": _gen_state,
    "ZIP code": _gen_zip,
    "Recent timestamp": _gen_recent_ts,
    "Past date": _gen_past_date,
    "Salary (35k–250k)": _gen_salary,
    "Amount (10–5000)": _gen_amount,
    "ICD-10 code": _gen_icd10,
    "CPT code": _gen_cpt,
    "LOINC code": _gen_loinc,
    "Medication": _gen_med,
    "Department": _gen_dept,
    "Encounter type (weighted)": _gen_enc_type,
    "Clinical note text": _gen_note,
    "Dictation transcript": _gen_dictation,
    "UUID4": _gen_uuid,
    "Random integer": _gen_int,
    "Random float": _gen_float,
    "Random word": _gen_word,
    "Sentence": _gen_sentence,
    "Always NULL": _gen_null,
}

AUTO = "Auto (inferred)"


# ---------------------------------------------------------------------------
# Semantic Generator
# ---------------------------------------------------------------------------

def _null_rate(col: ColumnDef) -> float:
    if col.is_pk or not col.nullable:
        return 0.0
    name = col.name.lower()
    if re.search(r"deleted|archived|terminated|end_date|expir|middle|line2|line_2|fax|suffix|notes|description|comments|reason", name):
        return 0.38
    if re.search(r"phone|mobile|cell|secondary|optional|alt_", name):
        return 0.12
    return 0.07


def _truncate_to_col(text: str, col: ColumnDef) -> str:
    """Truncate narrative text to the column's declared length (if any)."""
    m = re.search(r"\((\d+)\)", col.sql_type)
    if m and col.base_type in ("varchar", "char", "character", "nvarchar", "nchar"):
        limit = int(m.group(1))
        if len(text) > limit:
            cut = text[:limit - 1]
            return cut.rsplit(" ", 1)[0] + "…"
    return text


_NOTE_TYPE_POOL = ["progress_note", "history_physical", "discharge_summary",
                   "ed_note", "telehealth_note", "procedure_note"]
_NARRATIVE_RE = re.compile(
    r"note(_text|_body|s)?$|progress.?note|discharge.?summar|soap|"
    r"h.?and.?p$|^hpi$|chief.?complaint|narrative|clinical.?text|impression$"
)
_DICTATION_RE = re.compile(r"dictation|transcript")


def _generate_value(col: ColumnDef, fake: Faker, fk_pool: List, row_idx: int,
                    override: str = None) -> Any:
    name = col.name.lower()
    bt = col.base_type

    # manual override from the UI (PK/FK stay locked to preserve integrity)
    if override and override in GENERATOR_REGISTRY and not col.is_pk and not col.fk_table:
        return GENERATOR_REGISTRY[override](col, fake, row_idx)

    if bt in ("uuid", "uniqueidentifier"):
        return str(uuid.uuid4())

    if col.is_pk:
        if bt in ("int", "integer", "bigint", "serial", "bigserial", "smallint", "tinyint"):
            return row_idx + 1
        for kw, prefix in [("patient", "SYN"), ("student", "SYN"), ("employee", "EMP"),
                            ("user", "USR"), ("subject", "SUBJ"), ("claim", "CLM"), ("encounter", "ENC"),
                            ("note", "NOTE")]:
            if kw in name:
                return f"{prefix}-{row_idx+1:06d}"
        return f"ID-{row_idx+1:06d}"

    if col.fk_table and fk_pool:
        return random.choice(fk_pool)

    # Clinical note metadata & narrative (before generic name rules so
    # note_text columns don't fall through to fake.word())
    if re.search(r"^note.?type$|note.?category", name):
        return random.choice(_NOTE_TYPE_POOL)
    if re.search(r"transcription.?status|note.?status", name):  # before _DICTATION_RE
        return random.choices(["Signed", "Transcribed", "Draft", "Pending review"],
                              weights=[0.6, 0.2, 0.1, 0.1])[0]
    if re.search(r"^author$|dictated.?by|signed.?by|transcriptionist", name):
        return f"Dr. {fake.first_name()} {fake.last_name()}, MD"
    if _DICTATION_RE.search(name):
        if _note_gen is not None:
            note = _note_gen(row_idx, fake, "mix", dictation_ratio=1.0)["note_text"]
            return _truncate_to_col(note, col)
        return _truncate_to_col(
            "Dictation received via telephone line. Patient reports ongoing symptoms; "
            "transcription pending review by attending provider.", col)
    if _NARRATIVE_RE.search(name):
        if _note_gen is not None:
            note = _note_gen(row_idx, fake, "mix", dictation_ratio=0.0)["note_text"]
            return _truncate_to_col(note, col)
        return _truncate_to_col(
            "Patient seen and evaluated. Condition stable, continue current plan. "
            "Follow up as scheduled if symptoms change.", col)

    # Names
    if re.search(r"first.?name|fname|given.?name|forename", name):
        return fake.first_name()
    if re.search(r"last.?name|lname|surname|family.?name", name):
        return fake.last_name()
    if re.search(r"middle.?name|middle.?initial", name):
        return fake.first_name()
    if re.search(r"full.?name|display.?name|patient.?name|provider.?name|person.?name", name):
        return fake.name()
    if name == "name" or (name.endswith("_name") and not re.search(r"file|table|field|column|domain|host|type|class", name)):
        return fake.name()

    # Contact
    if re.search(r"^email$|email.?address", name):
        return safe_email(fake)
    if re.search(r"^phone$|phone.?number|^mobile$|^cell$|telephone|^tel$", name):
        return safe_phone()
    if re.search(r"^fax$|fax.?number", name):
        return safe_phone()

    # Identity documents
    if re.search(r"^ssn$|social.?security", name):
        return safe_ssn()
    if re.search(r"^mrn$|medical.?record", name):
        return f"MRN-{2240000 + row_idx}"
    if re.search(r"npi", name):
        return f"9{random.randint(100000000, 999999999)}"

    # Location
    if re.search(r"address.?line.?1|street.?address|^street$|^address1$|^addr1$", name):
        return fake.street_address()
    if re.search(r"address.?line.?2|^address2$|^addr2$|^apt$|^suite$", name):
        return random.choice([f"Apt {random.randint(1, 999)}", f"Suite {random.randint(100, 999)}", None, None, None])
    if re.search(r"^address$|^addr$|mailing.?address|billing.?address", name):
        return fake.street_address()
    if re.search(r"^city$|city.?name", name):
        return fake.city()
    if re.search(r"^state$|state.?abbr|state.?code", name):
        return fake.state_abbr()
    if re.search(r"^zip$|zip.?code|^zipcode$|postal.?code", name):
        return fake.zipcode()
    if re.search(r"country.?code", name):
        return random.choice(["US", "US", "US", "CA", "GB", "MX", "AU"])
    if re.search(r"^country$", name):
        return random.choice(["United States", "United States", "Canada", "United Kingdom", "Mexico"])
    if re.search(r"^latitude$|^lat$", name):
        return round(random.uniform(25.0, 49.0), 6)
    if re.search(r"^longitude$|^lon$|^lng$", name):
        return round(random.uniform(-124.0, -67.0), 6)

    # Demographics
    if re.search(r"^dob$|birth.?date|date.?of.?birth|birthdate|birthday", name):
        age = random.randint(0, 90)
        return (date.today() - timedelta(days=age * 365 + random.randint(0, 364))).isoformat()
    if re.search(r"^age$", name) and bt in ("int", "integer", "smallint", "tinyint"):
        return random.randint(0, 99)
    if re.search(r"^gender$|^sex$", name):
        return random.choices(["Female", "Male", "Non-binary", "Unknown"], weights=[0.49, 0.49, 0.015, 0.005])[0]
    if re.search(r"^race$", name):
        return weighted_choice(RACE_OPTIONS)
    if re.search(r"^ethnicity$", name):
        return weighted_choice(ETHNICITY_OPTIONS)
    if re.search(r"^language$|preferred.?language|^lang$", name):
        return weighted_choice(LANGUAGES)

    # Dates / Timestamps
    if re.search(r"created.?at|date.?created|create.?time|created.?date|inserted.?at", name):
        return (datetime.now() - timedelta(days=random.randint(1, 730), hours=random.randint(0, 23))).isoformat(timespec="minutes")
    if re.search(r"updated.?at|modified.?at|last.?modified|updated.?date", name):
        return (datetime.now() - timedelta(days=random.randint(0, 365))).isoformat(timespec="minutes")
    if re.search(r"deleted.?at|archived.?at|deactivated.?at", name):
        return None
    if re.search(r"hire.?date|start.?date|employment.?date", name):
        return (date.today() - timedelta(days=random.randint(30, 10950))).isoformat()
    if re.search(r"termination.?date|term.?date|end.?date|expir", name):
        return (date.today() + timedelta(days=random.randint(-365, 365))).isoformat() if random.random() > 0.6 else None
    if re.search(r"admit.?date|admit.?time|admission.?date|admit.?datetime", name):
        return (datetime.now() - timedelta(days=random.randint(1, 365), hours=random.randint(0, 23))).isoformat(timespec="minutes")
    if re.search(r"discharge.?date|discharge.?time|discharge.?datetime", name):
        return (datetime.now() - timedelta(days=random.randint(0, 360))).isoformat(timespec="minutes")
    if re.search(r"last.?logon|last.?login|last.?access|last.?seen", name):
        return (datetime.now() - timedelta(days=random.randint(0, 90))).isoformat(timespec="minutes")
    if re.search(r"password.?last.?set|pwd.?changed", name):
        return (date.today() - timedelta(days=random.randint(0, 180))).isoformat()

    # Financial
    if re.search(r"^salary$|^wage$|compensation|annual.?pay", name):
        return random.randint(35000, 250000)
    if re.search(r"hourly.?rate|^hourly$", name):
        return round(random.uniform(12.0, 120.0), 2)
    if re.search(r"^amount$|^charge$|^price$|^cost$|^fee$|^balance$|^total$|^payment$", name):
        return round(random.uniform(10.0, 5000.0), 2)
    if re.search(r"credit.?card|card.?number|cc.?number", name):
        return "4242424242424242"
    if re.search(r"routing.?number", name):
        return f"0{random.randint(10000000, 99999999)}"

    # Clinical
    if re.search(r"icd.?10|icd10|diagnosis.?code|dx.?code|diag.?code", name):
        return random.choice(ICD10_POOL)
    if re.search(r"^cpt$|cpt.?code", name):
        return random.choice(CPT_POOL)
    if re.search(r"^loinc$|loinc.?code", name):
        return random.choice(LOINC_POOL)
    if re.search(r"medication|drug.?name|med.?name", name):
        return random.choice(MEDICATIONS)

    # Clinical
    if re.search(r"encounter.?type", name):
        return random.choices(ENCOUNTER_TYPES, weights=[0.60, 0.10, 0.15, 0.10, 0.04, 0.01])[0]

    # HR
    if re.search(r"^department$|^dept$", name):
        return random.choice(DEPARTMENTS)
    if re.search(r"job.?title|^position$", name) and bt in ("varchar", "text", "char", "nvarchar", "string"):
        return fake.job()
    if re.search(r"flsa.?status", name):
        return random.choice(["Exempt", "Non-Exempt"])

    # IAM
    if re.search(r"^username$|user.?name|login.?name|^login$", name):
        fn = re.sub(r"[^a-z]", "", fake.first_name().lower())
        ln = re.sub(r"[^a-z]", "", fake.last_name().lower())
        return f"{fn[0]}{ln}"
    if re.search(r"password.?hash|^password$|^passwd$|^pwd$", name):
        return fake.sha256()
    if re.search(r"api.?key|^token$|access.?token|auth.?token", name):
        return fake.sha256()
    if re.search(r"^upn$|user.?principal.?name", name):
        fn = re.sub(r"[^a-z]", "", fake.first_name().lower())
        ln = re.sub(r"[^a-z]", "", fake.last_name().lower())
        return f"{fn[0]}{ln}@example.edu"

    # Text / Misc
    if re.search(r"^description$|^desc$|^notes$|^note$|^comments$|^comment$|^summary$|^details$|^reason$|^remarks$", name):
        return fake.sentence()
    if re.search(r"^url$|^website$|^homepage$|^link$", name):
        return f"https://example.com/{fake.slug()}"
    if re.search(r"ip.?address|ip.?addr|^ip$", name):
        return f"192.0.2.{random.randint(1, 254)}"
    if re.search(r"^uuid$|^guid$", name):
        return str(uuid.uuid4())

    # Boolean flags
    if bt in ("bool", "boolean"):
        if re.search(r"active|enabled|is_active", name):
            return random.random() < 0.85
        if re.search(r"deceased|terminated|deleted|archived", name):
            return random.random() < 0.05
        return random.random() < 0.15
    if bt == "bit":
        return 1 if random.random() < 0.5 else 0

    # Status
    if re.search(r"^status$", name):
        return random.choice(["Active", "Inactive", "Pending"])

    # Type-based fallbacks
    if bt in ("int", "integer", "bigint", "smallint", "tinyint", "int2", "int4", "int8", "serial", "bigserial"):
        if re.search(r"count|qty|quantity|rank|score|priority|seq", name):
            return random.randint(0, 100)
        return random.randint(1, 10000)
    if bt in ("float", "double", "real", "float4", "float8", "double_precision"):
        return round(random.uniform(0.0, 100.0), 4)
    if bt in ("decimal", "numeric", "money", "smallmoney"):
        return round(random.uniform(0.0, 1000.0), 2)
    if bt in ("date",):
        return (date.today() - timedelta(days=random.randint(0, 1825))).isoformat()
    if bt in ("datetime", "timestamp", "datetime2", "datetimeoffset", "timestamptz",
              "timestamp_without_time_zone", "timestamp_with_time_zone"):
        return (datetime.now() - timedelta(days=random.randint(0, 365), hours=random.randint(0, 23))).isoformat(timespec="minutes")
    if bt in ("time", "timetz"):
        return f"{random.randint(0, 23):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"
    if bt in ("json", "jsonb"):
        return json.dumps({"synthetic": True, "value": fake.word()})
    if bt in ("text", "varchar", "nvarchar", "char", "nchar", "string", "clob",
              "mediumtext", "longtext", "tinytext"):
        if name.endswith("_id") or name.endswith("_fk"):
            return f"SYN-{random.randint(1, 100):06d}"
        if re.search(r"code|type|category|kind|class", name):
            return fake.word().upper()[:10]
        return fake.word()

    return fake.word()


def _describe_generator(col: ColumnDef) -> str:
    """Human-readable label for what will be generated."""
    name = col.name.lower()
    bt = col.base_type

    if bt in ("uuid", "uniqueidentifier"):
        return "uuid4()"
    if col.is_pk:
        if bt in ("int", "integer", "bigint", "serial", "bigserial"):
            return "sequential integer"
        return "sequential ID (SYN-000001 ...)"
    if col.fk_table:
        return f"FK pool → {col.fk_table}"
    if re.search(r"first.?name|fname", name):
        return "fake.first_name()"
    if re.search(r"last.?name|lname|surname", name):
        return "fake.last_name()"
    if re.search(r"middle.?name", name):
        return "fake.first_name() [~38% NULL]"
    if name == "name" or re.search(r"full.?name|display.?name", name):
        return "fake.name()"
    if re.search(r"email", name):
        return "safe_email() [@example.com]"
    if re.search(r"phone|mobile|telephone", name):
        return "safe_phone() [555-01xx]"
    if re.search(r"^fax$|fax.?number", name):
        return "safe_phone() [~38% NULL]"
    if re.search(r"ssn|social.?security", name):
        return "safe_ssn() [987-65-xxxx]"
    if re.search(r"^mrn$|medical.?record", name):
        return "MRN-224xxxx"
    if re.search(r"dob|birth.?date|date.?of.?birth", name):
        return "random date (age distribution)"
    if re.search(r"^gender$|^sex$", name):
        return "Female/Male/Non-binary (weighted)"
    if re.search(r"^race$", name):
        return "race (US Census weights)"
    if re.search(r"^ethnicity$", name):
        return "ethnicity (US Census weights)"
    if re.search(r"^city$", name):
        return "fake.city()"
    if re.search(r"^state$|state.?abbr|state.?code", name):
        return "fake.state_abbr()"
    if re.search(r"zip|postal", name):
        return "fake.zipcode()"
    if re.search(r"salary|wage|compensation", name):
        return "randint(35000, 250000)"
    if re.search(r"^amount$|^charge$|^price$|^cost$|^fee$", name):
        return "uniform(10, 5000)"
    if re.search(r"^department$|^dept$", name):
        return "department name (pool)"
    if re.search(r"job.?title|^position$", name):
        return "fake.job()"
    if re.search(r"^username$|user.?name", name):
        return "flastname pattern"
    if re.search(r"description|notes|comments|summary", name):
        return "fake.sentence() [~20% NULL]"
    if re.search(r"^status$", name):
        return "Active/Inactive/Pending"
    if re.search(r"created.?at|updated.?at", name):
        return "recent datetime"
    if re.search(r"hire.?date|start.?date", name):
        return "random past date"
    if re.search(r"end.?date|termination", name):
        return "random date [~60% NULL]"
    if bt in ("int", "integer", "bigint", "smallint", "serial"):
        return "randint(1, 10000)"
    if bt in ("decimal", "numeric", "float", "double", "money"):
        return "uniform(0, 1000)"
    if bt == "date":
        return "random date (last 5 years)"
    if bt in ("datetime", "timestamp", "timestamptz"):
        return "random datetime (last year)"
    if bt in ("bool", "boolean", "bit"):
        return "random bool"
    if bt in ("varchar", "text", "char", "nvarchar"):
        return "fake.word()"
    return f"fake.word() [{bt}]"


# ---------------------------------------------------------------------------
# Data Generation
# ---------------------------------------------------------------------------

def generate_from_table(
    table: TableDef,
    n: int,
    fake: Faker,
    fk_pools: Optional[Dict[str, List]] = None,
    overrides: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    if fk_pools is None:
        fk_pools = {}
    if overrides is None:
        overrides = {}

    fn_cols = [c.name for c in table.columns if re.search(r"first.?name|fname", c.name.lower())]
    ln_cols = [c.name for c in table.columns if re.search(r"last.?name|lname|surname", c.name.lower())]

    edge_map: Dict[int, Tuple[str, str]] = {}
    if fn_cols and ln_cols:
        count = min(len(EDGE_CASE_NAMES), max(1, n // 12))
        for j, idx in enumerate(random.sample(range(n), count)):
            edge_map[idx] = EDGE_CASE_NAMES[j % len(EDGE_CASE_NAMES)]

    # Build FK pools for tables not already provided
    for col in table.columns:
        if col.fk_table:
            key = col.fk_table.lower()
            if key not in fk_pools:
                fk_pools[key] = [f"SYN-{i+1:06d}" for i in range(max(20, n // 2))]

    rows = []
    for i in range(n):
        row = {}
        edge = edge_map.get(i)
        for col in table.columns:
            if edge and col.name in fn_cols:
                row[col.name] = edge[0]
                continue
            if edge and col.name in ln_cols:
                row[col.name] = edge[1]
                continue
            null_rate = _null_rate(col)
            if null_rate > 0 and random.random() < null_rate:
                row[col.name] = None
                continue
            pool = fk_pools.get(col.fk_table.lower(), []) if col.fk_table else []
            row[col.name] = _generate_value(col, fake, pool, i,
                                            override=overrides.get(col.name))
        rows.append(row)

    return pd.DataFrame(rows)


def generate_all_tables(tables: List[TableDef], n: int, fake: Faker,
                        overrides_all: Optional[Dict[str, Dict[str, str]]] = None) -> Dict[str, pd.DataFrame]:
    """Generate all tables in dependency order for referential integrity."""
    schema_names = {t.name.lower() for t in tables}
    overrides_all = overrides_all or {}
    results: Dict[str, pd.DataFrame] = {}
    pk_pools: Dict[str, List] = {}

    def deps_met(t: TableDef) -> bool:
        return all(
            not (col.fk_table and col.fk_table.lower() in schema_names
                 and col.fk_table.lower() not in pk_pools)
            for col in t.columns
        )

    remaining = list(tables)
    for _ in range(len(tables) * 3):
        if not remaining:
            break
        for t in list(remaining):
            if deps_met(t):
                df = generate_from_table(t, n, fake, dict(pk_pools),
                                         overrides=overrides_all.get(t.name, {}))
                results[t.name] = df
                remaining.remove(t)
                pk_col = next((c for c in t.columns if c.is_pk), None)
                if pk_col and pk_col.name in df.columns:
                    pk_pools[t.name.lower()] = df[pk_col.name].dropna().tolist()

    for t in remaining:  # circular deps or unresolvable
        results[t.name] = generate_from_table(t, n, fake)

    return results


# ---------------------------------------------------------------------------
# Output Formatters
# ---------------------------------------------------------------------------

def to_csv_string(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    buf.write("# Generated by synth-data-gen | All data is fictional\n")
    df.to_csv(buf, index=False)
    return buf.getvalue()


def to_json_string(df: pd.DataFrame) -> str:
    records = json.loads(df.to_json(orient="records", date_format="iso"))
    return json.dumps(
        {"_meta": {"generated_by": "synth-data-gen", "synthetic": True, "record_count": len(records)}, "data": records},
        indent=2, ensure_ascii=False,
    )


def to_sql_string(df: pd.DataFrame, table_name: str) -> str:
    cols = ", ".join(df.columns)
    lines = [
        "-- Generated by synth-data-gen | All data is fictional",
        "-- DO NOT use in production systems\n",
        f"INSERT INTO {table_name} ({cols})\nVALUES",
    ]
    for i, (_, row) in enumerate(df.iterrows()):
        vals = []
        for v in row:
            if v is None or (isinstance(v, float) and pd.isna(v)):
                vals.append("NULL")
            elif isinstance(v, bool):
                vals.append("TRUE" if v else "FALSE")
            elif isinstance(v, (int, float)):
                vals.append(str(v))
            else:
                vals.append("'" + str(v).replace("'", "''") + "'")
        sep = ";" if i == len(df) - 1 else ","
        lines.append(f"    ({', '.join(vals)}){sep}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Inline Validator
# ---------------------------------------------------------------------------

_REAL_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "mail.com", "protonmail.com", "live.com", "msn.com",
}
_SAFE_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "test.invalid", "example.edu"}
_SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@([\w-]+\.[\w.-]+)\b")
_PHONE_RE = re.compile(r"\b(\d{3})[-.)]?\s*(\d{3})[-.]\s*(\d{4})\b")


def validate_text(text: str) -> dict:
    results: dict = {"critical": [], "warnings": [], "info": []}
    safe_ssns = 0
    for area, group, serial in _SSN_RE.findall(text):
        if int(area) in range(1, 900):
            results["critical"].append(f"Real-range SSN: {area}-{group}-{serial}")
        else:
            safe_ssns += 1
    if safe_ssns:
        results["info"].append(f"{safe_ssns} SSN(s) in safe synthetic range (987-65-xxxx)")

    seen_domains: set = set()
    for domain in _EMAIL_RE.findall(text):
        d = domain.lower()
        if d in seen_domains:
            continue
        seen_domains.add(d)
        if d in _REAL_EMAIL_DOMAINS:
            results["critical"].append(f"Real email domain: @{d}")
        elif d not in _SAFE_EMAIL_DOMAINS:
            results["warnings"].append(f"Unrecognized email domain: @{d}")

    unsafe_phones = safe_phones = 0
    for area, exchange, number in _PHONE_RE.findall(text):
        if exchange == "555" and number.startswith("01"):
            safe_phones += 1
        else:
            unsafe_phones += 1
    if unsafe_phones:
        results["warnings"].append(f"{unsafe_phones} phone(s) outside safe 555-01xx range")
    if safe_phones:
        results["info"].append(f"{safe_phones} phone(s) in safe range (555-01xx)")

    return results


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def _render_results(tbl_name: str, df: pd.DataFrame, output_format: str, seed: int) -> None:
    tab_preview, tab_raw, tab_validate, tab_stats = st.tabs(["Preview", "Raw Output", "Validation", "Statistics"])

    with tab_preview:
        st.dataframe(df, use_container_width=True, height=350)

    with tab_raw:
        if output_format == "Table Preview":
            st.info("Select CSV, JSON, or SQL INSERT from the sidebar to get downloadable output.")
            st.dataframe(df, use_container_width=True, height=350)
        elif output_format == "CSV":
            raw = to_csv_string(df)
            st.code(raw[:5000] + ("\n... (truncated)" if len(raw) > 5000 else ""), language="csv")
            st.download_button("Download CSV", raw, file_name=f"synthetic_{tbl_name}.csv",
                               mime="text/csv", key=f"dl_csv_{tbl_name}")
        elif output_format == "JSON":
            raw = to_json_string(df)
            st.code(raw[:5000] + ("\n... (truncated)" if len(raw) > 5000 else ""), language="json")
            st.download_button("Download JSON", raw, file_name=f"synthetic_{tbl_name}.json",
                               mime="application/json", key=f"dl_json_{tbl_name}")
        elif output_format == "SQL INSERT":
            raw = to_sql_string(df, tbl_name)
            st.code(raw[:5000] + ("\n... (truncated)" if len(raw) > 5000 else ""), language="sql")
            st.download_button("Download SQL", raw, file_name=f"synthetic_{tbl_name}.sql",
                               mime="text/sql", key=f"dl_sql_{tbl_name}")

    with tab_validate:
        vr = validate_text(to_csv_string(df))
        for msg in vr["critical"][:10]:
            st.error(f"CRITICAL: {msg}")
        for msg in vr["warnings"][:10]:
            st.warning(f"WARNING: {msg}")
        for msg in vr["info"][:10]:
            st.info(msg)
        if not vr["critical"] and not vr["warnings"]:
            st.success("All checks passed — no real PII/PHI detected.")
        elif vr["critical"]:
            st.error("Critical issues found. DO NOT use this data.")
        else:
            st.warning("Warnings found. Review before using.")

    with tab_stats:
        c1, c2, c3 = st.columns(3)
        c1.metric("Rows", len(df))
        c2.metric("Columns", len(df.columns))
        c3.metric("Seed", seed)
        st.markdown("#### NULL Distribution")
        null_pcts = (df.isnull().sum() / len(df) * 100).round(1)
        null_df = pd.DataFrame({"Column": null_pcts.index, "NULL %": null_pcts.values})
        null_df = null_df[null_df["NULL %"] > 0]
        if len(null_df):
            st.bar_chart(null_df.set_index("Column"))
        else:
            st.info("No NULL values in this dataset.")
        st.markdown("#### Column Details")
        st.dataframe(df.describe(include="all").T, use_container_width=True)


def main():
    st.set_page_config(page_title="Schema-Driven Synthetic Data Generator", page_icon="🗄️", layout="wide")
    st.title("Schema-Driven Synthetic Data Generator")
    st.caption("Paste a SQL `CREATE TABLE` schema and generate realistic synthetic data. All data is entirely fictional.")

    # Sidebar
    st.sidebar.header("Generation Settings")
    row_count = st.sidebar.slider("Rows per table", min_value=5, max_value=5000, value=50, step=5)
    seed = st.sidebar.number_input("Random Seed", min_value=0, max_value=999999, value=42)
    output_format = st.sidebar.selectbox("Output Format", ["Table Preview", "CSV", "JSON", "SQL INSERT"])

    # Session state for example loading
    if "ddl_input" not in st.session_state:
        st.session_state.ddl_input = ""

    # Schema input
    st.subheader("1. Paste your SQL schema")
    col_input, col_example = st.columns([3, 1])

    with col_input:
        ddl_text = st.text_area(
            "CREATE TABLE DDL",
            height=220,
            placeholder="CREATE TABLE my_table (\n    id INT PRIMARY KEY,\n    name VARCHAR(100) NOT NULL,\n    ...\n);",
            key="ddl_input",
            label_visibility="collapsed",
        )

    with col_example:
        uploaded = st.file_uploader("Upload .sql file", type=["sql", "txt"])
        if uploaded:
            st.session_state.ddl_input = uploaded.read().decode("utf-8", errors="replace")
            st.rerun()
        st.markdown("---")
        if st.button("Load example schema", use_container_width=True):
            st.session_state.ddl_input = EXAMPLE_DDL
            st.rerun()
        st.caption("Loads a sample patients + encounters schema")

    # Parse
    tables: List[TableDef] = []
    if ddl_text and ddl_text.strip():
        try:
            tables = parse_ddl(ddl_text)
        except Exception as e:
            st.error(f"Parse error: {e}")
        if not tables:
            st.warning("No `CREATE TABLE` statements found. Check your DDL syntax.")

    # Schema preview
    if tables:
        st.subheader("2. Parsed Schema")
        st.caption(f"Found {len(tables)} table(s). Review inferred generators — you can override any "
                   "column's generator from the dropdown before generating. PK/FK columns stay locked "
                   "to preserve referential integrity.")
        for t in tables:
            with st.expander(f"**{t.name}** — {len(t.columns)} columns", expanded=len(tables) <= 2):
                saved = st.session_state.get(f"overrides_{t.name}", {})
                col_data = []
                for c in t.columns:
                    flags = []
                    if c.is_pk:
                        flags.append("PK")
                    if c.fk_table:
                        flags.append(f"FK → {c.fk_table}")
                    if not c.nullable:
                        flags.append("NOT NULL")
                    locked = bool(c.is_pk or c.fk_table)
                    col_data.append({
                        "Column": c.name,
                        "SQL Type": c.sql_type,
                        "Flags": " | ".join(flags) if flags else "—",
                        "Inferred Generator": _describe_generator(c),
                        "Generator": "Auto (locked)" if locked else saved.get(c.name, AUTO),
                    })
                preview_df = pd.DataFrame(col_data)
                edited = st.data_editor(
                    preview_df,
                    use_container_width=True,
                    hide_index=True,
                    key=f"editor_{t.name}",
                    disabled=["Column", "SQL Type", "Flags", "Inferred Generator"],
                    column_config={
                        "Generator": st.column_config.SelectboxColumn(
                            "Generator (editable)",
                            options=[AUTO] + list(GENERATOR_REGISTRY.keys()),
                            help="Override the inferred generator for this column",
                        ),
                    },
                )
                # persist overrides (skip locked columns rendered as Auto (locked))
                overrides = {
                    r["Column"]: r["Generator"]
                    for _, r in edited.iterrows()
                    if r["Generator"] not in (AUTO, "Auto (locked)")
                }
                st.session_state[f"overrides_{t.name}"] = overrides
                if overrides:
                    st.caption(f"{len(overrides)} column(s) overridden: "
                               + ", ".join(f"`{c}`" for c in list(overrides)[:6])
                               + (" …" if len(overrides) > 6 else ""))

    # Generation controls
    if tables:
        st.subheader("3. Generate")
        gen_mode = st.radio(
            "Mode",
            ["Single table", "All tables (with referential integrity)"],
            horizontal=True,
        )
        selected_table = None
        if gen_mode == "Single table":
            selected_table = st.selectbox("Table", [t.name for t in tables])

        if st.button("Generate Data", type="primary"):
            random.seed(seed)
            Faker.seed(seed)
            fake = Faker()

            if gen_mode == "All tables (with referential integrity)":
                overrides_all = {t.name: st.session_state.get(f"overrides_{t.name}", {})
                                 for t in tables}
            else:
                tbl = next(t for t in tables if t.name == selected_table)
                overrides_all = {tbl.name: st.session_state.get(f"overrides_{tbl.name}", {})}

            with st.spinner("Generating..."):
                if gen_mode == "All tables (with referential integrity)":
                    all_dfs = generate_all_tables(tables, row_count, fake, overrides_all)
                else:
                    all_dfs = {tbl.name: generate_from_table(tbl, row_count, fake,
                                                             overrides=overrides_all.get(tbl.name, {}))}

            total_rows = sum(len(df) for df in all_dfs.values())
            st.success(f"Generated {total_rows} row(s) across {len(all_dfs)} table(s) (seed={seed})")

            if len(all_dfs) > 1:
                manifest = {
                    "_meta": {"generated_by": "synth-data-gen schema_app", "synthetic": True,
                              "seed": seed, "rows_per_table": row_count,
                              "timestamp": datetime.now().isoformat(timespec="seconds")},
                    "tables": {k: len(v) for k, v in all_dfs.items()},
                }
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for tbl_name, df in all_dfs.items():
                        zf.writestr(f"synthetic_{tbl_name}.csv", to_csv_string(df))
                    zf.writestr("manifest.json", json.dumps(manifest, indent=2))
                st.download_button("📦 Download all tables (zip, CSV + manifest)",
                                   buf.getvalue(), file_name="synthetic_schema_bundle.zip",
                                   mime="application/zip")

            for tbl_name, df in all_dfs.items():
                st.markdown(f"#### `{tbl_name}`")
                _render_results(tbl_name, df, output_format, seed)

    elif not ddl_text or not ddl_text.strip():
        st.markdown("---")
        st.markdown(
            "**Supported inputs:** any standard `CREATE TABLE` DDL — PostgreSQL, MySQL, SQLite, SQL Server\n\n"
            "**Semantic mapping:** column names like `first_name`, `email`, `ssn`, `dob`, `zip`, `salary` "
            "automatically map to realistic generators. All other columns fall back to SQL type-based generation.\n\n"
            "**Safety:** SSNs use `987-65-xxxx`, emails use `@example.com`, phones use `555-01xx`. "
            "An inline validator checks every output before delivery."
        )


if __name__ == "__main__":
    main()
