#!/usr/bin/env python3
"""
Clinical Bundle Generator — referentially-linked synthetic EHR dataset
=======================================================================
Generates a full clinical dataset where every table references the SAME patient
pool with a consistent timeline:

    patients → encounters → diagnoses
                        ├──→ lab_results
                        └──→ clinical_notes (identity + dx + dates match)

Guarantees:
- encounter.patient_id always exists in patients
- diagnoses/labs/notes .encounter_id always exists in encounters
- note.patient_id equals its encounter's patient_id
- DOB < admit < discharge, and note service_datetime falls inside the encounter window
- note narrative embeds the actual patient's name/MRN/DOB and the encounter's
  principal diagnosis (meds/labs in the narrative match the dx)
- All identifiers stay in safe/fictional ranges (SSN 987-65-xxxx, 555-01xx, MRN-224xxxx)

Output formats: csv | json | sql | fhir | hl7  (fhir/hl7 implemented by
fhir_export.py / hl7_export.py). Every run also writes a manifest.json for
reproducibility, and --zip bundles everything into one archive.

Run:
    python clinical_bundle.py -n 100 --validate
    python clinical_bundle.py -n 250 --format fhir --zip
    python clinical_bundle.py -n 50 --format hl7 --dictation-ratio 0.5
"""

import argparse
import hashlib
import io
import json
import random
import re
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from faker import Faker

import clinical_notes as cn

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAFE_SSN_PREFIX = "987-65"

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
EDGE_CASE_NAMES = cn.__dict__.get("EDGE_CASE_NAMES", [])

DEPARTMENTS = ["Cardiology", "Oncology", "Primary Care", "Emergency", "Surgery",
               "OB/GYN", "Psychiatry", "Pediatrics", "Orthopedics", "Neurology"]
ENCOUNTER_TYPES = [("Outpatient", 0.60), ("ED", 0.15), ("Inpatient", 0.10),
                   ("Telehealth", 0.10), ("Observation", 0.05)]
DISPOSITIONS = [("Discharged Home", 0.85), ("Transfer", 0.05), ("AMA", 0.01),
                ("Expired", 0.005), ("Observation", 0.085)]

LOS_HOURS = {"Inpatient": (24, 240), "ED": (2, 12), "Outpatient": (0, 2),
             "Telehealth": (0, 0), "Observation": (12, 48)}

# encounters per patient (some patients have none — realistic)
ENC_PER_PATIENT = [(0, 0.10), (1, 0.40), (2, 0.25), (3, 0.15), (4, 0.10)]

# labs: loinc, name, unit, ref_low, ref_high, abs_low, abs_high
LAB_DEFS = [
    ("2951-2", "Sodium", "mEq/L", 136, 145, 120, 160),
    ("2823-3", "Potassium", "mEq/L", 3.5, 5.0, 2.5, 7.0),
    ("2075-0", "Chloride", "mEq/L", 98, 106, 85, 120),
    ("3094-0", "BUN", "mg/dL", 7, 20, 3, 80),
    ("2160-0", "Creatinine", "mg/dL", 0.6, 1.2, 0.3, 10.0),
    ("2345-7", "Glucose", "mg/dL", 70, 100, 40, 500),
    ("6690-2", "WBC", "10*3/uL", 4.5, 11.0, 1.0, 30.0),
    ("718-7", "Hemoglobin", "g/dL", 12.0, 17.5, 5.0, 22.0),
    ("4548-4", "HbA1c", "%", 4.0, 6.0, 3.5, 14.0),
    ("3016-3", "TSH", "mIU/L", 0.4, 4.0, 0.01, 50.0),
]

CONDITIONS = cn.CONDITIONS  # name -> {icd10, meds, labs, symptoms, followup}

TABLE_ORDER = ["patients", "encounters", "diagnoses", "medications",
               "lab_results", "clinical_notes"]

# ---------------------------------------------------------------------------
# Locale packs — region-appropriate fictional ranges
# ---------------------------------------------------------------------------
# US phones use the NANP fictional range (555-01xx); UK uses the Ofcom drama
# range (01632 960xxx); Canada shares NANP; EU uses a synthetic +49 pattern.
# Non-US patients get a NULL ssn column (foreign patients rarely have one —
# and there is no universally "safe" national-ID range outside the US).

