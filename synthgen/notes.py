#!/usr/bin/env python3
"""
Clinical Notes & Dictation Generator
=====================================
Generates synthetic physician notes — transcribed notes AND raw dictation
transcripts — with embedded PHI. Every identifier stays in a reserved/fictional
range (SSN 987-65-xxxx, phone 555-01xx, email @example.com, MRN-224xxxx), so the
output is safe for dev/test while remaining realistic enough to exercise
de-identification, transcription, and NLP pipelines.

Each note ships with ground-truth PHI spans (type + character offsets) so you can
measure de-identification recall/precision, not just eyeball it.

Note types:
    progress_note, history_physical, discharge_summary, ed_note,
    telehealth_note, procedure_note, dictation_transcript

Run:
    python clinical_notes.py -n 20 --validate
    python clinical_notes.py -n 50 -t dictation_transcript -f txt --ground-truth
"""

import argparse
import io
import json
import random
import re
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
from faker import Faker

from .clock import clock

# ---------------------------------------------------------------------------
# Constants — must stay in safe/fictional ranges (matches the rest of the repo)
# ---------------------------------------------------------------------------

SAFE_SSN_PREFIX = "987-65"
SAFE_EMAIL_DOMAINS = ["example.com", "example.org", "test.invalid"]
SAFE_PHONE_PREFIX = "555-01"

NOTE_TYPES = [
    "progress_note",
    "history_physical",
    "discharge_summary",
    "ed_note",
    "telehealth_note",
    "procedure_note",
    "radiology_report",
    "behavioral_health_note",
    "patient_portal_message",
    "phone_call_transcript",
]

# note types that are never rendered as dictation (already audio→text or patient-written)
NON_DICTATABLE = {"patient_portal_message", "phone_call_transcript"}

# note type label used inside the note header
NOTE_LABELS = {
    "progress_note": "PROGRESS NOTE",
    "history_physical": "HISTORY & PHYSICAL",
    "discharge_summary": "DISCHARGE SUMMARY",
    "ed_note": "EMERGENCY DEPARTMENT NOTE",
    "telehealth_note": "TELEHEALTH NOTE",
    "procedure_note": "PROCEDURE NOTE",
    "radiology_report": "RADIOLOGY REPORT",
    "behavioral_health_note": "BEHAVIORAL HEALTH NOTE",
    "patient_portal_message": "PATIENT PORTAL MESSAGE",
    "phone_call_transcript": "INBOUND CALL TRANSCRIPT",
}

# Correlated clinical content: dx -> icd10, meds, relevant labs, symptoms.
# This keeps medications/labs consistent with the diagnosis in each note.
CONDITIONS = {
    "Type 2 diabetes mellitus": {
        "icd10": "E11.9",
        "meds": ["metformin 500mg twice daily", "glipizide 5mg daily", "insulin glargine 12 units at bedtime"],
        "labs": [("HbA1c", "8.4", "%"), ("fasting glucose", "148", "mg/dL")],
        "symptoms": ["intermittent polyuria", "mild fatigue", "occasional blurred vision"],
        "followup": "endocrinology in 3 months",
    },
    "Essential hypertension": {
        "icd10": "I10",
        "meds": ["lisinopril 10mg daily", "amlodipine 5mg daily", "losartan 50mg daily"],
        "labs": [("basic metabolic panel", "within normal limits", "")],
        "symptoms": ["intermittent headaches", "no chest pain or dyspnea"],
        "followup": "BP check with nursing in 2 weeks",
    },
    "Major depressive disorder": {
        "icd10": "F32.1",
        "meds": ["sertraline 50mg daily", "bupropion XL 150mg daily"],
        "labs": [("PHQ-9 score", "14", "")],
        "symptoms": ["depressed mood", "reduced interest in usual activities", "difficulty sleeping"],
        "followup": "behavioral health follow-up in 4 weeks",
    },
    "Generalized anxiety disorder": {
        "icd10": "F41.1",
        "meds": ["escitalopram 10mg daily", "sertraline 50mg daily", "buspirone 10mg twice daily"],
        "labs": [("GAD-7 score", "12", "")],
        "symptoms": ["excessive worry most days", "restlessness", "difficulty concentrating"],
        "followup": "behavioral health follow-up in 6 weeks",
    },
    "Alcohol use disorder, in sustained remission": {
        "icd10": "F10.21",
        "meds": ["naltrexone 50mg daily", "acamprosate 333mg three times daily"],
        "labs": [("liver function panel", "within normal limits", "")],
        "symptoms": ["denies current alcohol use", "attending weekly support meetings"],
        "followup": "monthly recovery check-ins",
    },
    "Community-acquired pneumonia": {
        "icd10": "J18.9",
        "meds": ["azithromycin 250mg daily", "amoxicillin 500mg three times daily"],
        "labs": [("WBC", "13.8", "10*3/uL")],
        "symptoms": ["productive cough", "low-grade fever", "pleuritic chest pain"],
        "followup": "repeat chest X-ray in 6 weeks",
    },
    "Primary osteoarthritis of the right knee": {
        "icd10": "M17.11",
        "meds": ["ibuprofen 400mg as needed", "acetaminophen 500mg as needed"],
        "labs": [],
        "symptoms": ["right knee pain with ambulation", "morning stiffness lasting less than 30 minutes"],
        "followup": "orthopedics if symptoms progress",
    },
    "Atrial fibrillation": {
        "icd10": "I48.91",
        "meds": ["apixaban 5mg twice daily", "metoprolol 25mg twice daily"],
        "labs": [("TSH", "2.1", "mIU/L")],
        "symptoms": ["palpitations", "exercise intolerance"],
        "followup": "cardiology in 6 weeks with repeat ECG",
    },
}

