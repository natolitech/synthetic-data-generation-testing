#!/usr/bin/env python3
"""
HL7 v2.x export for synthetic clinical data
============================================
Converts cohort DataFrames from clinical_bundle.py into pipe-delimited HL7 v2.5.1
messages following the segment layouts documented in format-templates.md:

- ADT^A01 admit messages (MSH/EVN/PID/PV1/IN1) — one per non-telehealth encounter
- ORU^R01 lab result messages (MSH/PID/OBR/OBX...) — one per encounter with labs

All facility/application names use SYN/SYNTH prefixes; identifiers reuse the
cohort's safe ranges. Message content is escaped (|, ^, ~, backslash, &) so every
generated message is well-formed.
"""

from datetime import datetime

from .clock import clock

_SENDING_APP = "SYNTHSYS"
_SENDING_FAC = "SYNFAC"
_RECV_APP = "RECVSYS"
_RECV_FAC = "RECVFAC"

_INSURANCE_PLANS = [
    ("SYNPLAN001", "Blue Cross Synthetic"),
    ("SYNPLAN002", "Synthetic Health Partners"),
    ("SYNPLAN003", "Aetna Synthetic Test Plan"),
    ("SYNPLAN004", "United Synthetic Care"),
    ("SYNPLAN005", "Synthetic Medicare Test"),
]

_V2_SEX = {"Female": "F", "Male": "M", "Non-binary": "O", "Unknown": "U"}

# PID-10 race codes (CDCREC)
_RACE_CODES = {
    "White": "2106-3", "Black or African American": "2054-5",
    "Asian": "2028-9", "Two or More Races": "2076-8",
    "American Indian or Alaska Native": "1002-5",
    "Native Hawaiian or Other Pacific Islander": "2076-8",
    "Unknown": "UNK",
}

_ENC_PV1_CLASS = {"Inpatient": "I", "ED": "E", "Outpatient": "O",
                  "Telehealth": "O", "Observation": "O"}


def _esc(value) -> str:
    """Escape HL7 delimiters inside content so segments stay well-formed."""
    if value is None:
        return ""
    return (str(value)
            .replace("\\", "\\E\\")
            .replace("|", "\\F\\")
            .replace("^", "\\S\\")
            .replace("~", "\\R\\")
            .replace("&", "\\T\\")
            .replace("\n", " "))


def _ts(dt: str) -> str:
    """ISO datetime → HL7 YYYYMMDDHHmmss."""
    try:
        d = datetime.fromisoformat(str(dt))
    except (ValueError, TypeError):
        return ""
    return d.strftime("%Y%m%d%H%M%S")


def _ts_date(dt: str) -> str:
    try:
        d = datetime.fromisoformat(str(dt))
    except (ValueError, TypeError):
        return ""
    return d.strftime("%Y%m%d")


def _msh(msg_type: str, control_id: str) -> str:
    return (f"MSH|^~\\&|{_SENDING_APP}|{_SENDING_FAC}|{_RECV_APP}|{_RECV_FAC}|"
            f"{clock.now().strftime('%Y%m%d%H%M%S')}||{msg_type}|{control_id}|P|2.5.1")


def _pid(patient: dict) -> str:
    """PID segment from a patient row dict."""
    name = f'{_esc(patient["last_name"])}^{_esc(patient["first_name"])}^^^'
    ids = f'{_esc(patient["mrn"])}^^^{_SENDING_FAC}^MR'
    if patient.get("ssn"):
        ids += f'~{_esc(patient["ssn"])}^^^USSSA^SS'
    addr = (f'{_esc(patient.get("address"))}^^{_esc(patient.get("city"))}^'
            f'{_esc(patient.get("state"))}^{_esc(patient.get("zip"))}^US')
    phone = ""
    if patient.get("phone"):
        p = str(patient["phone"]).split("-")
        phone = f'^PRN^PH^^^{p[0]}^{p[1]}' if len(p) == 2 else f'^PRN^PH^^^{patient["phone"]}'
    race = _RACE_CODES.get(patient.get("race"), "UNK")
    race_txt = f'{race}^{_esc(patient.get("race"))}^CDCREC'
    ethnicity = ("N^Not Hispanic^CDCREC" if "Not Hispanic" in str(patient.get("ethnicity"))
                 else "H^Hispanic^CDCREC")
    sex = _V2_SEX.get(patient.get("gender"), "U")
    return (f"PID|1||{ids}||{name}||{_ts_date(patient['dob'])}|{sex}||{race_txt}|"
            f"{addr}||{phone}|||||||||{ethnicity}")