LOCALES = {
    "us": {
        "label": "United States",
        "faker_locale": None,
        "languages": [("English", 0.70), ("Spanish", 0.15), ("Mandarin", 0.05),
                      ("Arabic", 0.03), ("Tagalog", 0.02), ("Korean", 0.02),
                      ("Hindi", 0.01), ("French", 0.01), ("Vietnamese", 0.01)],
        "ssn": True,
    },
    "uk": {
        "label": "United Kingdom",
        "faker_locale": "en_GB",
        "languages": [("English", 0.90), ("Polish", 0.03), ("Urdu", 0.02),
                      ("Punjabi", 0.02), ("Bengali", 0.01), ("Gujarati", 0.01),
                      ("French", 0.01)],
        "ssn": False,
    },
    "ca": {
        "label": "Canada",
        "faker_locale": "en_CA",
        "languages": [("English", 0.68), ("French", 0.27), ("Mandarin", 0.02),
                      ("Punjabi", 0.02), ("Tagalog", 0.01)],
        "ssn": False,
    },
    "eu": {
        "label": "European Union (Germany)",
        "faker_locale": "de_DE",
        "languages": [("German", 0.84), ("English", 0.10), ("Turkish", 0.03),
                      ("Polish", 0.02), ("Arabic", 0.01)],
        "ssn": False,
    },
}


def _locale_phone(locale_key: str) -> str:
    if locale_key == "uk":
        return f"01632 960{random.randint(100, 999)}"      # Ofcom drama range
    if locale_key == "ca":
        return f"555-01{random.randint(0, 9)}{random.randint(0, 9)}"  # NANP
    if locale_key == "eu":
        return f"+49 30 5550-{random.randint(100, 999)}"   # synthetic pattern
    return f"555-01{random.randint(0, 9)}{random.randint(0, 9)}"


def _locale_postal(locale_key: str, loc_fake) -> str:
    if locale_key == "uk":
        # ZZ99 is the UK/NHS convention for test/development postcodes
        letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        return f"ZZ99 {random.randint(1, 9)}{random.choice(letters)}{random.choice(letters)}"
    if locale_key == "ca":
        # FSA 'Z' prefix is unassigned in Canada — zero collision with real codes
        letters = "ABCDEFGHJKLMNPRSTVXY"
        return (f"Z{random.randint(0, 9)}{random.choice(letters)} "
                f"{random.randint(0, 9)}{random.choice(letters)}{random.randint(0, 9)}")
    if locale_key == "eu":
        return f"{random.randint(10, 99)}{random.randint(100, 999)}"
    return loc_fake.zipcode()


def _locale_region(locale_key: str, loc_fake) -> str:
    """Administrative area for the `state` column."""
    try:
        if locale_key == "uk" and hasattr(loc_fake, "county"):
            return loc_fake.county()
        if locale_key == "ca" and hasattr(loc_fake, "province_abbr"):
            return loc_fake.province_abbr()
        if locale_key == "eu":
            return random.choice(["BY", "BE", "BW", "NRW", "HE", "SN"])
        return loc_fake.state_abbr()
    except Exception:
        return ""


# Condition-relevant labs: values biased to ranges that agree with the dx
CONDITION_LABS = {
    "Type 2 diabetes mellitus": [
        ("4548-4", "HbA1c", "%", 4.0, 6.0, 7.2, 11.5),      # biased high
        ("2345-7", "Glucose", "mg/dL", 70, 100, 140, 380),
    ],
    "Essential hypertension": [
        ("3094-0", "BUN", "mg/dL", 7, 20, 7, 20),
        ("2160-0", "Creatinine", "mg/dL", 0.6, 1.2, 0.6, 1.6),
    ],
    "Community-acquired pneumonia": [
        ("6690-2", "WBC", "10*3/uL", 4.5, 11.0, 12.5, 24.0),  # biased high
    ],
    "Atrial fibrillation": [
        ("3016-3", "TSH", "mIU/L", 0.4, 4.0, 0.4, 4.0),
    ],
}


def _weighted(options):
    values, weights = zip(*options)
    return random.choices(values, weights=weights, k=1)[0]


def _safe_ssn():
    return f"{SAFE_SSN_PREFIX}-{random.randint(0, 9999):04d}"


def _safe_phone():
    return f"555-01{random.randint(0, 9)}{random.randint(0, 9)}"


# ---------------------------------------------------------------------------
# Cohort generation
# ---------------------------------------------------------------------------