# Conditions treated as behavioral-health / SUD sensitive (42 CFR Part 2 testing)
BH_CONDITIONS = {"Major depressive disorder", "Generalized anxiety disorder",
                 "Alcohol use disorder, in sustained remission"}

# Non-English patient quotes (interpreter / family translator scenes)
SPANISH_SNIPPETS = [
    "Mi espalda me duele mucho",
    "No puedo dormir por la noche",
    "Me duele la cabeza desde la semana pasada",
    "Tengo miedo de tomar tanta medicina",
]

ALLERGIES = [
    ("penicillin", "hives"),
    ("sulfa drugs", "rash"),
    ("no known drug allergies", None),
    ("latex", "contact dermatitis"),
]

# --- safe-range identifier helpers ------------------------------------------

def safe_ssn() -> str:
    return f"{SAFE_SSN_PREFIX}-{random.randint(0, 9999):04d}"


def safe_phone() -> str:
    return f"{SAFE_PHONE_PREFIX}{random.randint(0, 99):02d}"


def safe_email(first: str, last: str) -> str:
    f = re.sub(r"[^a-zA-Z0-9]", "", first.lower())
    l = re.sub(r"[^a-zA-Z0-9]", "", last.lower())
    return f"{f}.{l}@{random.choice(SAFE_EMAIL_DOMAINS)}"


def safe_npi() -> str:
    return f"9{random.randint(100000000, 999999999)}"


# ---------------------------------------------------------------------------
# Ground-truth span tracking
# ---------------------------------------------------------------------------

class NoteBuilder:
    """Assemble narrative text from segments while recording PHI spans.

    A segment is (text, phi_type) — phi_type None for non-PHI narrative.
    Rendered text is identical regardless of tracking; spans are offsets into
    the final string, ready for de-identification scoring.
    """

    def __init__(self):
        self.segments = []  # List[Tuple[str, Optional[str]]]

    def add(self, text, phi_type=None):
        if text:
            self.segments.append((text, phi_type))
        return self

    def line(self, text="", phi_type=None):
        return self.add(text + "\n" if text else "\n", phi_type)

    def blank(self):
        return self.add("\n")

    def render(self, dictation=False):
        """Return (text, spans). In dictation mode, plain segments are spoken-
        form transformed (punctuation -> spoken commands, disfluencies)."""
        parts, spans, pos = [], [], 0

        if dictation:
            parts.append("BEGIN DICTATION\n")
            pos += len(parts[-1])

        for text, phi in self.segments:
            if phi is None and dictation:
                text = _spoken_form(text)
                # occasionally mark a whole phrase inaudible (ASR artifact)
                if len(text) > 30 and random.random() < 0.02:
                    text = "[inaudible]"
            parts.append(text)
            if phi:
                spans.append({"type": phi, "text": text, "start": pos, "end": pos + len(text)})
            pos += len(text)
            if dictation and phi is None and text.endswith(". "):
                fill = random.choice(["", "", "", " um ", " uh ", " er ", " ... "])
                if fill:
                    parts.append(fill)
                    pos += len(fill)

        if dictation:
            parts.append("\nEND OF DICTATION")
        return "".join(parts), spans


def _spoken_form(text: str) -> str:
    """Convert punctuation in narrative text to dictation-style spoken commands."""
    text = text.replace("Dr.", "Doctor")
    text = text.replace("\n\n", " new paragraph ")
    text = text.replace("\n", " new paragraph ")
    text = re.sub(r"\.\s", " period ", text)
    text = re.sub(r"\.$", " period", text)
    text = re.sub(r",\s", " comma ", text)
    text = re.sub(r":\s", " colon ", text)
    text = text.replace(";", " semicolon")
    return text


# ---------------------------------------------------------------------------
# Context construction (correlated clinical facts for one note)
# ---------------------------------------------------------------------------

def _make_context(i: int, fake: Faker) -> dict:
    first, last = fake.first_name(), fake.last_name()
    age = random.randint(18, 92)
    gender = random.choices(["female", "male"], weights=[0.51, 0.49])[0]
    conditions = random.sample(list(CONDITIONS.keys()), k=random.choices([1, 2], weights=[0.7, 0.3])[0])
    primary, secondary = conditions[0], conditions[1] if len(conditions) > 1 else None

    svc = clock.now() - timedelta(days=random.randint(1, 730), hours=random.randint(0, 23))
    allergy, allergy_rx = random.choice(ALLERGIES)

    contact_rel = random.choice(["son", "daughter", "spouse", "sister", "brother", "neighbor"])
    if contact_rel in ("son", "brother"):
        contact_first = fake.first_name_male()
    elif contact_rel in ("daughter", "sister"):
        contact_first = fake.first_name_female()
    else:
        contact_first = fake.first_name()

    return {
        "note_id": f"NOTE-{i + 1:06d}",
        "patient_id": f"SYN-{random.randint(1, 5000):06d}",
        "first": first, "last": last,
        "name": f"{first} {last}",
        "mrn": f"MRN-{2240001 + random.randint(0, 9000)}",
        "dob": (clock.today() - timedelta(days=age * 365 + random.randint(0, 364))),
        "age": age,
        "gender": gender,
        "ssn": safe_ssn(),
        "phone": safe_phone(),
        "email": safe_email(first, last),
        "address": fake.street_address(),
        "city": fake.city(), "state": fake.state_abbr(), "zip": fake.zipcode(),
        "provider": f"Dr. {fake.first_name()} {fake.last_name()}, MD",
        "provider_short": f"Dr. {fake.last_name()}",
        "npi": safe_npi(),
        "encounter_id": f"ENC-{random.randint(1, 99999999):08d}",
        "department": random.choice(["Cardiology", "Primary Care", "Emergency", "Internal Medicine", "Endocrinology", "Orthopedics"]),
        "encounter_type": random.choices(["Outpatient", "Inpatient", "ED", "Telehealth"], weights=[0.55, 0.2, 0.15, 0.1])[0],
        "service_datetime": svc,
        "primary": primary,
        "primary_detail": CONDITIONS[primary],
        "secondary": secondary,
        "allergy": allergy, "allergy_rx": allergy_rx,
        "bp": f"{random.randint(105, 165)}/{random.randint(65, 100)}",
        "hr": random.randint(58, 105),
        "rr": random.randint(12, 22),
        "temp": f"9{random.randint(7, 9)}.{random.randint(0, 9)}",
        "spo2": random.randint(92, 100),
        "weight_lbs": random.randint(110, 290),
        "contact_name": f"{contact_first} {last}",
        "contact_rel": contact_rel,
        "contact_phone": safe_phone(),
        "admit_date": (svc - timedelta(days=random.randint(1, 10))).strftime("%m/%d/%Y"),
        "discharge_date": svc.strftime("%m/%d/%Y"),
    }