def adt_a01(encounter: dict, patient: dict, provider_display: str,
            control_id: str) -> str:
    """ADT^A01 admit message."""
    admit_ts = _ts(encounter["admit_datetime"])
    pv1_class = _ENC_PV1_CLASS.get(encounter["encounter_type"], "O")
    prov = _esc(provider_display.replace(", MD", "").replace("Dr. ", ""))
    plan_id, plan_name = _INSURANCE_PLANS[hash(encounter["encounter_id"]) %
                                          len(_INSURANCE_PLANS)]
    segments = [
        _msh("ADT^A01", control_id),
        f"EVN|A01|{admit_ts}",
        _pid(patient),
        (f"PV1|1|{pv1_class}|{pv1_class}^101^A^{_SENDING_FAC}||||{prov}^^^^^Dr.|||"
         f"{_esc(encounter.get('department'))}||||A|||{prov}^^^^^Dr.|IN|||||||||||||"
         f"{_SENDING_FAC}|||||{admit_ts}"),
        (f"IN1|1|{plan_id}^{plan_name}|SYNPAY001|{plan_name} Test Plan|"
         f"PO Box 99999^^Testville^IL^60601|||||||||||||||||||||||||||||987654321"),
    ]
    return "\n".join(segments)


def oru_r01(encounter: dict, patient: dict, labs: list, control_id: str) -> str:
    """ORU^R01 lab-result message with one OBR and N OBX segments."""
    order_id = f"SYN-ORD-{str(encounter['encounter_id'])[-6:]}"
    collection_ts = _ts(labs[0]["result_datetime"]) if labs else _ts(encounter["admit_datetime"])
    segments = [
        _msh("ORU^R01", control_id).replace(_SENDING_APP, "SYNTHLAB"),
        _pid(patient),
        (f"OBR|1|{order_id}|SYN-LAB-{str(encounter['encounter_id'])[-6:]}|"
         f"80053^Lab Panel^CPT||||{collection_ts}"),
    ]
    for i, lab in enumerate(labs, 1):
        flag = lab.get("abnormal_flag") or "N"
        value = "" if lab.get("value") is None else str(lab["value"])
        segments.append(
            f'OBX|{i}|NM|{_esc(lab["loinc_code"])}^{_esc(lab["test_name"])}^LN||'
            f'{value}|{_esc(lab["unit"])}|{_esc(lab["reference_range"])}|{flag}|||F')
    return "\n".join(segments)


# ---------------------------------------------------------------------------
# Cohort → messages
# ---------------------------------------------------------------------------

def cohort_to_hl7_messages(cohort: dict):
    """Yield (filename, text). One ADT per in-person encounter, one ORU per
    encounter with labs. Messages are \n-separated per segment, blank line
    between messages."""
    enc = cohort["encounters"]
    pat_by_id = {p["patient_id"]: p for _, p in cohort["patients"].iterrows()}
    labs_by_enc = {}
    for _, l in cohort["lab_results"].iterrows():
        labs_by_enc.setdefault(l["encounter_id"], []).append(l)

    adt_msgs, oru_msgs = [], []
    seq = 0
    for _, e in enc.iterrows():
        patient = pat_by_id[e["patient_id"]]
        provider = ""
        if len(cohort["clinical_notes"]):
            match = cohort["clinical_notes"][
                cohort["clinical_notes"]["encounter_id"] == e["encounter_id"]]
            if len(match):
                provider = match["author"].iloc[0]
        seq += 1
        if e["encounter_type"] != "Telehealth":
            adt_msgs.append(adt_a01(e, patient, provider or "Dr. Synth",
                                    f"SYN-MSG-{seq:05d}"))
        if e["encounter_id"] in labs_by_enc:
            seq += 1
            oru_msgs.append(oru_r01(e, patient, labs_by_enc[e["encounter_id"]],
                                    f"SYN-MSG-{seq:05d}"))

    yield "synthetic_adt_messages.hl7", "\n\n".join(adt_msgs)
    yield "synthetic_oru_lab_messages.hl7", "\n\n".join(oru_msgs)
