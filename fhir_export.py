#!/usr/bin/env python3
"""
FHIR R4 export for synthetic clinical data
===========================================
Converts cohort DataFrames from clinical_bundle.py into FHIR R4 resources
(Patient, Practitioner, Encounter, Condition, Observation, DocumentReference)
following the conventions documented in format-templates.md:

- identifier systems use `urn:example:` URIs — never real OIDs
- references are relative: "Patient/SYN-000001"
- Bundle entries use urn:uuid: fullUrls
- dates: YYYY-MM-DD or full ISO datetimes

Because the bundle generator produces *linked* data, every reference resolves
inside the combined Bundle — usable directly as an API mock-server fixture.
"""

import base64

import pandas as pd

# BCP-47 codes for the language pool used across the repo
_LANGUAGE_CODES = {
    "English": "en", "Spanish": "es", "Mandarin": "zh", "Arabic": "ar",
    "Tagalog": "tl", "Korean": "ko", "Hindi": "hi", "French": "fr",
    "Vietnamese": "vi",
}

_ENCOUNTER_CLASS = {
    "Outpatient": ("AMB", "ambulatory"),
    "Inpatient": ("IMP", "inpatient encounter"),
    "ED": ("EMER", "emergency"),
    "Telehealth": ("VR", "virtual"),
    "Observation": ("OBSENC", "observation encounter"),
    "Urgent Care": ("AMB", "ambulatory"),
}

_NOTE_TYPE_LOINC = {
    "progress_note": ("34117-2", "Progress note"),
    "progress_note_dictation": ("34117-2", "Progress note"),
    "history_physical": ("34133-9", "History and physical note"),
    "history_physical_dictation": ("34133-9", "History and physical note"),
    "discharge_summary": ("18842-5", "Discharge summary"),
    "discharge_summary_dictation": ("18842-5", "Discharge summary"),
    "ed_note": ("34117-2", "Emergency department note"),
    "ed_note_dictation": ("34117-2", "Emergency department note"),
    "telehealth_note": ("34117-2", "Progress note"),
    "telehealth_note_dictation": ("34117-2", "Progress note"),
    "procedure_note": ("28570-0", "Procedure note"),
    "procedure_note_dictation": ("28570-0", "Procedure note"),
}

_ABNORMAL_INTERPRETATION = {
    "L": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                       "code": "L", "display": "Low"}]}],
    "H": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                       "code": "H", "display": "High"}]}],
    "LL": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                        "code": "LL", "display": "Critical low"}]}],
    "HH": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                        "code": "HH", "display": "Critical high"}]}],
}

_US_CORE_PATIENT = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"


def patient_resource(row) -> dict:
    r = {
        "resourceType": "Patient",
        "id": row["patient_id"],
        "meta": {"profile": [_US_CORE_PATIENT]},
        "identifier": [{
            "use": "usual",
            "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                                 "code": "MR"}]},
            "system": "urn:example:hospital:mrn",
            "value": row["mrn"],
        }],
        "active": True,
        "name": [{"use": "official", "family": row["last_name"],
                  "given": [row["first_name"]]}],
        "gender": str(row["gender"]).lower()[:1] if row.get("gender") else "unknown",
        "birthDate": row["dob"],
    }
    if row.get("ssn"):
        r["identifier"].append({
            "use": "official",
            "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                                 "code": "SS"}]},
            "system": "urn:example:ssn",
            "value": row["ssn"],
        })
    telecom = []
    if row.get("phone"):
        telecom.append({"system": "phone", "value": row["phone"], "use": "home"})
    if row.get("email"):
        telecom.append({"system": "email", "value": row["email"]})
    if telecom:
        r["telecom"] = telecom
    if row.get("deceased_flag"):
        r["deceasedBoolean"] = True
    if row.get("address"):
        r["address"] = [{
            "use": "home",
            "line": [row["address"]],
            "city": row.get("city"),
            "state": row.get("state"),
            "postalCode": row.get("zip"),
            "country": "US",
        }]
    lang = row.get("preferred_language")
    if lang:
        code = _LANGUAGE_CODES.get(lang, "en")
        r["communication"] = [{
            "language": {"coding": [{"system": "urn:ietf:bcp:47", "code": code}],
                         "text": lang},
            "preferred": True,
        }]
    return r