# --- public API for composing notes from external cohorts (clinical_bundle) ---

def make_context(fake: Faker, i: int = 0, **overrides) -> dict:
    """Build a note context with random defaults, then apply overrides.

    Used by clinical_bundle.py to keep note identity/diagnosis/dates consistent
    with the linked cohort. When `dob` is overridden, `age` is recomputed from it
    unless explicitly provided.
    """
    ctx = _make_context(i, fake)
    if "dob" in overrides and "age" not in overrides and "service_datetime" in overrides:
        svc = overrides["service_datetime"]
        dob = overrides["dob"]
        overrides["age"] = svc.year - dob.year - (
            (svc.month, svc.day) < (dob.month, dob.day))
    ctx.update(overrides)
    return ctx


def build_note(ctx: dict, note_type: str, dictation: bool = False):
    """Render a note for a pre-built context dict. Returns (text, spans)."""
    if note_type not in _BUILDERS:
        note_type = random.choice(NOTE_TYPES)
    builder = _BUILDERS[note_type](ctx)
    return builder.render(dictation=dictation)


# ---------------------------------------------------------------------------
# Section builders (shared across note types)
# ---------------------------------------------------------------------------

def _header(b, ctx, label):
    b.line(label)
    b.add("Patient: ").add(ctx["name"], "PATIENT")
    b.add("   MRN: ").add(ctx["mrn"], "MRN").line()
    b.add("DOB: ").add(ctx["dob"].strftime("%m/%d/%Y"), "DOB")
    b.add(f'  ({ctx["age"]} y.o. {ctx["gender"]})   Encounter: ')
    b.add(ctx["encounter_id"], "ENCOUNTER").line()
    b.add("Provider: ").add(ctx["provider"], "PROVIDER")
    b.add("   NPI: ").add(ctx["npi"], "NPI").line()
    b.add("Service Date: ").add(ctx["service_datetime"].strftime("%m/%d/%Y"), "DATE").line()
    if random.random() < 0.6:
        b.add("Address: ").add(f'{ctx["address"]}, {ctx["city"]}, {ctx["state"]} {ctx["zip"]}', "ADDRESS").line()
    b.line()


def _subjective(b, ctx):
    d = ctx["primary_detail"]
    b.line("S:")
    b.add(f'Patient is a {ctx["age"]}-year-old {ctx["gender"]} presenting for ')
    b.add("follow-up" if ctx["encounter_type"] in ("Outpatient", "Telehealth") else "evaluation").add(" of ")
    b.add(f'{ctx["primary"].lower()}').add(". ")
    b.add(f'Patient reports {random.choice(d["symptoms"])}').add(". ")
    if ctx["secondary"]:
        b.add(f'History significant for {ctx["secondary"].lower()}, currently stable').add(". ")
    b.add("Denies chest pain, shortness of breath at rest, or unintended weight loss. ")
    if random.random() < 0.4:
        b.add("Social history: ")
        b.add("former smoker with 10 pack-year history" if random.random() < 0.5 else "denies tobacco, alcohol, or illicit drug use")
        b.add(". ")
    if random.random() < 0.35:
        b.add(f'Emergency contact is {ctx["contact_rel"]} ')
        b.add(ctx["contact_name"], "CONTACT")
        b.add(" at ")
        b.add(ctx["contact_phone"], "PHONE").add(". ")
    b.blank()


def _objective(b, ctx):
    b.line("O:")
    b.add(f'Vitals: BP {ctx["bp"]}, HR {ctx["hr"]}, RR {ctx["rr"]}, Temp {ctx["temp"]} C, SpO2 {ctx["spo2"]}%, Weight {ctx["weight_lbs"]} lbs. ')
    b.add("General: alert and oriented, no acute distress. ")
    b.add(random.choice([
        "Cardiovascular: regular rate and rhythm, no murmurs. ",
        "Cardiovascular: irregularly irregular rhythm consistent with known atrial fibrillation. ",
        "Cardiovascular: regular rhythm, no peripheral edema. ",
    ]))
    b.add("Lungs clear to auscultation bilaterally. ")
    labs = ctx["primary_detail"]["labs"]
    if labs:
        name, val, unit = labs[0]
        b.add(f'Recent {name} {"of " + val if val else ""} {unit}'.strip() + ". ")
    b.add(f'Allergies: {ctx["allergy"]}'
          + (f' ({ctx["allergy_rx"]})' if ctx["allergy_rx"] else "") + ". ")
    b.blank()


