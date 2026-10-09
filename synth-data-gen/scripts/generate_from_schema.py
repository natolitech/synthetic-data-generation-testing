#!/usr/bin/env python3
"""
generate_from_schema.py — Schema-driven synthetic data generator
================================================================
Reads SQL DDL schema files and generates realistic synthetic data
to populate a database. All data is entirely fictional — no real
PII or PHI is generated.

Usage:
    # Single schema file, CSV output (default)
    python generate_from_schema.py schema/my_schema.sql

    # Entire schema directory
    python generate_from_schema.py schema/ --rows 200 --output ./synthetic/

    # JSON output with validation
    python generate_from_schema.py schema/ --format json --validate

    # Specific tables only, seeded for reproducibility
    python generate_from_schema.py schema/all.sql --tables patients encounters --seed 42

    # SQL INSERT output for seeding a database
    python generate_from_schema.py schema/ --format sql --output ./seed_data/

Exit codes:
    0  — success
    1  — validation warnings (data generated but review recommended)
    2  — validation critical issues (do not use generated data)
    3  — schema parse error or no tables found

Dependencies:
    pip install faker pandas
"""

import argparse
import io
import json
import random
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:  # sibling module — enables narrative note/dictation columns
    from clinical_notes import generate_note as _gen_note
except ImportError:  # pragma: no cover - fallback when notes module is absent
    _gen_note = None

try:
    from faker import Faker
    import pandas as pd
except ImportError:
    print("Missing dependencies. Install with: pip install faker pandas", file=sys.stderr)
    sys.exit(3)


# ---------------------------------------------------------------------------
# Safety constants — all generated identifiers stay in reserved/fictional ranges
# ---------------------------------------------------------------------------

SAFE_SSN_PREFIX = "987-65"          # IRS test range
SAFE_EMAIL_DOMAINS = ["example.com", "example.org", "test.invalid"]
SAFE_PHONE_PREFIX = "555-01"        # NANPA reserved for fiction

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
CLINICAL_DEPARTMENTS = ["Cardiology", "Primary Care", "Emergency", "Surgery", "OB/GYN",
                        "Psychiatry", "Pediatrics", "Orthopedics", "Neurology", "Oncology"]
ADJUDICATION_STATUSES = ["Paid", "Pending", "Denied", "Appealed", "Voided"]
ACCOUNT_STATUSES = ["Active", "Disabled", "Locked", "Expired"]
ENROLLMENT_STATUSES = ["Enrolled", "Graduated", "Withdrawn", "Leave of Absence"]


# ---------------------------------------------------------------------------
# Schema parsing
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
    source_file: str = ""
    columns: List[ColumnDef] = field(default_factory=list)


def _split_top_level(text: str) -> List[str]:
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


def parse_ddl(text: str, source_file: str = "") -> List[TableDef]:
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
            tables.append(TableDef(name=table_name, source_file=source_file, columns=columns))

    return tables


def load_schema(path: Path) -> List[TableDef]:
    """Load schema from a file or every .sql/.ddl file in a directory."""
    if path.is_file():
        return parse_ddl(path.read_text(encoding="utf-8", errors="replace"), source_file=path.name)

    tables = []
    for ext in ("*.sql", "*.ddl"):
        for f in sorted(path.glob(ext)):
            tables.extend(parse_ddl(f.read_text(encoding="utf-8", errors="replace"), source_file=f.name))
    return tables


# ---------------------------------------------------------------------------
# Semantic value generator
# ---------------------------------------------------------------------------

def _weighted(options):
    values, weights = zip(*options)
    return random.choices(values, weights=weights, k=1)[0]


def _safe_email(fake: Faker) -> str:
    first = re.sub(r"[^a-zA-Z0-9]", "", fake.first_name().lower())
    last = re.sub(r"[^a-zA-Z0-9]", "", fake.last_name().lower())
    return f"{first}.{last}@{random.choice(SAFE_EMAIL_DOMAINS)}"


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