def practitioner_resource(provider: dict) -> dict:
    return {
        "resourceType": "Practitioner",
        "id": provider["provider_id"],
        "identifier": [{
            "system": "urn:example:npi",
            "value": provider["npi"],
        }],
        "active": True,
        "name": [{"family": provider["last"], "given": [provider["first"]],
                  "prefix": ["Dr."]}],
    }


def encounter_resource(row, patient_id: str, provider: dict, diagnoses=None) -> dict:
    r = {
        "resourceType": "Encounter",
        "id": row["encounter_id"],
        "status": "finished" if row.get("discharge_datetime") else "in-progress",
        "class": _encounter_class(row["encounter_type"]),
        "subject": {"reference": f"Patient/{patient_id}"},
        "participant": [{
            "individual": {"reference": f'Practitioner/{provider["provider_id"]}',
                           "display": provider["display_short"]},
        }],
        "period": {"start": row["admit_datetime"]},
    }
    if row.get("discharge_datetime"):
        r["period"]["end"] = row["discharge_datetime"]
    if diagnoses is not None and len(diagnoses):
        r["diagnosis"] = [{
            "condition": {"reference": f'Condition/DX-{d["diagnosis_id"]}'},
            "use": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/diagnosis-role",
                                "code": "billing"}]},
        } for _, d in diagnoses.iterrows()]
    return r


def condition_resource(row, patient_id: str) -> dict:
    return {
        "resourceType": "Condition",
        "id": f'DX-{row["diagnosis_id"]}',
        "clinicalStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "code": "active"}]},
        "verificationStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
            "code": "confirmed"}]},
        "code": {
            "coding": [{"system": "http://hl7.org/fhir/sid/icd-10",
                        "code": row["icd10_code"]}],
            "text": row["description"],
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f'Encounter/{row["encounter_id"]}'},
        "onsetDateTime": row.get("onset_date") or None,
    }


def observation_resource(row, patient_id: str) -> dict:
    r = {
        "resourceType": "Observation",
        "id": f'LAB-{row["lab_id"]}',
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": row["loinc_code"],
                             "display": row["test_name"]}],
                 "text": row["test_name"]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f'Encounter/{row["encounter_id"]}'},
        "effectiveDateTime": row["result_datetime"],
    }
    if row.get("value") is not None:
        r["valueQuantity"] = {"value": float(row["value"]), "unit": row["unit"]}
    else:
        r["dataAbsentReason"] = {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/data-absent-reason",
            "code": "unknown"}]}
    ref = row.get("reference_range")
    if ref and "-" in str(ref):
        lo, hi = str(ref).split("-", 1)
        r["referenceRange"] = [{"low": {"value": float(lo)},
                                "high": {"value": float(hi)}}]
    flag = row.get("abnormal_flag")
    if flag in _ABNORMAL_INTERPRETATION:
        r["interpretation"] = _ABNORMAL_INTERPRETATION[flag]
    return r