def _assessment(b, ctx):
    b.line("A:")
    b.add(f'1. {ctx["primary"]} (').add(ctx["primary_detail"]["icd10"], "ICD10").add(") — ")
    b.add(random.choice(["well controlled on current regimen", "improving", "mildly exacerbated, medication adjusted today", "stable, continue monitoring"])).add(". ")
    if ctx["secondary"]:
        b.add(f'2. {ctx["secondary"]} (').add(CONDITIONS[ctx["secondary"]]["icd10"], "ICD10").add(") — stable. ")
    b.blank()


def _plan(b, ctx):
    d = ctx["primary_detail"]
    b.line("P:")
    b.add("1. Continue " + random.choice(d["meds"]) + ". ")
    if len(d["meds"]) > 1:
        b.add("2. Add " + random.choice(d["meds"][1:]) + ". ")
    b.add(f'2. {d["followup"].capitalize()}. ')
    if random.random() < 0.3:
        b.add("3. Review after-hours instructions; patient to call ")
        b.add(ctx["phone"], "PHONE").add(" with concerns. ")
    if random.random() < 0.25 and ctx.get("ssn"):
        b.add("4. Insurance verified; SSN on file ")
        b.add(ctx["ssn"], "SSN").add(" matched registration records. ")
    b.add("Patient verbalized understanding and agreement with the plan. ")
    b.blank()


def _build_progress_note(ctx):
    b = NoteBuilder()
    _header(b, ctx, NOTE_LABELS["progress_note"])
    _subjective(b, ctx)
    _objective(b, ctx)
    _assessment(b, ctx)
    _plan(b, ctx)
    b.add("Electronically signed by ").add(ctx["provider"], "PROVIDER").add(".")
    return b


def _build_history_physical(ctx):
    b = NoteBuilder()
    _header(b, ctx, NOTE_LABELS["history_physical"])
    b.add("CHIEF COMPLAINT: ").add(random.choice(ctx["primary_detail"]["symptoms"])).add(". ").blank()
    b.line("HPI:")
    b.add(f'{ctx["name"]}', "PATIENT")
    b.add(f' is a {ctx["age"]}-year-old {ctx["gender"]} with a history of {ctx["primary"].lower()} ')
    b.add(f'presenting with {random.choice(ctx["primary_detail"]["symptoms"])} for ')
    b.add(f'{random.randint(2, 14)} days').add(". ")
    b.add(f'PMH: {ctx["primary"].lower()}' + (f', {ctx["secondary"].lower()}' if ctx["secondary"] else "") + ". ")
    b.add(f'Medications: {"; ".join(ctx["primary_detail"]["meds"])}. ')
    b.add(f'Allergies: {ctx["allergy"]}' + (f' ({ctx["allergy_rx"]})' if ctx["allergy_rx"] else "") + ". ").blank()
    b.line("REVIEW OF SYSTEMS: Negative except as noted in HPI. ")
    b.line("PHYSICAL EXAM:")
    b.add(f'Vitals: BP {ctx["bp"]}, HR {ctx["hr"]}, Temp {ctx["temp"]} C, SpO2 {ctx["spo2"]}%. ')
    b.add("Constitutional: no acute distress. HEENT: normocephalic, atraumatic. ")
    b.add("Cardiovascular: regular rate and rhythm. Pulmonary: clear bilaterally. ")
    b.add("Abdomen: soft, non-tender. Extremities: no edema. ").blank()
    _assessment(b, ctx)
    _plan(b, ctx)
    b.add("Electronically signed by ").add(ctx["provider"], "PROVIDER").add(".")
    return b


def _build_discharge_summary(ctx):
    b = NoteBuilder()
    _header(b, ctx, NOTE_LABELS["discharge_summary"])
    b.add("Admission Date: ").add(ctx["admit_date"], "DATE")
    b.add("   Discharge Date: ").add(ctx["discharge_date"], "DATE").line()
    b.add("Admitting Diagnosis: ").add(ctx["primary_detail"]["icd10"], "ICD10")
    b.add(f' — {ctx["primary"]}').blank()
    b.line("HOSPITAL COURSE:")
    b.add(f'Patient was admitted for {ctx["primary"].lower()} and treated with ')
    b.add(random.choice(ctx["primary_detail"]["meds"]))
    b.add(". Course was uncomplicated with progressive improvement. ")
    b.add(f'Encounter {ctx["encounter_id"]}', "ENCOUNTER")
    b.add(" includes daily progress documentation. ").blank()
    b.line("DISCHARGE MEDICATIONS:")
    for i, med in enumerate(ctx["primary_detail"]["meds"][:2], 1):
        b.add(f'{i}. {med}. ')
    b.blank()
    b.line("DISPOSITION:")
    b.add("Discharged home in stable condition with services. ")
    b.add(f'Follow-up: {ctx["primary_detail"]["followup"]}. ')
    if random.random() < 0.4:
        b.add('Appointment scheduling will call patient at ')
        b.add(ctx["phone"], "PHONE").add(". ")
    b.blank()
    b.add("Electronically signed by ").add(ctx["provider"], "PROVIDER").add(".")
    return b