def _generate_value(col: ColumnDef, fake: Faker, fk_pool: List, row_idx: int) -> Any:
    name = col.name.lower()
    bt = col.base_type

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
        if _gen_note is not None:
            note = _gen_note(row_idx, fake, "mix", dictation_ratio=1.0)["note_text"]
            return _truncate_to_col(note, col)
        return _truncate_to_col(
            "Dictation received via telephone line. Patient reports ongoing symptoms; "
            "transcription pending review by attending provider.", col)
    if _NARRATIVE_RE.search(name):
        if _gen_note is not None:
            note = _gen_note(row_idx, fake, "mix", dictation_ratio=0.0)["note_text"]
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
        return _safe_email(fake)
    if re.search(r"^phone$|phone.?number|^mobile$|^cell$|telephone|^tel$", name):
        return f"{SAFE_PHONE_PREFIX}{random.randint(0, 99):02d}"
    if re.search(r"^fax$|fax.?number", name):
        return f"{SAFE_PHONE_PREFIX}{random.randint(0, 99):02d}"

    # Identity documents
    if re.search(r"^ssn$|social.?security", name):
        return f"{SAFE_SSN_PREFIX}-{random.randint(0, 9999):04d}"
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
        return _weighted(RACE_OPTIONS)
    if re.search(r"^ethnicity$", name):
        return _weighted(ETHNICITY_OPTIONS)
    if re.search(r"^language$|preferred.?language|^lang$", name):
        return _weighted(LANGUAGES)

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
    if re.search(r"^department$|^dept$|clinical.?dept|clinical.?department", name):
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
    if re.search(r"^description$|^desc$|^notes$|^note$|^comments$|^comment$|^summary$|^details$|^reason$", name):
        return fake.sentence()
    if re.search(r"^url$|^website$|^homepage$|^link$", name):
        return f"https://example.com/{fake.slug()}"
    if re.search(r"ip.?address|ip.?addr|^ip$", name):
        return f"192.0.2.{random.randint(1, 254)}"
    if re.search(r"^uuid$|^guid$", name):
        return str(uuid.uuid4())

    # Booleans
    if bt in ("bool", "boolean"):
        if re.search(r"active|enabled|is_active", name):
            return random.random() < 0.85
        if re.search(r"deceased|terminated|deleted|archived", name):
            return random.random() < 0.05
        return random.random() < 0.15
    if bt == "bit":
        return 1 if random.random() < 0.5 else 0

    if re.search(r"^status$", name):
        return random.choice(["Active", "Inactive", "Pending"])

    # Type-based fallbacks
    if bt in ("int", "integer", "bigint", "smallint", "tinyint", "int2", "int4", "int8", "serial", "bigserial"):
        return random.randint(0, 100) if re.search(r"count|qty|rank|score|priority|seq", name) else random.randint(1, 10000)
    if bt in ("float", "double", "real", "float4", "float8", "double_precision"):
        return round(random.uniform(0.0, 100.0), 4)
    if bt in ("decimal", "numeric", "money", "smallmoney"):
        return round(random.uniform(0.0, 1000.0), 2)
    if bt == "date":
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


