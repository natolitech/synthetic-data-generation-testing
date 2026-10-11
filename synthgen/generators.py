"""Shared constants and safe-range helpers for synthetic generation."""
import json
import random
import re
import uuid
from datetime import date, timedelta
from typing import Any, List

from faker import Faker

from .schema import ColumnDef
from . import notes
from .clock import clock

# --- safe-range constants (from the skill CLI copy) ---

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

def weighted_choice(options):
    values, weights = zip(*options)
    return random.choices(values, weights=weights, k=1)[0]


def safe_ssn() -> str:
    return f"{SAFE_SSN_PREFIX}-{random.randint(0, 9999):04d}"


def safe_phone() -> str:
    return f"{SAFE_PHONE_PREFIX}{random.randint(0, 99):02d}"


def safe_email(fake: Faker) -> str:
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
                   "ed_note", "telehealth_note", "procedure_note",
                   "radiology_report", "behavioral_health_note",
                   "patient_portal_message", "phone_call_transcript"]
_NARRATIVE_RE = re.compile(
    r"note(_text|_body|s)?$|progress.?note|discharge.?summar|soap|"
    r"h.?and.?p$|^hpi$|chief.?complaint|narrative|clinical.?text|impression$"
)
_DICTATION_RE = re.compile(r"dictation|transcript")


def generate_value(col: ColumnDef, fake: Faker, fk_pool: List, row_idx: int,
                 override: str = None) -> Any:
    name = col.name.lower()
    bt = col.base_type

    # manual override from the UI/CLI (PK/FK stay locked to preserve integrity)
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
        if _gen_note is not None:
            note = notes.generate_note(row_idx, fake, "mix", dictation_ratio=1.0)["note_text"]
            return _truncate_to_col(note, col)
        return _truncate_to_col(
            "Dictation received via telephone line. Patient reports ongoing symptoms; "
            "transcription pending review by attending provider.", col)
    if _NARRATIVE_RE.search(name):
        if _gen_note is not None:
            note = notes.generate_note(row_idx, fake, "mix", dictation_ratio=0.0)["note_text"]
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
        return (clock.today() - timedelta(days=age * 365 + random.randint(0, 364))).isoformat()
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
        return (clock.now() - timedelta(days=random.randint(1, 730), hours=random.randint(0, 23))).isoformat(timespec="minutes")
    if re.search(r"updated.?at|modified.?at|last.?modified|updated.?date", name):
        return (clock.now() - timedelta(days=random.randint(0, 365))).isoformat(timespec="minutes")
    if re.search(r"deleted.?at|archived.?at|deactivated.?at", name):
        return None
    if re.search(r"hire.?date|start.?date|employment.?date", name):
        return (clock.today() - timedelta(days=random.randint(30, 10950))).isoformat()
    if re.search(r"termination.?date|term.?date|end.?date|expir", name):
        return (clock.today() + timedelta(days=random.randint(-365, 365))).isoformat() if random.random() > 0.6 else None
    if re.search(r"admit.?date|admit.?time|admission.?date|admit.?datetime", name):
        return (clock.now() - timedelta(days=random.randint(1, 365), hours=random.randint(0, 23))).isoformat(timespec="minutes")
    if re.search(r"discharge.?date|discharge.?time|discharge.?datetime", name):
        return (clock.now() - timedelta(days=random.randint(0, 360))).isoformat(timespec="minutes")
    if re.search(r"last.?logon|last.?login|last.?access|last.?seen", name):
        return (clock.now() - timedelta(days=random.randint(0, 90))).isoformat(timespec="minutes")
    if re.search(r"password.?last.?set|pwd.?changed", name):
        return (clock.today() - timedelta(days=random.randint(0, 180))).isoformat()

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
        return (clock.today() - timedelta(days=random.randint(0, 1825))).isoformat()
    if bt in ("datetime", "timestamp", "datetime2", "datetimeoffset", "timestamptz",
              "timestamp_without_time_zone", "timestamp_with_time_zone"):
        return (clock.now() - timedelta(days=random.randint(0, 365), hours=random.randint(0, 23))).isoformat(timespec="minutes")
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


def null_rate(col: ColumnDef) -> float:
    if col.is_pk or not col.nullable:
        return 0.0
    name = col.name.lower()
    if re.search(r"deleted|archived|terminated|end_date|expir|middle|line2|line_2|fax|suffix|notes|description|comments|reason", name):
        return 0.38
    if re.search(r"phone|mobile|cell|secondary|optional|alt_", name):
        return 0.12
    return 0.07

# --- generator registry (in-app override support; from schema_app) ---

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
    return (clock.today() - timedelta(days=age * 365 + random.randint(0, 364))).isoformat()
def _gen_gender(col, fake, i):
    return random.choices(["Female", "Male", "Non-binary", "Unknown"],
                          weights=[0.49, 0.49, 0.015, 0.005])[0]
def _gen_address(col, fake, i): return fake.street_address()
def _gen_city(col, fake, i): return fake.city()
def _gen_state(col, fake, i): return fake.state_abbr()
def _gen_zip(col, fake, i): return fake.zipcode()
def _gen_recent_ts(col, fake, i):
    return (clock.now() - timedelta(days=random.randint(1, 730))).isoformat(timespec="minutes")
def _gen_past_date(col, fake, i):
    return (clock.today() - timedelta(days=random.randint(1, 3650))).isoformat()
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
    return _truncate_to_col(notes.generate_note(i, fake, "mix", dictation_ratio=0.0)["note_text"], col)
def _gen_dictation(col, fake, i):
    return _truncate_to_col(notes.generate_note(i, fake, "mix", dictation_ratio=1.0)["note_text"], col)
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

def describe_generator(col: ColumnDef) -> str:
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


def reconcile_age(rows: list, table) -> None:
    """Temporal consistency: when a table has both DOB and age columns, derive
    age from DOB instead of leaving them independently random."""
    dob_col = next((c.name for c in table.columns
                    if re.search(r"^dob$|birth.?date|date.?of.?birth|birthdate", c.name.lower())), None)
    age_col = next((c.name for c in table.columns if c.name.lower() == "age"), None)
    if not (dob_col and age_col):
        return
    today = clock.today()
    for row in rows:
        dob = row.get(dob_col)
        if not dob:
            continue
        try:
            d = date.fromisoformat(str(dob)[:10])
        except ValueError:
            continue
        row[age_col] = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