def _build_ed_note(ctx):
    b = NoteBuilder()
    _header(b, ctx, NOTE_LABELS["ed_note"])
    b.add("TRIAGE: ").add(f'{ctx["age"]}-year-old {ctx["gender"]}').add(", ").add(ctx["department"]).add(" presenting via ").add(
        random.choice(["walk-in", "private vehicle", "EMS", "ambulance"])).add(". ").blank()
    b.line("ED COURSE:")
    b.add(f'Evaluated for {ctx["primary"].lower()}. ')
    b.add(f'Vitals: BP {ctx["bp"]}, HR {ctx["hr"]}, Temp {ctx["temp"]} C, SpO2 {ctx["spo2"]}%. ')
    b.add('Labs and imaging ordered under encounter ').add(ctx["encounter_id"], "ENCOUNTER").add(". ")
    b.add("IV access established, symptomatic treatment administered with improvement. ").blank()
    _assessment(b, ctx)
    b.line("DISPOSITION:")
    b.add(random.choice([
        "Discharged home in stable condition with prescriptions and return precautions. ",
        "Admitted to observation for continued management. ",
        "Admitted to floor bed. ",
    ]))
    if random.random() < 0.3:
        b.add("Prescription sent to patient pharmacy; confirm at ")
        b.add(ctx["phone"], "PHONE").add(". ")
    b.blank()
    b.add("Electronically signed by ").add(ctx["provider"], "PROVIDER").add(".")
    return b


def _build_telehealth_note(ctx):
    b = NoteBuilder()
    _header(b, ctx, NOTE_LABELS["telehealth_note"])
    b.add("MODALITY: Two-way audio-video. Patient located at home in ")
    b.add(f'{ctx["city"]}, {ctx["state"]}', "ADDRESS").add(". ")
    b.add("Identity verified via two identifiers. Consent for telehealth obtained. ").blank()
    _subjective(b, ctx)
    _objective(b, ctx)
    b.add("Physical exam limited by video modality; guided self-exam performed. ").blank()
    _assessment(b, ctx)
    _plan(b, ctx)
    b.add("Technical issues: none. Encounter billed as telehealth E/M. ")
    b.add("Electronically signed by ").add(ctx["provider"], "PROVIDER").add(".")
    return b


def _build_procedure_note(ctx):
    b = NoteBuilder()
    _header(b, ctx, NOTE_LABELS["procedure_note"])
    proc = random.choice([
        ("Left knee intra-articular steroid injection", "80 mg methylprednisolone", "3 mL"),
        ("Ultrasound-guided right internal jugular line placement", "triple-lumen catheter", "n/a"),
        ("Lumbar puncture", "20-gauge needle", "12 mL CSF"),
        ("Incision and drainage of right forearm abscess", "scalpel #11", "minimal"),
    ])
    b.add("PROCEDURE: ").add(proc[0]).add(". ").blank()
    b.line("CONSENT: Risks, benefits, and alternatives discussed; verbal and written consent obtained. ")
    b.line("ANESTHESIA: 1% lidocaine without epinephrine. ")
    b.line("DESCRIPTION:")
    b.add("The patient was positioned and prepped in sterile fashion. ")
    b.add(f'Using sterile technique, {proc[1]} was utilized. ')
    b.add("The procedure was tolerated well without complications. ")
    b.add(f'EBL: minimal. Specimen: {proc[2]}').add(". ").blank()
    b.line("CONDITION: Stable, transported to recovery in stable condition. ")
    b.add("Electronically signed by ").add(ctx["provider"], "PROVIDER").add(".")
    return b


# Condition -> (exam, findings, impression) for radiology correlation
RADIOLOGY_BY_CONDITION = {
    "Community-acquired pneumonia": (
        "Chest X-ray, 2 views",
        "There is a patchy right lower lobe opacity with air bronchograms. No pleural effusion or pneumothorax. Cardiomediastinal silhouette is normal.",
        "1. Patchy right lower lobe infiltrate, consistent with community-acquired pneumonia."),
    "Primary osteoarthritis of the right knee": (
        "Right knee X-ray, 3 views",
        "Medial joint space narrowing with subchondral sclerosis and osteophyte formation. No acute fracture or dislocation. Soft tissues unremarkable.",
        "1. Medial compartment osteoarthritis of the right knee, moderate."),
    "Atrial fibrillation": (
        "Chest X-ray, 2 views",
        "Mild cardiomegaly. No pulmonary edema, effusion, or focal consolidation. Bones and soft tissues unremarkable.",
        "1. Mild cardiomegaly. 2. No evidence of pulmonary edema."),
    "Type 2 diabetes mellitus": (
        "Chest X-ray, 2 views",
        "Lungs are clear bilaterally. No acute cardiopulmonary process.",
        "1. No acute cardiopulmonary finding."),
    "Essential hypertension": (
        "Chest X-ray, 2 views",
        "Normal heart size. Lungs clear. No acute abnormality.",
        "1. No acute cardiopulmonary finding."),
    "Major depressive disorder": (
        "Chest X-ray, 2 views",
        "Lungs clear bilaterally, obtained to rule out organic etiology. No acute abnormality.",
        "1. No acute cardiopulmonary finding."),
    "Generalized anxiety disorder": (
        "Chest X-ray, 2 views",
        "Unremarkable examination. No acute abnormality.",
        "1. No acute cardiopulmonary finding."),
    "Alcohol use disorder, in sustained remission": (
        "Chest X-ray, 2 views",
        "Lungs clear. No acute abnormality. No radiographic evidence of complication.",
        "1. No acute cardiopulmonary finding."),
}