def document_reference_resource(row, patient_id: str, provider_ref: str = None) -> dict:
    loinc_code, loinc_display = _NOTE_TYPE_LOINC.get(
        row["note_type"], ("34117-2", "Progress note"))
    payload = base64.b64encode(str(row["note_text"]).encode("utf-8")).decode("ascii")
    author = ({"reference": provider_ref} if provider_ref else {}) | {"display": row["author"]}
    return {
        "resourceType": "DocumentReference",
        "id": row["note_id"],
        "status": "current",
        "type": {"coding": [{"system": "http://loinc.org", "code": loinc_code,
                             "display": loinc_display}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": row["service_datetime"],
        "author": [author],
        "content": [{
            "attachment": {
                "contentType": "text/plain; charset=utf-8",
                "data": payload,
            },
            "format": {"system": "urn:example:format",
                       "code": "text/plain",
                       "display": "Plain text note"},
        }],
        "context": {"encounter": [{"reference": f'Encounter/{row["encounter_id"]}'}]},
    }


def _encounter_class(enc_type: str) -> dict:
    code, display = _ENCOUNTER_CLASS.get(enc_type, ("AMB", "ambulatory"))
    return {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": code, "display": display}


# ---------------------------------------------------------------------------
# Cohort → bundles
# ---------------------------------------------------------------------------

def _bundle(entries: list) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(entries),
        "entry": [{"fullUrl": f"urn:uuid:{e['resourceType']}/{e['id']}", "resource": e}
                  for e in entries],
    }


def _provider_pool(cohort: dict) -> dict:
    """Reconstruct provider records from encounter/note author fields."""
    providers = {}
    enc = cohort["encounters"]
    notes = cohort["clinical_notes"]
    prov_by_enc = dict(zip(enc["encounter_id"], enc["attending_provider_id"]))
    npi_by_note = dict(zip(notes["note_id"], notes["author_npi"])) if len(notes) else {}
    display_by_note = dict(zip(notes["note_id"], notes["author"])) if len(notes) else {}
    # encounter provider ids -> npi via notes is imperfect; npi filled when known
    for _, e in enc.iterrows():
        pid = e["attending_provider_id"]
        if pid not in providers:
            providers[pid] = {"provider_id": pid, "first": "", "last": pid,
                              "display_short": pid, "npi": ""}
    if len(notes):
        for _, n in notes.iterrows():
            pid = prov_by_enc.get(n["encounter_id"])
            if pid and pid in providers:
                providers[pid]["npi"] = n["author_npi"]
                display = str(n["author"]).replace(", MD", "")
                parts = display.replace("Dr. ", "").split(" ", 1)
                if len(parts) == 2:
                    providers[pid]["first"], providers[pid]["last"] = parts
                providers[pid]["display_short"] = f"Dr. {parts[-1] if len(parts) > 1 else pid}"
    return providers


def cohort_to_bundles(cohort: dict):
    """Yield (filename, bundle_dict) — one combined bundle plus per-type bundles."""
    enc = cohort["encounters"]
    enc_patient = dict(zip(enc["encounter_id"], enc["patient_id"]))
    providers = _provider_pool(cohort)
    prov_by_enc = dict(zip(enc["encounter_id"], enc["attending_provider_id"]))

    dx_by_enc = {}
    for _, d in cohort["diagnoses"].iterrows():
        dx_by_enc.setdefault(d["encounter_id"], []).append(d)

    patients = [patient_resource(r) for _, r in cohort["patients"].iterrows()]
    practitioners = [practitioner_resource(p) for p in providers.values()]
    encounters = []
    for _, e in enc.iterrows():
        prov = providers.get(e["attending_provider_id"])
        encounters.append(encounter_resource(
            e, e["patient_id"], prov,
            diagnoses=pd.DataFrame(dx_by_enc.get(e["encounter_id"], []))))
    conditions = [condition_resource(d, enc_patient.get(d["encounter_id"]))
                  for _, d in cohort["diagnoses"].iterrows()]
    observations = [observation_resource(l, enc_patient.get(l["encounter_id"]))
                    for _, l in cohort["lab_results"].iterrows()]
    docrefs = []
    for _, n in cohort["clinical_notes"].iterrows():
        pid = prov_by_enc.get(n["encounter_id"])
        ref = f"Practitioner/{pid}" if pid else None
        docrefs.append(document_reference_resource(n, n["patient_id"], ref))

    combined = patients + practitioners + encounters + conditions + observations + docrefs
    yield "synthetic_fhir_bundle.json", _bundle(combined)
    for fname, entries in [
        ("synthetic_patients_fhir.json", patients),
        ("synthetic_encounters_fhir.json", encounters),
        ("synthetic_diagnoses_fhir.json", conditions),
        ("synthetic_lab_results_fhir.json", observations),
        ("synthetic_clinical_notes_fhir.json", docrefs),
    ]:
        if entries:
            yield fname, _bundle(entries)