def _null_rate(col: ColumnDef) -> float:
    if col.is_pk or not col.nullable:
        return 0.0
    name = col.name.lower()
    if re.search(r"deleted|archived|terminated|end_date|expir|middle|line2|line_2|fax|suffix|notes|description|comments|reason", name):
        return 0.38
    if re.search(r"phone|mobile|cell|secondary|optional|alt_", name):
        return 0.12
    return 0.07


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def generate_table(table: TableDef, n: int, fake: Faker,
                   fk_pools: Optional[Dict[str, List]] = None) -> pd.DataFrame:
    if fk_pools is None:
        fk_pools = {}

    fn_cols = [c.name for c in table.columns if re.search(r"first.?name|fname", c.name.lower())]
    ln_cols = [c.name for c in table.columns if re.search(r"last.?name|lname|surname", c.name.lower())]

    edge_map: Dict[int, Tuple[str, str]] = {}
    if fn_cols and ln_cols:
        count = min(len(EDGE_CASE_NAMES), max(1, n // 12))
        for j, idx in enumerate(random.sample(range(n), count)):
            edge_map[idx] = EDGE_CASE_NAMES[j % len(EDGE_CASE_NAMES)]

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
            row[col.name] = _generate_value(col, fake, pool, i)
        rows.append(row)

    return pd.DataFrame(rows)


def generate_all(tables: List[TableDef], n: int, fake: Faker) -> Dict[str, pd.DataFrame]:
    """Generate all tables in FK dependency order."""
    schema_names = {t.name.lower() for t in tables}
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
                df = generate_table(t, n, fake, dict(pk_pools))
                results[t.name] = df
                remaining.remove(t)
                pk_col = next((c for c in t.columns if c.is_pk), None)
                if pk_col and pk_col.name in df.columns:
                    pk_pools[t.name.lower()] = df[pk_col.name].dropna().tolist()

    for t in remaining:  # circular deps
        results[t.name] = generate_table(t, n, fake)

    return results


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def to_csv(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    buf.write("# Generated by synth-data-gen | All data is fictional\n")
    df.to_csv(buf, index=False)
    return buf.getvalue()


def to_json(df: pd.DataFrame) -> str:
    records = json.loads(df.to_json(orient="records", date_format="iso"))
    return json.dumps(
        {"_meta": {"generated_by": "synth-data-gen", "synthetic": True, "record_count": len(records)},
         "data": records},
        indent=2, ensure_ascii=False,
    )


def to_sql(df: pd.DataFrame, table_name: str) -> str:
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
# Validator
# ---------------------------------------------------------------------------

_REAL_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "mail.com", "protonmail.com", "live.com", "msn.com",
}
_SAFE_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "test.invalid", "example.edu"}
_SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@([\w-]+\.[\w.-]+)\b")
_PHONE_RE = re.compile(r"\b(\d{3})[-.)]?\s*(\d{3})[-.]\s*(\d{4})\b")


def validate(text: str) -> dict:
    results: dict = {"critical": [], "warnings": [], "info": []}
    safe_ssns = 0
    for area, _, _s in _SSN_RE.findall(text):
        if int(area) in range(1, 900):
            results["critical"].append(f"Real-range SSN area: {area}")
        else:
            safe_ssns += 1
    if safe_ssns:
        results["info"].append(f"{safe_ssns} SSN(s) in safe range (987-65-xxxx)")

    seen: set = set()
    for domain in _EMAIL_RE.findall(text):
        d = domain.lower()
        if d in seen:
            continue
        seen.add(d)
        if d in _REAL_EMAIL_DOMAINS:
            results["critical"].append(f"Real email domain: @{d}")
        elif d not in _SAFE_EMAIL_DOMAINS:
            results["warnings"].append(f"Unrecognized email domain: @{d}")

    unsafe = safe = 0
    for _, exchange, number in _PHONE_RE.findall(text):
        if exchange == "555" and number.startswith("01"):
            safe += 1
        else:
            unsafe += 1
    if unsafe:
        results["warnings"].append(f"{unsafe} phone(s) outside safe 555-01xx range")
    if safe:
        results["info"].append(f"{safe} phone(s) in safe range")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate synthetic data from a SQL DDL schema file or directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("schema", help="Schema file (.sql/.ddl) or directory of schema files")
    parser.add_argument("-n", "--rows", type=int, default=100, help="Rows per table (default: 100)")
    parser.add_argument("-s", "--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("-f", "--format", choices=["csv", "json", "sql"], default="csv",
                        help="Output format (default: csv)")
    parser.add_argument("-o", "--output", default="./synthetic_output",
                        help="Output directory (default: ./synthetic_output)")
    parser.add_argument("-t", "--tables", nargs="+", metavar="TABLE",
                        help="Only generate these tables (default: all)")
    parser.add_argument("--validate", action="store_true",
                        help="Run PII/PHI validation after generation")
    parser.add_argument("--list-tables", action="store_true",
                        help="Print detected table names and exit")
    args = parser.parse_args()

    schema_path = Path(args.schema)
    if not schema_path.exists():
        print(f"ERROR: Schema path not found: {schema_path}", file=sys.stderr)
        return 3

    print(f"Loading schema from: {schema_path}")
    tables = load_schema(schema_path)

    if not tables:
        print("ERROR: No CREATE TABLE statements found. Check your DDL syntax.", file=sys.stderr)
        return 3

    if args.list_tables:
        print(f"\nFound {len(tables)} table(s):")
        for t in tables:
            src = f"  [{t.source_file}]" if t.source_file else ""
            pk = next((c.name for c in t.columns if c.is_pk), "none")
            fks = [f"{c.name}→{c.fk_table}" for c in t.columns if c.fk_table]
            print(f"  {t.name}{src}  (pk: {pk}{', fk: ' + ', '.join(fks) if fks else ''})")
        return 0

    # Filter to requested tables
    if args.tables:
        requested = {t.lower() for t in args.tables}
        tables = [t for t in tables if t.name.lower() in requested]
        if not tables:
            print(f"ERROR: None of the requested tables found. "
                  f"Use --list-tables to see available tables.", file=sys.stderr)
            return 3

    print(f"Generating {args.rows} rows per table for {len(tables)} table(s) "
          f"(seed={args.seed}, format={args.format})")

    random.seed(args.seed)
    Faker.seed(args.seed)
    fake = Faker()

    results = generate_all(tables, args.rows, fake)

    # Write output
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    ext_map = {"csv": ".csv", "json": ".json", "sql": ".sql"}
    ext = ext_map[args.format]

    exit_code = 0
    for table_name, df in results.items():
        out_file = out_dir / f"synthetic_{table_name}{ext}"

        if args.format == "csv":
            content = to_csv(df)
        elif args.format == "json":
            content = to_json(df)
        else:
            content = to_sql(df, table_name)

        out_file.write_text(content, encoding="utf-8")
        print(f"  Wrote {len(df)} rows → {out_file}")

        if args.validate:
            vr = validate(content)
            for msg in vr["critical"]:
                print(f"    CRITICAL: {msg}", file=sys.stderr)
                exit_code = max(exit_code, 2)
            for msg in vr["warnings"]:
                print(f"    WARNING:  {msg}", file=sys.stderr)
                exit_code = max(exit_code, 1)
            for msg in vr["info"]:
                print(f"    INFO:     {msg}")
            if not vr["critical"] and not vr["warnings"]:
                print(f"    Validation passed — no real PII/PHI detected.")

    print(f"\nDone. Output in: {out_dir.resolve()}")
    if exit_code == 2:
        print("WARNING: Critical validation issues found. DO NOT use this data.", file=sys.stderr)
    elif exit_code == 1:
        print("NOTE: Validation warnings found. Review before using.")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