def _build_radiology_report(ctx):
    exam, findings, impression = RADIOLOGY_BY_CONDITION.get(
        ctx["primary"], ("Chest X-ray, 2 views",
                         "Lungs are clear bilaterally. No acute cardiopulmonary process.",
                         "1. No acute cardiopulmonary finding."))
    b = NoteBuilder()
    b.line(NOTE_LABELS["radiology_report"])
    b.add("Exam: ").add(exam).line()
    b.add("Exam Date: ").add(ctx["service_datetime"].strftime("%m/%d/%Y"), "DATE").line()
    b.add("Patient: ").add(ctx["name"], "PATIENT")
    b.add("   MRN: ").add(ctx["mrn"], "MRN").line()
    b.add("DOB: ").add(ctx["dob"].strftime("%m/%d/%Y"), "DOB")
    b.add(f'  ({ctx["age"]} y.o. {ctx["gender"]})   Accession: ')
    b.add(f'ACC-{random.randint(100000, 999999)}').line().blank()
    b.add("REFERRING PROVIDER: ").add(ctx["provider"], "PROVIDER").blank()
    b.add("INDICATION: ").add(ctx["primary"]).add(". ").blank()
    b.line("TECHNIQUE: Routine views were obtained per department protocol. ")
    b.line("COMPARISON: None available. ").blank()
    b.line("FINDINGS:")
    b.add(findings + " ").blank()
    b.line("IMPRESSION:")
    b.add(impression + ". ")
    if random.random() < 0.4:
        b.add("2. No acute abnormality. ")
    b.blank()
    b.add("Electronically signed by ").add(ctx["provider"], "PROVIDER").add(".")
    return b


def _build_behavioral_health_note(ctx):
    is_sud = ctx["primary"] == "Alcohol use disorder, in sustained remission" or \
        (ctx["secondary"] == "Alcohol use disorder, in sustained remission")
    b = NoteBuilder()
    b.line(NOTE_LABELS["behavioral_health_note"])
    if is_sud:
        b.line("*** CONFIDENTIAL — SUBSTANCE USE DISORDER RECORDS PROTECTED BY 42 CFR PART 2 ***")
        b.line("*** REDISCLOSURE PROHIBITED WITHOUT WRITTEN PATIENT CONSENT ***")
    else:
        b.line("*** CONFIDENTIAL — BEHAVIORAL HEALTH RECORD ***")
    b.line()
    b.add("Patient: ").add(ctx["name"], "PATIENT")
    b.add("   MRN: ").add(ctx["mrn"], "MRN").line()
    b.add("DOB: ").add(ctx["dob"].strftime("%m/%d/%Y"), "DOB")
    b.add(f'  ({ctx["age"]} y.o. {ctx["gender"]})   Encounter: ')
    b.add(ctx["encounter_id"], "ENCOUNTER").line()
    b.add("Clinician: ").add(ctx["provider"], "PROVIDER")
    b.add("   NPI: ").add(ctx["npi"], "NPI").line().blank()

    b.line("SUBJECTIVE:")
    b.add(f'Patient presents for follow-up of {ctx["primary"].lower()}. ')
    b.add(f'Reports {random.choice(ctx["primary_detail"]["symptoms"])}').add(". ")
    if random.random() < 0.25:
        b.add("Through an interpreter, patient states \"")
        b.add(random.choice(SPANISH_SNIPPETS))
        b.add("\" — interpreter translated for the clinician. ")
    b.add("Denies thoughts of self-harm or harm to others. "
          "Reports adequate support system and safe home environment. ").blank()

    b.line("OBJECTIVE — MENTAL STATUS EXAM:")
    b.add("Appearance: well-groomed, cooperative. Speech: normal rate and volume. ")
    b.add("Mood: \"").add(random.choice(["okay", "better than last time", "still low", "anxious"]))
    b.add(".\" Affect: congruent. Thought process: linear and goal-directed. ")
    b.add("Cognition: alert and oriented. Insight and judgment: intact. ").blank()

    b.line("ASSESSMENT:")
    b.add(f'1. {ctx["primary"]} (').add(ctx["primary_detail"]["icd10"], "ICD10").add(") — ")
    b.add(random.choice(["improving with current treatment", "stable", "partial response, regimen adjusted"])).add(". ")
    if ctx["secondary"]:
        b.add(f'2. {ctx["secondary"]} — monitored, stable. ')
    b.blank()

    b.line("PLAN:")
    b.add("1. Continue " + random.choice(ctx["primary_detail"]["meds"]) + ". ")
    b.add(f'2. {ctx["primary_detail"]["followup"].capitalize()}. ')
    b.add("3. Crisis resources reviewed; patient provided the 24/7 support line ")
    b.add(ctx["phone"], "PHONE").add(". ")
    if is_sud:
        b.add("4. Recovery program attendance verified; consent form on file per 42 CFR Part 2. ")
    b.blank()
    b.add("Electronically signed by ").add(ctx["provider"], "PROVIDER").add(".")
    return b


def _build_portal_message(ctx):
    b = NoteBuilder()
    b.line(NOTE_LABELS["patient_portal_message"])
    b.add("From: ").add(ctx["email"], "EMAIL").line()
    b.add("To: ").add("messages@clinic.example.com").line()
    b.add("Sent: ").add(ctx["service_datetime"].strftime("%m/%d/%Y %H:%M"), "DATE").line()
    b.add("Subject: ").add(random.choice([
        "question about my medicine", "follow up visit", "refill needed",
        "still not feeling great", "insurance form question"])).line()
    b.line()
    b.add("hello, this is ").add(ctx["name"], "PATIENT").add(", ")
    b.add("my date of birth is ").add(ctx["dob"].strftime("%m/%d/%Y"), "DOB").add(". ")
    b.add(f'i wanted to ask about my {random.choice(ctx["primary_detail"]["meds"])} ')
    b.add("because " + random.choice([
        "i think its making me dizzy", "i ran out last week",
        "the pharmacy said it needs approval", "ive been feeling better, do i still take it?"]) + ". ")
    if random.random() < 0.3:
        b.add("my " + ctx["contact_rel"] + " ")
        b.add(ctx["contact_name"], "CONTACT").add(" said i should message you directly. ")
    if random.random() < 0.2:
        b.add("(my daughter types these for me, she is translating) \"")
        b.add(random.choice(SPANISH_SNIPPETS)).add("\" ")
    b.add("you can call me at ").add(ctx["phone"], "PHONE")
    b.add(" or reply here. ")
    if random.random() < 0.35:
        b.add("also i moved, my new address is ")
        b.add(f'{ctx["address"]}, {ctx["city"]}, {ctx["state"]} {ctx["zip"]}', "ADDRESS").add(". ")
    b.add("thank you!")
    return b