def generate_clinical_cohort(n_patients: int = 100, fake: Faker = None,
                             encounters_per_patient=None,
                             dictation_ratio: float = 0.35,
                             with_notes: bool = True,
                             note_probability: float = 0.7,
                             locale: str = "us") -> dict:
    """Generate a referentially-linked clinical dataset.

    Returns a dict of DataFrames keyed by table name (TABLE_ORDER).
    `locale` in {"us","uk","ca","eu"} localizes names/addresses/phones with
    region-appropriate fictional ranges (non-US patients have NULL ssn).
    """
    fake = fake or Faker()
    if encounters_per_patient is None:
        encounters_per_patient = ENC_PER_PATIENT

    pack = LOCALES.get(locale, LOCALES["us"])
    loc_fake = Faker(pack["faker_locale"]) if pack["faker_locale"] else fake

    # ---- provider pool (shared by encounters, notes, FHIR practitioners) ----
    providers = []
    for i in range(200):
        first, last = fake.first_name(), fake.last_name()
        providers.append({
            "provider_id": f"PRV-{1001 + i}",
            "first": first, "last": last,
            "display": f"Dr. {first} {last}, MD",
            "display_short": f"Dr. {last}",
            "npi": cn.safe_npi(),
        })

    # ---- patients (locale-aware) --------------------------------------------
    patients = []
    edge_every = max(1, n_patients // 12)
    for i in range(n_patients):
        if locale == "us" and i % edge_every == 0 and EDGE_CASE_NAMES:
            first, last = EDGE_CASE_NAMES[(i // edge_every) % len(EDGE_CASE_NAMES)]
        else:
            first, last = loc_fake.first_name(), loc_fake.last_name()

        age_bucket = _weighted([("pediatric", 0.05), ("young_adult", 0.40),
                                ("middle", 0.35), ("senior", 0.20)])
        age = {"pediatric": random.randint(0, 17), "young_adult": random.randint(18, 44),
               "middle": random.randint(45, 64), "senior": random.randint(65, 99)}[age_bucket]
        dob = date.today() - timedelta(days=age * 365 + random.randint(0, 364))

        patients.append({
            "patient_id": f"SYN-{i + 1:06d}",
            "mrn": f"MRN-{2240001 + i}",
            "first_name": first,
            "last_name": last,
            "dob": dob.isoformat(),
            "gender": _weighted([("Female", 0.49), ("Male", 0.49),
                                 ("Non-binary", 0.015), ("Unknown", 0.005)]),
            "race": _weighted(RACE_OPTIONS),
            "ethnicity": _weighted(ETHNICITY_OPTIONS),
            "ssn": (None if random.random() < 0.05 else _safe_ssn()) if pack["ssn"] else None,
            "email": None if random.random() < 0.15 else cn.safe_email(first, last),
            "phone": None if random.random() < 0.05 else _locale_phone(locale),
            "address": loc_fake.street_address(),
            "city": loc_fake.city(),
            "state": _locale_region(locale, loc_fake),
            "zip": _locale_postal(locale, loc_fake),
            "preferred_language": _weighted(pack["languages"]),
            "deceased_flag": random.random() < 0.03,
        })

    # ---- encounters (linked to patient pool) --------------------------------
    encounters = []
    enc_seq = 0
    for p in patients:
        # encounters must fall within the patient's lifetime (pediatric-safe):
        # bound the total look-back (days+hours+minutes) by seconds since birth
        dob_dt = datetime.combine(date.fromisoformat(p["dob"]), datetime.min.time())
        alive_seconds = max(3600, int((datetime.now() - dob_dt).total_seconds()))
        for _ in range(_weighted(encounters_per_patient)):
            enc_seq += 1
            enc_type = _weighted(ENCOUNTER_TYPES)
            admit = datetime.now() - timedelta(seconds=random.uniform(3600, alive_seconds))
            lo, hi = LOS_HOURS[enc_type]
            discharge = (admit + timedelta(hours=random.randint(lo, hi))
                         if random.random() > 0.05 else None)
            encounters.append({
                "encounter_id": f"ENC-{enc_seq:08d}",
                "patient_id": p["patient_id"],
                "encounter_type": enc_type,
                "admit_datetime": admit.isoformat(timespec="minutes"),
                "discharge_datetime": discharge.isoformat(timespec="minutes") if discharge else None,
                "department": random.choice(DEPARTMENTS),
                "attending_provider_id": random.choice(providers)["provider_id"],
                "disposition": _weighted(DISPOSITIONS) if discharge else None,
                "_admit_dt": admit,
                "_discharge_dt": discharge,
            })

    # ---- diagnoses (linked to encounters) -----------------------------------
    diagnoses = []
    dx_seq = 0
    enc_principal = {}   # encounter_id -> principal condition name (for notes/labs/FHIR)
    enc_conditions = {}  # encounter_id -> [condition names]
    enc_dx_onset = {}    # (encounter_id, condition) -> onset date or None
    for e in encounters:
        n_dx = random.choices([1, 2, 3], weights=[0.55, 0.30, 0.15])[0]
        chosen = random.sample(list(CONDITIONS.keys()), k=min(n_dx, len(CONDITIONS)))
        enc_conditions[e["encounter_id"]] = chosen
        for j, cond in enumerate(chosen):
            dx_seq += 1
            onset = (e["_admit_dt"] - timedelta(days=random.randint(1, 1825))).date() if random.random() > 0.2 else None
            enc_dx_onset[(e["encounter_id"], cond)] = onset
            diagnoses.append({
                "diagnosis_id": dx_seq,
                "encounter_id": e["encounter_id"],
                "icd10_code": CONDITIONS[cond]["icd10"],
                "description": cond,
                "dx_type": "Principal" if j == 0 else "Secondary",
                "onset_date": onset.isoformat() if onset else None,
            })
            if j == 0:
                enc_principal[e["encounter_id"]] = cond

    # ---- medications (correlated with diagnoses, temporally consistent) ------
    # Each med belongs to one of the encounter's conditions; start_date is on or
    # after that diagnosis's onset date, and on/before the admit date.
    medications = []
    med_seq = 0
    prov_by_id = {pr["provider_id"]: pr for pr in providers}
    for e in encounters:
        for cond in enc_conditions[e["encounter_id"]]:
            for med in random.sample(CONDITIONS[cond]["meds"],
                                     k=random.choices([1, 1, 2], weights=[0.5, 0.3, 0.2])[0]):
                med_seq += 1
                onset = enc_dx_onset.get((e["encounter_id"], cond))
                # a medication string may be shared by several conditions
                # (e.g., sertraline: MDD + GAD) — never start it before the
                # earliest KNOWN onset among the conditions that share it
                shared_known = [
                    enc_dx_onset[(e["encounter_id"], c)]
                    for c in enc_conditions[e["encounter_id"]]
                    if med in CONDITIONS[c]["meds"]
                    and enc_dx_onset.get((e["encounter_id"], c))
                ]
                earliest = (min(shared_known) if shared_known
                            else (onset or (e["_admit_dt"] - timedelta(days=900)).date()))
                latest = min(e["_admit_dt"].date(), date.today())
                if earliest > latest:
                    earliest = latest
                span = max(1, (latest - earliest).days)
                start = earliest + timedelta(days=random.randint(0, span))
                active = random.random() < 0.65
                end = None if active else start + timedelta(days=random.randint(30, 500))
                if end and end > date.today():
                    end = date.today()
                medications.append({
                    "med_id": med_seq,
                    "encounter_id": e["encounter_id"],
                    "patient_id": e["patient_id"],
                    "medication": med,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat() if end else None,
                    "status": "Active" if active else
                              random.choice(["Discontinued", "Completed"]),
                    "prescriber_id": e["attending_provider_id"],
                })

    # ---- lab results (condition-correlated when possible) --------------------
    labs = []
    lab_seq = 0
    lab_defs_by_loinc = {d[0]: d for d in LAB_DEFS}
    for e in encounters:
        n_labs = random.choices([0, 1, 2, 3], weights=[0.25, 0.40, 0.25, 0.10])[0]
        # condition-relevant labs first (values biased to the dx), then filler
        relevant = []
        for cond in enc_conditions[e["encounter_id"]]:
            relevant.extend(CONDITION_LABS.get(cond, []))
        picks = []
        if relevant:
            k = min(n_labs, len(relevant))
            picks = [("c", t) for t in random.sample(relevant, k=k)]
        for _ in range(n_labs - len(picks)):
            picks.append(("g", random.choice(LAB_DEFS)))

        for kind, pick in picks:
            lab_seq += 1
            if kind == "c":  # condition lab with bias range
                loinc, name, unit, ref_lo, ref_hi, bias_lo, bias_hi = pick
                # 65% of the time the value lands in the condition-biased range
                if random.random() < 0.65:
                    value = round(random.uniform(bias_lo, bias_hi), 2)
                else:
                    value = round(random.uniform(ref_lo, ref_hi), 2)
            else:            # generic LAB_DEF tuple
                loinc, name, unit, ref_lo, ref_hi, abs_lo, abs_hi = pick
                if random.random() < 0.10:
                    value = round(random.uniform(abs_lo, ref_lo) if random.random() < 0.5
                                  else random.uniform(ref_hi, abs_hi), 2)
                else:
                    value = round(random.uniform(ref_lo, ref_hi), 2)
            if random.random() < 0.05:
                value = None
            flag = "N"
            if value is not None:
                if value < ref_lo:
                    flag = "LL" if value < ref_lo * 0.7 else "L"
                elif value > ref_hi:
                    flag = "HH" if value > ref_hi * 1.3 else "H"
            window_end = e["_discharge_dt"] or (e["_admit_dt"] + timedelta(hours=4))
            window_hours = max(1, int((window_end - e["_admit_dt"]).total_seconds() // 3600))
            result_dt = e["_admit_dt"] + timedelta(hours=random.randint(0, window_hours))
            labs.append({
                "lab_id": lab_seq,
                "encounter_id": e["encounter_id"],
                "loinc_code": loinc,
                "test_name": name,
                "value": value,
                "unit": unit,
                "reference_range": f"{ref_lo}-{ref_hi}",
                "abnormal_flag": flag if value is not None else None,
                "result_datetime": result_dt.isoformat(timespec="minutes"),
            })

    # ---- notes (identity + dx + timeline match the cohort) -------------------
    notes = []
    note_seq = 0
    pat_by_id = {p["patient_id"]: p for p in patients}
    prov_by_id = {pr["provider_id"]: pr for pr in providers}
    if with_notes:
        for e in encounters:
            if random.random() > note_probability:
                continue
            p = pat_by_id[e["patient_id"]]
            if _age_at(p["dob"], e["_admit_dt"]) < 18:
                continue  # narrative templates are adult-oriented
            note_seq += 1

            provider = prov_by_id[e["attending_provider_id"]]
            principal = enc_principal.get(e["encounter_id"])
            if principal is None:
                principal = random.choice(list(CONDITIONS.keys()))
            enc_conds = enc_conditions[e["encounter_id"]]
            secondary = enc_conds[1] if len(enc_conds) > 1 else None

            window_end = e["_discharge_dt"] or (e["_admit_dt"] + timedelta(hours=2))
            # keep notes at least one minute before discharge so minute-level
            # timestamp truncation can never place them after the encounter
            span = max(0, int((window_end - e["_admit_dt"]).total_seconds()) - 60)
            service_dt = e["_admit_dt"] + timedelta(seconds=random.randint(0, span))

            note_type = random.choice(cn.NOTE_TYPES)
            # behavioral-health notes only when the encounter carries a BH dx
            if note_type == "behavioral_health_note" and not (
                    set(enc_conditions[e["encounter_id"]]) & cn.BH_CONDITIONS):
                note_type = random.choice([t for t in cn.NOTE_TYPES
                                           if t != "behavioral_health_note"])
            dictation = random.random() < dictation_ratio and note_type not in cn.NON_DICTATABLE

            ctx = cn.make_context(
                fake, note_seq,
                # real cohort identity
                patient_id=p["patient_id"],
                first=p["first_name"], last=p["last_name"],
                name=f'{p["first_name"]} {p["last_name"]}',
                mrn=p["mrn"],
                dob=date.fromisoformat(p["dob"]),
                gender=p["gender"].lower() if p["gender"] in ("Female", "Male") else "female",
                ssn=p["ssn"] or _safe_ssn(),
                phone=p["phone"] or _safe_phone(),
                email=p["email"] or cn.safe_email(p["first_name"], p["last_name"]),
                address=p["address"], city=p["city"], state=p["state"], zip=p["zip"],
                # real encounter + provider
                encounter_id=e["encounter_id"],
                department=e["department"],
                encounter_type=e["encounter_type"],
                service_datetime=service_dt,
                admit_date=e["_admit_dt"].strftime("%m/%d/%Y"),
                discharge_date=window_end.strftime("%m/%d/%Y"),
                provider=provider["display"],
                provider_short=provider["display_short"],
                npi=provider["npi"],
                # the encounter's actual principal + secondary diagnoses
                primary=principal,
                primary_detail=CONDITIONS[principal],
                secondary=secondary,
            )
            text, spans = cn.build_note(ctx, note_type, dictation=dictation)

            notes.append({
                "note_id": f"NOTE-{note_seq:06d}",
                "patient_id": p["patient_id"],
                "patient_name": ctx["name"],
                "mrn": p["mrn"],
                "encounter_id": e["encounter_id"],
                "note_type": note_type + ("_dictation" if dictation else ""),
                "author": provider["display"],
                "author_npi": provider["npi"],
                "service_datetime": service_dt.isoformat(timespec="minutes"),
                # realism parity with standalone clinical_notes.py
                "department": None if random.random() < 0.15 else e["department"],
                "dictation_flag": dictation,
                "transcription_status": random.choices(
                    ["Signed", "Transcribed", "Draft", "Pending review"],
                    weights=[0.6, 0.2, 0.1, 0.1])[0],
                "word_count": len(text.split()),
                "note_text": text,
                "phi_spans": json.dumps(spans, ensure_ascii=False),
            })

    # drop helper columns
    for e in encounters:
        e.pop("_admit_dt", None)
        e.pop("_discharge_dt", None)

    return {
        "patients": pd.DataFrame(patients),
        "encounters": pd.DataFrame(encounters),
        "diagnoses": pd.DataFrame(diagnoses),
        "medications": pd.DataFrame(medications),
        "lab_results": pd.DataFrame(labs),
        "clinical_notes": pd.DataFrame(notes),
    }


def _age_at(dob_iso: str, at: datetime) -> int:
    dob = date.fromisoformat(dob_iso)
    return at.year - dob.year - ((at.month, at.day) < (dob.month, dob.day))


# ---------------------------------------------------------------------------
# Integrity check (also used by tests)
# ---------------------------------------------------------------------------

def check_integrity(cohort: dict) -> list:
    """Return a list of referential/timeline violations (empty = OK)."""
    errors = []
    patients = cohort["patients"]
    encounters = cohort["encounters"]
    diagnoses = cohort["diagnoses"]
    medications = cohort.get("medications")
    labs = cohort["lab_results"]
    notes = cohort["clinical_notes"]

    pat_ids = set(patients["patient_id"])
    enc_ids = set(encounters["encounter_id"])
    enc_patient = dict(zip(encounters["encounter_id"], encounters["patient_id"]))
    enc_discharge = dict(zip(encounters["encounter_id"], encounters["discharge_datetime"]))
    enc_admit = dict(zip(encounters["encounter_id"], encounters["admit_datetime"]))

    bad = [e for e in encounters["patient_id"] if e not in pat_ids]
    if bad:
        errors.append(f"{len(bad)} encounters reference unknown patients")

    bad = [d for d in diagnoses["encounter_id"] if d not in enc_ids]
    if bad:
        errors.append(f"{len(bad)} diagnoses reference unknown encounters")

    bad = [l for l in labs["encounter_id"] if l not in enc_ids]
    if bad:
        errors.append(f"{len(bad)} labs reference unknown encounters")

    if medications is not None and len(medications):
        cond_meds = {name: set(detail["meds"]) for name, detail in CONDITIONS.items()}
        for _, m in medications.iterrows():
            enc_id = m["encounter_id"]
            if enc_id not in enc_ids:
                errors.append(f'MED-{m["med_id"]} references unknown encounter')
                continue
            if m["patient_id"] != enc_patient.get(enc_id):
                errors.append(f'MED-{m["med_id"]} patient_id does not match its encounter')
            if m["start_date"] > enc_admit[enc_id][:10]:
                errors.append(f'MED-{m["med_id"]} starts after admit')
            if m["end_date"] and m["end_date"] < m["start_date"]:
                errors.append(f'MED-{m["med_id"]} ends before it starts')
            # correlation + temporal consistency against matching diagnoses
            enc_dx = diagnoses[diagnoses["encounter_id"] == enc_id]
            matching = [d for _, d in enc_dx.iterrows()
                        if m["medication"] in cond_meds.get(d["description"], set())]
            if not matching:
                errors.append(f'MED-{m["med_id"]} medication not correlated with encounter dx')
            else:
                onsets = [d["onset_date"] for d in matching if d["onset_date"]]
                if onsets and m["start_date"] < min(onsets):
                    errors.append(f'MED-{m["med_id"]} starts before its earliest dx onset')

    for _, n in notes.iterrows():
        if n["encounter_id"] and n["encounter_id"] not in enc_ids:
            errors.append(f'{n["note_id"]} references unknown encounter')
            continue
        if n["patient_id"] != enc_patient.get(n["encounter_id"]):
            errors.append(f'{n["note_id"]} patient_id does not match its encounter')
        svc = n["service_datetime"]
        admit = encounters.loc[encounters["encounter_id"] == n["encounter_id"], "admit_datetime"].iloc[0]
        if svc < admit:
            errors.append(f'{n["note_id"]} service_datetime precedes admit')
        disc = enc_discharge.get(n["encounter_id"])
        if disc and svc > disc:
            errors.append(f'{n["note_id"]} service_datetime after discharge')

    dob_map = dict(zip(patients["patient_id"], patients["dob"]))
    for _, e in encounters.iterrows():
        if e["admit_datetime"][:10] < dob_map[e["patient_id"]]:
            errors.append(f'{e["encounter_id"]} admit precedes patient DOB')
        if e["discharge_datetime"] and e["discharge_datetime"] < e["admit_datetime"]:
            errors.append(f'{e["encounter_id"]} discharge precedes admit')

    return errors


# ---------------------------------------------------------------------------
# Dirty data mode — the things that break real pipelines
# ---------------------------------------------------------------------------

def apply_dirty_mode(cohort: dict) -> dict:
    """Degrade a clean cohort with realistic data-quality problems.

    Mutates and returns the cohort. Run AFTER check_integrity() — dirty mode
    intentionally breaks formatting consistency (not referential integrity):
    duplicate rows, mixed date formats, whitespace/casing drift, empty strings
    vs NULLs, ZIP+4 mixing, and OCR-ish character damage in note text.
    """
    import numpy as np

    patients = cohort["patients"]

    # ~1% exact duplicate patient rows (pending-merge scenarios)
    n_dup = max(1, len(patients) // 100) if len(patients) >= 20 else 0
    if n_dup:
        dups = patients.sample(n=n_dup, random_state=random.randint(0, 9999))
        cohort["patients"] = patients = pd.concat(
            [patients, dups], ignore_index=True)

    # mixed DOB formats: ISO → MM/DD/YYYY or YYYYMMDD (~8%)
    def _messy_dob(v):
        if not v or random.random() > 0.08:
            return v
        d = date.fromisoformat(v)
        return random.choice([d.strftime("%m/%d/%Y"), d.strftime("%Y%m%d")])
    patients["dob"] = patients["dob"].map(_messy_dob)

    # whitespace + casing drift on names
    def _messy_name(v):
        if not isinstance(v, str) or not v:
            return v
        r = random.random()
        if r < 0.04:
            return v + " "
        if r < 0.07:
            return " " + v
        if r < 0.11:
            return v.lower()
        return v
    for col in ("first_name", "last_name"):
        patients[col] = patients[col].map(_messy_name)

    # ZIP+4 for ~6% (US-style postcodes only)
    def _messy_zip(v):
        if isinstance(v, str) and v.isdigit() and len(v) == 5 and random.random() < 0.35:
            return f"{v}-{random.randint(1000, 9999)}"
        return v
    patients["zip"] = patients["zip"].map(_messy_zip)

    # empty strings instead of NULL for a few phones
    ph = patients["phone"]
    mask = ph.isna() & (np.random.rand(len(ph)) < 0.4)
    patients.loc[mask, "phone"] = ""

    # mixed admit formats in encounters (~6%)
    enc = cohort["encounters"]
    def _messy_ts(v):
        if not v or random.random() > 0.06:
            return v
        d = datetime.fromisoformat(v)
        return d.strftime("%m/%d/%Y %H:%M")
    enc["admit_datetime"] = enc["admit_datetime"].map(_messy_ts)

    # OCR-ish damage in ~6% of notes (rn→m, cl→d, ii→u, stray spacing)
    notes = cohort["clinical_notes"]
    _OCR_SUBS = [("rn", "m"), ("cl", "d"), ("ii", "u"), ("tt", "t")]
    def _ocr_damage(text):
        if not isinstance(text, str) or random.random() > 0.06:
            return text
        sub = random.choice(_OCR_SUBS)
        words = text.split(" ")
        hit = False
        for i, w in enumerate(words):
            if len(w) > 3 and sub[0] in w and random.random() < 0.25:
                words[i] = w.replace(sub[0], sub[1], 1)
                hit = True
        return " ".join(words) if hit else text
    notes["note_text"] = notes["note_text"].map(_ocr_damage)

    return cohort


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def build_manifest(args, cohort: dict, extra: dict = None) -> dict:
    versions = {}
    for mod in (pd, Faker):
        versions[mod.__name__.split(".")[0]] = getattr(mod, "__version__", "unknown")
    manifest = {
        "_meta": {
            "generated_by": "synth-data-gen clinical_bundle",
            "synthetic": True,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "seed": args.seed,
            "format": args.format,
            "n_patients_requested": args.rows,
            "dictation_ratio": args.dictation_ratio,
            "locale": getattr(args, "locale", "us"),
            "dirty_mode": bool(getattr(args, "dirty", False)),
            "versions": versions,
        },
        "tables": {name: len(df) for name, df in cohort.items()},
    }
    if extra:
        manifest.update(extra)
    return manifest


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def to_csv(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    buf.write("# Generated by synth-data-gen clinical_bundle | All data is fictional\n")
    df.to_csv(buf, index=False)
    return buf.getvalue()


def to_json(df: pd.DataFrame) -> str:
    records = json.loads(df.to_json(orient="records", date_format="iso"))
    return json.dumps(
        {"_meta": {"generated_by": "synth-data-gen clinical_bundle", "synthetic": True,
                   "record_count": len(records)},
         "data": records},
        indent=2, ensure_ascii=False)


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


def ground_truth_document(cohort: dict, manifest: dict) -> dict:
    doc = dict(manifest)
    doc["notes"] = {
        row["note_id"]: {"note_type": row["note_type"],
                         "phi_spans": json.loads(row["phi_spans"])}
        for _, row in cohort["clinical_notes"].iterrows()
    }
    return doc


# ---------------------------------------------------------------------------
# Inline validator (same checks as the rest of the repo)
# ---------------------------------------------------------------------------

_REAL_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "mail.com", "protonmail.com", "live.com", "msn.com",
}
_SAFED = {"example.com", "example.org", "example.net", "test.invalid", "example.edu"}
_SAFE_TLDS = (".example", ".invalid", ".test", ".localhost")


def _safe_domain(d: str) -> bool:
    """Exact reserved domains, reserved TLDs, and their subdomains are safe."""
    d = d.lower()
    return (d in _SAFED
            or any(d.endswith(t) for t in _SAFE_TLDS)
            or any(d.endswith("." + s) for s in _SAFED))
_SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@([\w-]+\.[\w.-]+)\b")
_PHONE_RE = re.compile(r"\b(\d{3})[-.)]?\s*(\d{3})[-.]\s*(\d{4})\b")


def validate(text: str) -> dict:
    results = {"critical": [], "warnings": [], "info": []}
    safe_ssns = 0
    for area, _, _ in _SSN_RE.findall(text):
        if int(area) in range(1, 900):
            results["critical"].append(f"Real-range SSN area: {area}")
        else:
            safe_ssns += 1
    if safe_ssns:
        results["info"].append(f"{safe_ssns} SSN(s) in safe range (987-65-xxxx)")
    for domain in _EMAIL_RE.findall(text):
        d = domain.lower()
        if d in _REAL_EMAIL_DOMAINS:
            results["critical"].append(f"Real email domain: @{d}")
        elif not _safe_domain(d):
            results["warnings"].append(f"Unrecognized email domain: @{d}")
    for _, exch, num in _PHONE_RE.findall(text):
        if not (exch == "555" and num.startswith("01")):
            results["critical"].append(f"Phone outside safe range: {exch}-{num}")
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _iter_serialized(args, cohort):
    """Yield (filename, content) for every output file (manifest excluded)."""
    if args.format in ("csv", "json", "sql"):
        for name in TABLE_ORDER:
            df = cohort[name]
            if len(df) == 0:
                continue
            content = {"csv": to_csv, "json": to_json}[args.format](df) \
                if args.format in ("csv", "json") else to_sql(df, name)
            yield f"synthetic_{name}.{args.format}", content
    elif args.format == "fhir":
        from fhir_export import cohort_to_bundles
        for fname, bundle in cohort_to_bundles(cohort):
            yield fname, json.dumps(bundle, indent=2, ensure_ascii=False)
    elif args.format == "hl7":
        from hl7_export import cohort_to_hl7_messages
        for fname, text in cohort_to_hl7_messages(cohort):
            yield fname, text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a referentially-linked synthetic clinical dataset "
                    "(patients → encounters → diagnoses/labs/notes).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-n", "--rows", type=int, default=100,
                        help="Number of patients (default: 100)")
    parser.add_argument("-s", "--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("-f", "--format", choices=["csv", "json", "sql", "fhir", "hl7"],
                        default="csv", help="Output format (default: csv)")
    parser.add_argument("-o", "--output", default="./synthetic_output",
                        help="Output directory (default: ./synthetic_output)")
    parser.add_argument("--no-notes", action="store_true", help="Skip note generation")
    parser.add_argument("--dictation-ratio", type=float, default=0.35,
                        help="Fraction of notes rendered as raw dictation (default: 0.35)")
    parser.add_argument("--locale", choices=list(LOCALES.keys()), default="us",
                        help="Locale pack: localized names/addresses/phones with "
                             "region-appropriate fictional ranges (default: us)")
    parser.add_argument("--dirty", action="store_true",
                        help="Apply realistic data-quality problems (duplicate rows, mixed "
                             "date formats, whitespace/casing drift, OCR-ish note damage)")
    parser.add_argument("--zip", action="store_true",
                        help="Also write synthetic_clinical_bundle.zip with all files")
    parser.add_argument("--validate", action="store_true",
                        help="Run PII/PHI validation after generation")
    args = parser.parse_args()

    random.seed(args.seed)
    Faker.seed(args.seed)
    fake = Faker()

    print(f"Generating clinical cohort: {args.rows} patients (seed={args.seed}, "
          f"locale={args.locale})")
    cohort = generate_clinical_cohort(
        args.rows, fake,
        dictation_ratio=args.dictation_ratio,
        with_notes=not args.no_notes,
        locale=args.locale)

    integrity = check_integrity(cohort)
    for err in integrity:
        print(f"  INTEGRITY: {err}", file=sys.stderr)

    if args.dirty:
        apply_dirty_mode(cohort)
        print("  Dirty data mode applied — formats intentionally inconsistent "
              "(integrity was verified on clean data first).")

    manifest = build_manifest(args, cohort)
    print("  " + " | ".join(f"{k}: {len(v)} rows" for k, v in cohort.items()))

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = list(_iter_serialized(args, cohort))
    files.append(("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False)))
    files.append(("clinical_notes_ground_truth.json",
                  json.dumps(ground_truth_document(cohort, manifest), indent=2, ensure_ascii=False)))

    exit_code = 1 if integrity else 0
    for fname, content in files:
        path = out_dir / fname
        path.write_text(content, encoding="utf-8")
        size = f"{len(content) / 1024:.1f} KB"
        print(f"  Wrote {size:>10} → {path.name}")
        if args.validate and not fname.endswith(".json"):
            vr = validate(content)
            for msg in vr["critical"]:
                print(f"    CRITICAL: {msg}", file=sys.stderr)
                exit_code = max(exit_code, 2)
            for msg in vr["warnings"]:
                print(f"    WARNING:  {msg}", file=sys.stderr)
                exit_code = max(exit_code, 1)
            for msg in vr["info"]:
                print(f"    INFO:     {msg}")

    if args.zip:
        zip_path = out_dir / "synthetic_clinical_bundle.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, content in files:
                zf.writestr(fname, content)
        print(f"  Wrote bundle  → {zip_path.name} ({zip_path.stat().st_size / 1024:.1f} KB)")

    if args.validate and exit_code == 0:
        print("Validation passed — no real PII/PHI detected.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