def _build_call_transcript(ctx):
    agent = f"{random.choice(['Kelsey', 'Jordan', 'Maria', 'Sam', 'Dana'])} (Scheduling)"
    t = random.randint(0, 400)
    def ts():
        nonlocal t
        t += random.randint(5, 40)
        return f"[{t // 60:02d}:{t % 60:02d}] "
    b = NoteBuilder()
    b.line(NOTE_LABELS["phone_call_transcript"])
    b.add("Call Reference: ").add(ctx["encounter_id"], "ENCOUNTER").line()
    b.add("Date/Time: ").add(ctx["service_datetime"].strftime("%m/%d/%Y %H:%M"), "DATE").line()
    b.add("Caller: ").add(ctx["name"], "PATIENT")
    b.add("   Receiver: ").add(agent, "PROVIDER").line()
    b.add("Line: ").add(ctx["phone"], "PHONE").line().blank()
    b.add(ts()).add("AGENT: Thank you for calling the clinic, this is ")
    b.add(agent.split()[0]).add(". Who am I speaking with today? ").blank()
    b.add(ts()).add("CALLER: Hi, this is ").add(ctx["name"], "PATIENT").add(". ")
    if random.random() < 0.25:
        b.add("(speaking Spanish, interpreter joined) \"")
        b.add(random.choice(SPANISH_SNIPPETS))
        b.add("\" ")
    b.blank()
    b.add(ts()).add("AGENT: Thank you. For verification, can you confirm your date of birth and address? ").blank()
    b.add(ts()).add("CALLER: Sure, ").add(ctx["dob"].strftime("%m/%d/%Y"), "DOB").add(", and I live at ")
    b.add(f'{ctx["address"]}, {ctx["city"]}, {ctx["state"]} {ctx["zip"]}', "ADDRESS").add(". ").blank()
    b.add(ts()).add("AGENT: Perfect, you're verified. What can I help you with? ").blank()
    b.add(ts()).add("CALLER: I need to schedule my ")
    b.add(ctx["primary_detail"]["followup"]).add(". ").blank()
    b.add(ts()).add("AGENT: I have you down with your provider. A confirmation call will go to ")
    b.add(ctx["phone"], "PHONE").add(". ").blank()
    if random.random() < 0.3:
        b.add(ts()).add("CALLER: Also, can you update my chart? My ")
        b.add(ctx["contact_rel"]).add(" ").add(ctx["contact_name"], "CONTACT")
        b.add(" is my emergency contact now, at ").add(ctx["contact_phone"], "PHONE").add(". ").blank()
    b.add(ts()).add("AGENT: All set, anything else? ").blank()
    b.add(ts()).add("CALLER: No, that's all, thank you. ").blank()
    b.add(f"Duration: {random.randint(2, 9)} min {random.randint(0, 59)} sec")
    return b


_BUILDERS = {
    "progress_note": _build_progress_note,
    "history_physical": _build_history_physical,
    "discharge_summary": _build_discharge_summary,
    "ed_note": _build_ed_note,
    "telehealth_note": _build_telehealth_note,
    "procedure_note": _build_procedure_note,
    "radiology_report": _build_radiology_report,
    "behavioral_health_note": _build_behavioral_health_note,
    "patient_portal_message": _build_portal_message,
    "phone_call_transcript": _build_call_transcript,
}


# ---------------------------------------------------------------------------
# Note generation
# ---------------------------------------------------------------------------

def generate_note(i: int, fake: Faker, note_type: str = "mix",
                  dictation_ratio: float = 0.35) -> dict:
    """Generate one synthetic note row (dict) with ground-truth PHI spans."""
    if note_type == "mix":
        note_type = random.choice(NOTE_TYPES)
    dictation = random.random() < dictation_ratio and note_type not in NON_DICTATABLE

    ctx = _make_context(i, fake)
    builder = _BUILDERS[note_type](ctx)
    text, spans = builder.render(dictation=dictation)

    return {
        "note_id": ctx["note_id"],
        "patient_id": ctx["patient_id"],
        "patient_name": ctx["name"],
        "mrn": ctx["mrn"],
        # some notes in production are never linked to an encounter
        "encounter_id": None if random.random() < 0.08 else ctx["encounter_id"],
        "note_type": note_type + ("_dictation" if dictation else ""),
        "author": ctx["provider"],
        "author_npi": ctx["npi"],
        "service_datetime": ctx["service_datetime"].isoformat(timespec="minutes"),
        "department": None if random.random() < 0.15 else ctx["department"],
        "dictation_flag": dictation,
        "transcription_status": random.choices(
            ["Signed", "Transcribed", "Draft", "Pending review"],
            weights=[0.6, 0.2, 0.1, 0.1])[0],
        "word_count": len(text.split()),
        "note_text": text,
        "phi_spans": json.dumps(spans, ensure_ascii=False),
    }


def generate_notes_dataframe(n: int, fake: Faker = None, note_type: str = "mix",
                             dictation_ratio: float = 0.35) -> pd.DataFrame:
    fake = fake or Faker()
    return pd.DataFrame([generate_note(i, fake, note_type, dictation_ratio) for i in range(n)])


# Demo-app-compatible alias (signature: (n, fake))
def generate_clinical_notes(n, fake):
    return generate_notes_dataframe(n, fake)


# ---------------------------------------------------------------------------
# Serialization (matches the conventions in generate_from_schema.py)
# ---------------------------------------------------------------------------

def to_csv(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    buf.write("# Generated by synth-data-gen clinical_notes | All data is fictional\n")
    df.to_csv(buf, index=False)
    return buf.getvalue()


def to_json(df: pd.DataFrame) -> str:
    records = []
    for row in df.to_dict(orient="records"):
        row["phi_spans"] = json.loads(row["phi_spans"])  # embed as real arrays
        records.append(row)
    return json.dumps(
        {"_meta": {"generated_by": "synth-data-gen clinical_notes", "synthetic": True,
                   "record_count": len(records)},
         "data": records},
        indent=2, ensure_ascii=False,
    )


def to_sql(df: pd.DataFrame, table_name: str = "clinical_notes") -> str:
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
# Inline validator (same checks as generate_from_schema.py)
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


def _gt_document(notes_gt: dict, args, df: pd.DataFrame) -> dict:
    """Wrap ground truth with a synthetic marker (validator-friendly)."""
    return {
        "_meta": {
            "generated_by": "synth-data-gen clinical_notes",
            "synthetic": True,
            "description": "Ground-truth PHI spans for de-identification scoring. All data is fictional.",
            "seed": args.seed,
            "note_count": len(df),
        },
        "notes": notes_gt,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate synthetic clinical notes and dictation transcripts with safe-range PHI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-n", "--rows", type=int, default=25, help="Number of notes (default: 25)")
    parser.add_argument("-s", "--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("-f", "--format", choices=["csv", "json", "sql", "txt"], default="csv",
                        help="Output format (default: csv). txt writes one .txt per note.")
    parser.add_argument("-t", "--type", default="mix",
                        help="Note type: mix (default), " + ", ".join(NOTE_TYPES))
    parser.add_argument("--dictation-ratio", type=float, default=0.35,
                        help="Fraction of notes rendered as raw dictation (default: 0.35)")
    parser.add_argument("-o", "--output", default="./synthetic_output",
                        help="Output file or directory (default: ./synthetic_output)")
    parser.add_argument("--ground-truth", action="store_true",
                        help="Write clinical_notes_ground_truth.json sidecar with PHI spans")
    parser.add_argument("--validate", action="store_true",
                        help="Run PII/PHI validation after generation")
    parser.add_argument("--list-types", action="store_true", help="List note types and exit")
    args = parser.parse_args(argv)

    if args.list_types:
        print("Available note types (use 'mix' for a weighted blend):")
        for t in NOTE_TYPES:
            print(f"  {t}")
        return 0

    note_type = args.type
    dictation_ratio = args.dictation_ratio
    if note_type not in NOTE_TYPES and note_type not in ("mix", "dictation_transcript"):
        print(f"WARNING: unknown type '{args.type}', using 'mix'", file=sys.stderr)
        note_type = "mix"
    if note_type == "dictation_transcript":
        # pseudo-type: any note type, always rendered as raw dictation
        note_type = "mix"
        dictation_ratio = 1.0

    random.seed(args.seed)
    Faker.seed(args.seed)
    fake = Faker()

    print(f"Generating {args.rows} clinical note(s) (seed={args.seed}, type={note_type}, "
          f"dictation_ratio={dictation_ratio})")
    df = generate_notes_dataframe(args.rows, fake, note_type, dictation_ratio)

    out = Path(args.output)
    if out.suffix in (".csv", ".json", ".sql", ".txt"):
        out_file = out
        out_dir = out.parent
    else:
        out_dir = out
        out_file = out_dir / f"synthetic_clinical_notes.{args.format}"
    out_dir.mkdir(parents=True, exist_ok=True)

    exit_code = 0

    if args.format == "txt":
        gt = {}
        for _, row in df.iterrows():
            fn = out_dir / f"{row['note_id']}.txt"
            fn.write_text(row["note_text"], encoding="utf-8")
            gt[row["note_id"]] = {
                "note_type": row["note_type"],
                "phi_spans": json.loads(row["phi_spans"]),
            }
        if args.ground_truth:
            (out_dir / "clinical_notes_ground_truth.json").write_text(
                json.dumps(_gt_document(gt, args, df), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {len(df)} note(s) → {out_dir}/")
    else:
        content = {"csv": to_csv, "json": to_json, "sql": to_sql}[args.format](df)
        out_file.write_text(content, encoding="utf-8")
        print(f"Wrote {len(df)} rows → {out_file}")

        if args.ground_truth:
            gt = {row["note_id"]: {"note_type": row["note_type"],
                                   "phi_spans": json.loads(row["phi_spans"])}
                  for _, row in df.iterrows()}
            (out_dir / "clinical_notes_ground_truth.json").write_text(
                json.dumps(_gt_document(gt, args, df), indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Wrote PHI ground truth → {out_dir / 'clinical_notes_ground_truth.json'}")

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
                print("    Validation passed — no real PII/PHI detected.")

    if exit_code == 2:
        print("WARNING: Critical validation issues found. DO NOT use this data.", file=sys.stderr)
    elif exit_code == 1:
        print("NOTE: Validation warnings found. Review before using.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
