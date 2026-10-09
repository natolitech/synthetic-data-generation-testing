#!/usr/bin/env python3
"""
Synthetic Data Generation Demo
===============================
Interactive demo for the synth-data-gen Claude Code skill.
All data generated is entirely fictional — zero real PII/PHI.

Run:
    streamlit run demo_app.py
"""

import io
import json
import random
import re
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from faker import Faker

try:
    from clinical_notes import generate_clinical_notes
except ImportError:  # pragma: no cover - module lives next to this script
    generate_clinical_notes = None

# ---------------------------------------------------------------------------
# Constants (from synth-data-gen skill references)
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

ICD10_POOLS = {
    "Diabetes": [("E11.9", "Type 2 DM without complications"), ("E11.65", "Type 2 DM with hyperglycemia"), ("E11.21", "Type 2 DM with diabetic nephropathy")],
    "Hypertension": [("I10", "Essential hypertension"), ("I11.9", "Hypertensive heart disease without heart failure"), ("I12.9", "Hypertensive CKD stage 1-4")],
    "Heart disease": [("I25.10", "Atherosclerotic heart disease"), ("I48.91", "Unspecified atrial fibrillation"), ("I50.9", "Heart failure, unspecified")],
    "Respiratory": [("J06.9", "Acute upper respiratory infection"), ("J18.9", "Pneumonia, unspecified"), ("J44.1", "COPD with acute exacerbation")],
    "Mental health": [("F32.1", "Major depressive disorder, single episode, moderate"), ("F41.1", "Generalized anxiety disorder"), ("F17.210", "Nicotine dependence, cigarettes")],
    "Musculoskeletal": [("M54.5", "Low back pain"), ("M79.3", "Panniculitis, unspecified"), ("M17.11", "Primary osteoarthritis, right knee")],
}

MEDICATIONS = {
    "Diabetes": ["metformin 500mg", "glipizide 5mg", "insulin glargine 100u/mL", "sitagliptin 100mg"],
    "Hypertension": ["lisinopril 10mg", "amlodipine 5mg", "losartan 50mg", "metoprolol 25mg"],
    "Cardiac": ["atorvastatin 40mg", "aspirin 81mg", "clopidogrel 75mg", "apixaban 5mg"],
    "Psych": ["sertraline 50mg", "fluoxetine 20mg", "bupropion 150mg XL", "quetiapine 25mg"],
    "Pain": ["acetaminophen 500mg", "ibuprofen 400mg", "gabapentin 300mg"],
    "Antibiotics": ["amoxicillin 500mg", "azithromycin 250mg", "ciprofloxacin 500mg"],
}

DEPARTMENTS = ["Cardiology", "Oncology", "Primary Care", "Emergency", "Surgery", "OB/GYN", "Psychiatry", "Pediatrics", "Orthopedics", "Neurology"]
ENCOUNTER_TYPES = [("Outpatient", 0.60), ("ED", 0.15), ("Inpatient", 0.10), ("Telehealth", 0.10), ("Observation", 0.05)]
DISPOSITIONS = [("Discharged Home", 0.85), ("Transfer", 0.05), ("AMA", 0.01), ("Expired", 0.005), ("Observation", 0.085)]

COURSE_PREFIXES = ["CS", "BIOL", "CHEM", "PHYS", "MATH", "ENGL", "HIST", "PSYC", "ECON", "STAT", "PHIL", "ANTH"]
GRADES = [("A", 0.25), ("A-", 0.10), ("B+", 0.10), ("B", 0.15), ("B-", 0.08), ("C+", 0.07), ("C", 0.08), ("C-", 0.04), ("D", 0.03), ("F", 0.02), ("W", 0.05), ("I", 0.03)]

HR_DEPARTMENTS = ["Engineering", "Marketing", "Sales", "Human Resources", "Finance", "Legal", "Operations", "IT", "Research", "Customer Support"]
JOB_TITLES = {
    "Engineering": ["Software Engineer", "Senior Engineer", "Staff Engineer", "Engineering Manager", "QA Engineer"],
    "Marketing": ["Marketing Analyst", "Brand Manager", "Content Strategist", "Marketing Director"],
    "Sales": ["Account Executive", "Sales Representative", "Sales Manager", "VP of Sales"],
    "Human Resources": ["HR Generalist", "Recruiter", "HR Manager", "Benefits Coordinator"],
    "Finance": ["Financial Analyst", "Accountant", "Controller", "CFO", "Accounts Payable Clerk"],
    "Legal": ["Paralegal", "Corporate Counsel", "Compliance Officer", "General Counsel"],
    "Operations": ["Operations Analyst", "Project Manager", "Operations Director", "Logistics Coordinator"],
    "IT": ["Systems Administrator", "Network Engineer", "IT Manager", "Security Analyst", "Help Desk Technician"],
    "Research": ["Research Scientist", "Lab Technician", "Research Director", "Postdoctoral Fellow"],
    "Customer Support": ["Support Agent", "Support Lead", "Customer Success Manager"],
}

IAM_APPS = ["Epic", "Banner", "Workday", "Box", "ServiceNow", "Salesforce", "JIRA", "Confluence", "Tableau", "SAP"]
IAM_ROLES = {
    "Epic": ["Physician", "Nurse", "Registration", "HIM Coder", "Read-Only"],
    "Banner": ["Student Admin", "Financial Aid", "Registrar", "Advisor"],
    "Workday": ["Employee Self-Service", "Manager", "HR Partner", "Payroll Admin"],
    "Box": ["Co-Owner", "Editor", "Viewer", "Uploader"],
    "ServiceNow": ["ITIL User", "Fulfiller", "Admin", "Approver"],
    "Salesforce": ["Standard User", "System Admin", "Read Only", "Marketing User"],
    "JIRA": ["Developer", "Project Lead", "Admin", "Viewer"],
    "Confluence": ["Creator", "Admin", "Viewer"],
    "Tableau": ["Creator", "Explorer", "Viewer"],
    "SAP": ["Display Only", "Transaction User", "Power User", "Admin"],
}

STUDY_TITLES = [
    "Efficacy of Novel Biomarker Panel in Early Detection of Pancreatic Cancer",
    "Impact of Telehealth on Chronic Disease Management Outcomes",
    "Randomized Controlled Trial of Mindfulness-Based Intervention for Anxiety",
    "Longitudinal Analysis of Gut Microbiome and Metabolic Syndrome",
    "Machine Learning Approaches to Predict Hospital Readmission Risk",
    "Phase II Trial of Combination Immunotherapy in Advanced Melanoma",
    "Effects of Exercise Intervention on Cognitive Decline in Elderly Adults",
    "Genomic Profiling of Treatment-Resistant Depression",
]

CPT_CODES = [
    ("99213", "Office visit, established, low complexity", 150),
    ("99214", "Office visit, established, moderate complexity", 250),
    ("99215", "Office visit, established, high complexity", 350),
    ("99223", "Initial hospital care, high complexity", 800),
    ("99232", "Subsequent hospital care, moderate complexity", 400),
    ("99283", "ED visit, moderate severity", 500),
    ("99285", "ED visit, high severity", 1200),
    ("36415", "Venipuncture", 35),
    ("71046", "Chest X-ray, 2 views", 200),
    ("93000", "Electrocardiogram, routine", 150),
]

PAYERS = ["BlueCross BlueShield", "Aetna", "UnitedHealthcare", "Cigna", "Humana", "Medicare", "Medicaid", "Self-Pay"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def weighted_choice(options):
    values, weights = zip(*options)
    return random.choices(values, weights=weights, k=1)[0]


def safe_email(first, last, fake):
    clean_first = re.sub(r'[^a-zA-Z0-9]', '', first.lower())
    clean_last = re.sub(r'[^a-zA-Z0-9]', '', last.lower())
    domain = random.choice(SAFE_EMAIL_DOMAINS)
    return f"{clean_first}.{clean_last}@{domain}"


def safe_ssn():
    return f"{SAFE_SSN_PREFIX}-{random.randint(0, 9999):04d}"


def safe_phone():
    return f"{SAFE_PHONE_PREFIX}{random.randint(0, 99):02d}"


def inject_edge_case_names(n):
    count = min(len(EDGE_CASE_NAMES), max(1, n // 12))
    return set(random.sample(range(n), count))


# ---------------------------------------------------------------------------
# Domain generators
# ---------------------------------------------------------------------------

def generate_clinical_patients(n, fake):
    edge_indices = inject_edge_case_names(n)
    rows = []
    for i in range(n):
        if i in edge_indices:
            idx = list(edge_indices).index(i) % len(EDGE_CASE_NAMES)
            first, last = EDGE_CASE_NAMES[idx]
        else:
            first, last = fake.first_name(), fake.last_name()

        age_bucket = weighted_choice([("pediatric", 0.05), ("young_adult", 0.40), ("middle", 0.35), ("senior", 0.20)])
        age = {"pediatric": random.randint(0, 17), "young_adult": random.randint(18, 44), "middle": random.randint(45, 64), "senior": random.randint(65, 99)}[age_bucket]
        dob = date.today() - timedelta(days=age * 365 + random.randint(0, 364))

        rows.append({
            "patient_id": f"SYN-{i+1:06d}",
            "mrn": f"MRN-{2240001+i}",
            "first_name": first,
            "last_name": last,
            "dob": dob.isoformat(),
            "gender": weighted_choice([("Female", 0.49), ("Male", 0.49), ("Non-binary", 0.015), ("Unknown", 0.005)]),
            "race": weighted_choice(RACE_OPTIONS),
            "ethnicity": weighted_choice(ETHNICITY_OPTIONS),
            "ssn": None if random.random() < 0.05 else safe_ssn(),
            "email": None if random.random() < 0.15 else safe_email(first, last, fake),
            "phone": None if random.random() < 0.05 else safe_phone(),
            "address": fake.street_address(),
            "city": fake.city(),
            "state": fake.state_abbr(),
            "zip": fake.zipcode(),
            "preferred_language": weighted_choice(LANGUAGES),
            "deceased_flag": random.random() < 0.03,
        })
    return pd.DataFrame(rows)


def generate_clinical_encounters(n, fake, patient_ids=None):
    if patient_ids is None:
        patient_ids = [f"SYN-{i+1:06d}" for i in range(max(10, n // 3))]
    rows = []
    for i in range(n):
        enc_type = weighted_choice(ENCOUNTER_TYPES)
        admit = datetime.now() - timedelta(days=random.randint(1, 730), hours=random.randint(0, 23), minutes=random.randint(0, 59))
        los_hours = {"Inpatient": random.randint(24, 240), "ED": random.randint(2, 12), "Outpatient": random.randint(0, 2), "Telehealth": 0, "Observation": random.randint(12, 48)}[enc_type]
        discharge = admit + timedelta(hours=los_hours) if random.random() > 0.05 else None

        rows.append({
            "encounter_id": f"ENC-{i+1:08d}",
            "patient_id": random.choice(patient_ids),
            "encounter_type": enc_type,
            "admit_datetime": admit.isoformat(timespec="minutes"),
            "discharge_datetime": discharge.isoformat(timespec="minutes") if discharge else None,
            "department": random.choice(DEPARTMENTS),
            "attending_provider_id": f"PRV-{random.randint(1001, 1200)}",
            "disposition": weighted_choice(DISPOSITIONS) if discharge else None,
        })
    return pd.DataFrame(rows)


def generate_clinical_diagnoses(n, fake):
    encounter_ids = [f"ENC-{i+1:08d}" for i in range(max(10, n // 2))]
    rows = []
    for i in range(n):
        category = random.choice(list(ICD10_POOLS.keys()))
        code, desc = random.choice(ICD10_POOLS[category])
        rows.append({
            "diagnosis_id": i + 1,
            "encounter_id": random.choice(encounter_ids),
            "icd10_code": code,
            "description": desc,
            "dx_type": "Principal" if random.random() < 0.3 else "Secondary",
            "onset_date": (date.today() - timedelta(days=random.randint(1, 1825))).isoformat() if random.random() > 0.2 else None,
        })
    return pd.DataFrame(rows)


def generate_clinical_labs(n, fake):
    encounter_ids = [f"ENC-{i+1:08d}" for i in range(max(10, n // 3))]
    lab_defs = [
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
    rows = []
    for i in range(n):
        loinc, name, unit, ref_low, ref_high, abs_low, abs_high = random.choice(lab_defs)
        if random.random() < 0.10:
            value = round(random.uniform(abs_low, ref_low) if random.random() < 0.5 else random.uniform(ref_high, abs_high), 2)
        else:
            value = round(random.uniform(ref_low, ref_high), 2)
        if random.random() < 0.05:
            value = None

        flag = "N"
        if value is not None:
            if value < ref_low:
                flag = "LL" if value < ref_low * 0.7 else "L"
            elif value > ref_high:
                flag = "HH" if value > ref_high * 1.3 else "H"

        rows.append({
            "lab_id": i + 1,
            "encounter_id": random.choice(encounter_ids),
            "loinc_code": loinc,
            "test_name": name,
            "value": value,
            "unit": unit,
            "reference_range": f"{ref_low}-{ref_high}",
            "abnormal_flag": flag if value else None,
            "result_datetime": (datetime.now() - timedelta(days=random.randint(1, 365), hours=random.randint(0, 23))).isoformat(timespec="minutes"),
        })
    return pd.DataFrame(rows)


def generate_student_records(n, fake):
    edge_indices = inject_edge_case_names(n)
    rows = []
    for i in range(n):
        if i in edge_indices:
            idx = list(edge_indices).index(i) % len(EDGE_CASE_NAMES)
            first, last = EDGE_CASE_NAMES[idx]
        else:
            first, last = fake.first_name(), fake.last_name()

        level = weighted_choice([("Undergraduate", 0.65), ("Graduate", 0.25), ("Professional", 0.10)])
        if level == "Undergraduate":
            age = random.randint(17, 25)
        elif level == "Graduate":
            age = random.randint(22, 40)
        else:
            age = random.randint(24, 45)
        if random.random() < 0.05:
            age = random.randint(40, 65)

        citizenship = weighted_choice([("US Citizen", 0.65), ("Permanent Resident", 0.05), ("International", 0.30)])

        rows.append({
            "student_id": f"SYN-{100000 + i}",
            "first_name": first,
            "last_name": last,
            "dob": (date.today() - timedelta(days=age * 365 + random.randint(0, 364))).isoformat(),
            "email": safe_email(first, last, fake),
            "phone": None if random.random() < 0.10 else safe_phone(),
            "level": level,
            "major": fake.job().split()[0] + " Studies" if random.random() < 0.3 else random.choice(["Computer Science", "Biology", "Economics", "Psychology", "English", "Mathematics", "Chemistry", "History", "Physics", "Political Science"]),
            "gpa": round(random.uniform(1.5, 4.0), 2) if random.random() > 0.03 else None,
            "credits_earned": random.randint(0, 120 if level == "Undergraduate" else 60),
            "enrollment_status": weighted_choice([("Enrolled", 0.80), ("Leave of Absence", 0.05), ("Graduated", 0.10), ("Withdrawn", 0.05)]),
            "citizenship": citizenship,
            "visa_type": random.choice(["F-1", "J-1"]) if citizenship == "International" else None,
            "ferpa_restriction": random.random() < 0.03,
        })
    return pd.DataFrame(rows)


def generate_student_enrollment(n, fake):
    student_ids = [f"SYN-{100000 + i}" for i in range(max(10, n // 4))]
    terms = ["Fall 2024", "Winter 2025", "Spring 2025", "Summer 2025", "Fall 2025"]
    rows = []
    for i in range(n):
        prefix = random.choice(COURSE_PREFIXES)
        number = random.choice([101, 102, 201, 202, 210, 301, 305, 315, 401, 410, 450])
        rows.append({
            "enrollment_id": i + 1,
            "student_id": random.choice(student_ids),
            "course_id": f"{prefix} {number}",
            "section": f"{random.randint(1, 5):02d}",
            "term": random.choice(terms),
            "credits": weighted_choice([(3, 0.45), (4, 0.30), (1, 0.10), (2, 0.10), (5, 0.05)]),
            "grade": weighted_choice(GRADES) if random.random() > 0.15 else "IP",
            "enrollment_status": weighted_choice([("Completed", 0.75), ("Enrolled", 0.10), ("Dropped", 0.08), ("Waitlisted", 0.07)]),
        })
    return pd.DataFrame(rows)


def generate_hr_employees(n, fake):
    edge_indices = inject_edge_case_names(n)
    rows = []
    for i in range(n):
        if i in edge_indices:
            idx = list(edge_indices).index(i) % len(EDGE_CASE_NAMES)
            first, last = EDGE_CASE_NAMES[idx]
        else:
            first, last = fake.first_name(), fake.last_name()

        dept = random.choice(HR_DEPARTMENTS)
        title = random.choice(JOB_TITLES[dept])
        is_director_plus = any(kw in title.lower() for kw in ["director", "vp", "cfo", "counsel", "manager"])
        salary = random.randint(100000, 350000) if is_director_plus else random.randint(35000, 120000)
        hire_date = date.today() - timedelta(days=random.randint(30, 10950))
        terminated = random.random() < 0.15

        rows.append({
            "employee_id": f"EMP-{200000 + i}",
            "first_name": first,
            "last_name": last,
            "ssn": None if random.random() < 0.02 else safe_ssn(),
            "dob": (date.today() - timedelta(days=random.randint(18, 65) * 365 + random.randint(0, 364))).isoformat(),
            "hire_date": hire_date.isoformat(),
            "termination_date": (hire_date + timedelta(days=random.randint(90, 3650))).isoformat() if terminated else None,
            "department": dept,
            "job_title": title,
            "salary": salary,
            "manager_id": f"EMP-{200000 + random.randint(0, max(0, i - 1))}" if i > 0 else None,
            "flsa_status": "Exempt" if salary > 55000 else "Non-Exempt",
            "email": safe_email(first, last, fake),
            "phone": safe_phone(),
        })
    return pd.DataFrame(rows)


def generate_iam_accounts(n, fake):
    rows = []
    for i in range(n):
        first, last = fake.first_name(), fake.last_name()
        username = f"{first[0].lower()}{last.lower()}"
        if random.random() < 0.1:
            username += str(random.randint(2, 5))

        acct_type = weighted_choice([("Employee", 0.70), ("Student", 0.15), ("Contractor", 0.08), ("Service", 0.05), ("Admin", 0.02)])
        status = weighted_choice([("Active", 0.85), ("Disabled", 0.08), ("Locked", 0.04), ("Expired", 0.03)])
        created = date.today() - timedelta(days=random.randint(30, 3650))
        last_logon = (datetime.now() - timedelta(days=random.randint(0, 90))).isoformat(timespec="minutes") if status == "Active" and random.random() > 0.10 else None

        rows.append({
            "user_id": username,
            "display_name": f"{first} {last}",
            "upn": f"{username}@example.edu",
            "dn": f"CN={first} {last},OU={random.choice(HR_DEPARTMENTS)},DC=example,DC=edu",
            "account_type": acct_type,
            "account_status": status,
            "created_date": created.isoformat(),
            "last_logon": last_logon,
            "password_last_set": (datetime.now() - timedelta(days=random.randint(0, 180))).date().isoformat() if status == "Active" else None,
            "email": f"{username}@example.edu",
            "group_count": random.randint(1, 50) if acct_type != "Service" else random.randint(1, 5),
        })
    return pd.DataFrame(rows)


def generate_iam_entitlements(n, fake):
    user_ids = [f"{fake.first_name()[0].lower()}{fake.last_name().lower()}" for _ in range(max(10, n // 3))]
    rows = []
    for i in range(n):
        app = random.choice(IAM_APPS)
        role = random.choice(IAM_ROLES[app])
        provisioned = date.today() - timedelta(days=random.randint(30, 1825))
        rows.append({
            "entitlement_id": i + 1,
            "user_id": random.choice(user_ids),
            "application": app,
            "role": role,
            "provisioned_date": provisioned.isoformat(),
            "last_used": (date.today() - timedelta(days=random.randint(0, 90))).isoformat() if random.random() > 0.15 else None,
            "certification_status": weighted_choice([("Certified", 0.70), ("Pending", 0.20), ("Revoked", 0.10)]),
            "risk_level": weighted_choice([("Low", 0.50), ("Medium", 0.30), ("High", 0.15), ("Critical", 0.05)]),
        })
    return pd.DataFrame(rows)


def generate_research_subjects(n, fake):
    study_ids = [f"IRB-2024-{i+1:04d}" for i in range(max(1, n // 20))]
    rows = []
    for i in range(n):
        rows.append({
            "subject_id": f"SUBJ-{uuid.uuid4().hex[:12].upper()}",
            "study_id": random.choice(study_ids),
            "cohort": random.choice(["Control", "Treatment", "Arm-A", "Arm-B"]),
            "enrollment_date": (date.today() - timedelta(days=random.randint(30, 730))).isoformat(),
            "age_at_enrollment": random.randint(18, 85),
            "sex": weighted_choice([("M", 0.48), ("F", 0.48), ("Intersex", 0.02), ("Unknown", 0.02)]),
            "race_ethnicity": weighted_choice(RACE_OPTIONS),
            "consent_status": weighted_choice([("Consented", 0.88), ("Withdrawn", 0.05), ("Screen-Failed", 0.07)]),
            "site_id": f"SITE-{random.randint(1, 5):02d}",
        })
    return pd.DataFrame(rows)


def generate_research_studies(n, fake):
    rows = []
    for i in range(n):
        start = date.today() - timedelta(days=random.randint(90, 1825))
        rows.append({
            "study_id": f"IRB-{start.year}-{i+1:04d}",
            "pi_name": f"Dr. {fake.last_name()}",
            "title": random.choice(STUDY_TITLES) if i < len(STUDY_TITLES) else fake.sentence(nb_words=10),
            "irb_status": weighted_choice([("Approved", 0.70), ("Pending", 0.10), ("Closed", 0.15), ("Suspended", 0.05)]),
            "funding_source": random.choice(["NIH", "NSF", "DoD", "Industry", "Internal"]),
            "data_classification": weighted_choice([("Controlled", 0.50), ("Restricted", 0.30), ("Public", 0.20)]),
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=random.randint(365, 1825))).isoformat() if random.random() > 0.3 else None,
        })
    return pd.DataFrame(rows)


def generate_financial_claims(n, fake):
    patient_ids = [f"SYN-{i+1:06d}" for i in range(max(10, n // 3))]
    encounter_ids = [f"ENC-{i+1:08d}" for i in range(max(10, n // 2))]
    rows = []
    for i in range(n):
        cpt, desc, base_charge = random.choice(CPT_CODES)
        charge = round(base_charge * random.uniform(0.8, 1.5), 2)
        allowed = round(charge * random.uniform(0.4, 0.9), 2)
        rows.append({
            "claim_id": f"CLM-{i+1:08d}",
            "patient_id": random.choice(patient_ids),
            "encounter_id": random.choice(encounter_ids),
            "cpt_code": cpt,
            "description": desc,
            "charge_amount": charge,
            "payer": random.choice(PAYERS),
            "member_id": f"MBR-{random.randint(100000000, 999999999)}",
            "adjudication_status": weighted_choice([("Paid", 0.65), ("Pending", 0.15), ("Denied", 0.10), ("Appealed", 0.10)]),
            "allowed_amount": allowed,
            "patient_responsibility": round(charge - allowed, 2) if random.random() > 0.1 else 0.00,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def to_csv_string(df):
    buf = io.StringIO()
    buf.write("# Generated by synth-data-gen | All data is fictional\n")
    df.to_csv(buf, index=False)
    return buf.getvalue()


def to_json_string(df):
    records = json.loads(df.to_json(orient="records", date_format="iso"))
    output = {
        "_meta": {
            "generated_by": "synth-data-gen",
            "synthetic": True,
            "record_count": len(records),
        },
        "data": records,
    }
    return json.dumps(output, indent=2, ensure_ascii=False)


def to_sql_string(df, table_name):
    cols = ", ".join(df.columns)
    lines = [f"-- Generated by synth-data-gen | All data is fictional", f"-- DO NOT use in production systems\n"]
    lines.append(f"INSERT INTO {table_name} ({cols})\nVALUES")
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
# Validator (inline version of validate_synthetic.py)
# ---------------------------------------------------------------------------

REAL_SSN_AREA = set(range(1, 900))
REAL_EMAIL_DOMAINS = {
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'aol.com',
    'icloud.com', 'mail.com', 'protonmail.com', 'live.com', 'msn.com',
}
SAFE_EMAILS = {'example.com', 'example.org', 'example.net', 'test.invalid', 'example.invalid', 'test.test', 'example.edu'}

SSN_RE = re.compile(r'\b(\d{3})-(\d{2})-(\d{4})\b')
EMAIL_RE = re.compile(r'\b[\w.+-]+@([\w-]+\.[\w.-]+)\b')
PHONE_RE = re.compile(r'\b(\d{3})[-.)]?\s*(\d{3})[-.]\s*(\d{4})\b')


def validate_text(text):
    results = {"critical": [], "warnings": [], "info": []}

    # SSN check
    for area, group, serial in SSN_RE.findall(text):
        if int(area) in REAL_SSN_AREA:
            results["critical"].append(f"Real-range SSN: {area}-{group}-{serial}")
        else:
            results["info"].append(f"Safe SSN: {area}-{group}-{serial}")

    # Email check
    for domain in EMAIL_RE.findall(text):
        d = domain.lower()
        if d in REAL_EMAIL_DOMAINS:
            results["critical"].append(f"Real email domain: @{d}")
        elif d not in SAFE_EMAILS:
            results["warnings"].append(f"Unrecognized domain: @{d}")

    # Phone check
    unsafe_phones = 0
    safe_phones = 0
    for area, exchange, number in PHONE_RE.findall(text):
        if exchange == '555' and number.startswith('01'):
            safe_phones += 1
        else:
            unsafe_phones += 1
    if unsafe_phones:
        results["warnings"].append(f"{unsafe_phones} phone(s) outside safe 555-01xx range")
    if safe_phones:
        results["info"].append(f"{safe_phones} phone(s) in safe range")

    # Deduplicate info
    seen_safe_ssn = sum(1 for m in results["info"] if m.startswith("Safe SSN"))
    results["info"] = [m for m in results["info"] if not m.startswith("Safe SSN")]
    if seen_safe_ssn:
        results["info"].insert(0, f"{seen_safe_ssn} SSN(s) in safe synthetic range")

    return results


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

DOMAIN_TABLES = {
    "Clinical / EHR": {
        "Patients": ("clinical_patients", generate_clinical_patients),
        "Encounters": ("clinical_encounters", generate_clinical_encounters),
        "Diagnoses": ("clinical_diagnoses", generate_clinical_diagnoses),
        "Lab Results": ("clinical_labs", generate_clinical_labs),
        "Clinical Notes / Dictations": ("clinical_notes", generate_clinical_notes),
    },
    "Student Records": {
        "Students": ("students", generate_student_records),
        "Course Enrollment": ("enrollment", generate_student_enrollment),
    },
    "Human Resources": {
        "Employees": ("employees", generate_hr_employees),
    },
    "Identity & Access": {
        "User Accounts": ("iam_accounts", generate_iam_accounts),
        "Entitlements": ("iam_entitlements", generate_iam_entitlements),
    },
    "Research": {
        "Research Subjects": ("research_subjects", generate_research_subjects),
        "Studies": ("research_studies", generate_research_studies),
    },
    "Financial / Billing": {
        "Claims": ("financial_claims", generate_financial_claims),
    },
}


def main():
    st.set_page_config(page_title="Synthetic Data Generator Demo", page_icon="🧪", layout="wide")

    st.title("Synthetic Data Generator Demo")
    st.caption("Interactive demo for the **synth-data-gen** Claude Code skill. All data is entirely fictional.")

    # ---- Sidebar controls ----
    st.sidebar.header("Configuration")

    domain = st.sidebar.selectbox("Domain", list(DOMAIN_TABLES.keys()))
    tables = DOMAIN_TABLES[domain]
    table_name = st.sidebar.selectbox("Table", list(tables.keys()))

    row_count = st.sidebar.slider("Rows", min_value=5, max_value=500, value=50, step=5)
    seed = st.sidebar.number_input("Random Seed", min_value=0, max_value=999999, value=42)
    output_format = st.sidebar.selectbox("Output Format", ["Table Preview", "CSV", "JSON", "SQL INSERT"])

    generate_btn = st.sidebar.button("Generate Data", type="primary", use_container_width=True)

    # ---- Domain info ----
    st.sidebar.markdown("---")
    st.sidebar.markdown("### About This Skill")
    st.sidebar.markdown(
        "The **synth-data-gen** skill generates realistic but entirely fictional data "
        "to replace production PII/PHI in dev/test environments. It ensures:\n"
        "- SSNs use the IRS test range (987-65-xxxx)\n"
        "- Emails use RFC 2606 reserved domains\n"
        "- Phones use the NANPA fictional range (555-01xx)\n"
        "- Realistic NULL distributions and edge cases\n"
        "- Diverse demographics and unicode names"
    )

    # ---- Main area ----
    if generate_btn:
        random.seed(seed)
        Faker.seed(seed)
        fake = Faker()

        tbl_key, gen_fn = tables[table_name]

        if gen_fn is None:
            st.error(
                "The Clinical Notes generator requires `clinical_notes.py` next to "
                "demo_app.py. It is included in this repository."
            )
            return

        with st.spinner(f"Generating {row_count} {table_name.lower()} records..."):
            df = gen_fn(row_count, fake)

        st.success(f"Generated {len(df)} records (seed={seed})")

        # Display based on format
        tab_preview, tab_raw, tab_validate, tab_stats = st.tabs(["Preview", "Raw Output", "Validation", "Statistics"])

        with tab_preview:
            st.dataframe(df, use_container_width=True, height=400)

            # Narrative tables: show full note text in expanders
            if "note_text" in df.columns:
                st.markdown("#### Full Note Text (first 5)")
                for _, row in df.head(5).iterrows():
                    title = f"{row['note_id']} · {row['note_type']} · {row['patient_name']}"
                    with st.expander(title):
                        st.text(row["note_text"])
                        spans = json.loads(row["phi_spans"])
                        st.caption(
                            f"{len(spans)} ground-truth PHI spans: "
                            + ", ".join(sorted({s['type'] for s in spans}))
                        )

        with tab_raw:
            if output_format == "Table Preview":
                st.info("Select CSV, JSON, or SQL from the sidebar to see raw output.")
                st.dataframe(df, use_container_width=True, height=400)
            elif output_format == "CSV":
                raw = to_csv_string(df)
                st.code(raw[:5000] + ("\n... (truncated)" if len(raw) > 5000 else ""), language="csv")
                st.download_button("Download CSV", raw, file_name=f"synthetic_{tbl_key}.csv", mime="text/csv")
            elif output_format == "JSON":
                raw = to_json_string(df)
                st.code(raw[:5000] + ("\n... (truncated)" if len(raw) > 5000 else ""), language="json")
                st.download_button("Download JSON", raw, file_name=f"synthetic_{tbl_key}.json", mime="application/json")
            elif output_format == "SQL INSERT":
                raw = to_sql_string(df, tbl_key)
                st.code(raw[:5000] + ("\n... (truncated)" if len(raw) > 5000 else ""), language="sql")
                st.download_button("Download SQL", raw, file_name=f"synthetic_{tbl_key}.sql", mime="text/sql")

        with tab_validate:
            st.subheader("PII/PHI Leakage Check")
            text_to_check = to_csv_string(df)
            results = validate_text(text_to_check)

            if results["critical"]:
                for msg in results["critical"][:10]:
                    st.error(f"CRITICAL: {msg}")
            if results["warnings"]:
                for msg in results["warnings"][:10]:
                    st.warning(f"WARNING: {msg}")
            if results["info"]:
                for msg in results["info"][:10]:
                    st.info(msg)

            if not results["critical"] and not results["warnings"]:
                st.success("All checks passed. Data appears safe for use — no real PII/PHI detected.")
            elif results["critical"]:
                st.error("Critical issues detected. DO NOT use this data.")
            else:
                st.warning("Warnings found. Review before using.")

        with tab_stats:
            st.subheader("Data Quality Statistics")

            col1, col2, col3 = st.columns(3)
            col1.metric("Total Rows", len(df))
            col2.metric("Columns", len(df.columns))
            col3.metric("Seed", seed)

            st.markdown("#### NULL Distribution")
            null_pcts = (df.isnull().sum() / len(df) * 100).round(1)
            null_df = pd.DataFrame({"Column": null_pcts.index, "NULL %": null_pcts.values})
            null_df = null_df[null_df["NULL %"] > 0]
            if len(null_df) > 0:
                st.bar_chart(null_df.set_index("Column"))
            else:
                st.info("No NULL values in this dataset.")

            st.markdown("#### Column Details")
            desc = df.describe(include="all").T
            st.dataframe(desc, use_container_width=True)

    else:
        # Landing state
        st.markdown("---")
        st.markdown("### How to Use")
        st.markdown(
            "1. **Pick a domain** from the sidebar (Clinical, Student Records, HR, IAM, Research, Financial)\n"
            "2. **Select a table** within that domain\n"
            "3. **Configure** row count, seed, and output format\n"
            "4. **Click Generate** to create synthetic data\n"
            "5. **Review** the preview, raw output, validation results, and statistics"
        )

        st.markdown("### Supported Domains")
        cols = st.columns(3)
        for i, (domain_name, tables_dict) in enumerate(DOMAIN_TABLES.items()):
            with cols[i % 3]:
                st.markdown(f"**{domain_name}**")
                for t in tables_dict:
                    st.markdown(f"- {t}")

        st.markdown("---")
        st.markdown("### Safety Guarantees")
        st.markdown(
            "| Identifier | Safe Range | Why |\n"
            "|---|---|---|\n"
            "| SSN | `987-65-xxxx` | IRS test range, never assigned to real people |\n"
            "| Email | `@example.com` | RFC 2606 reserved domains |\n"
            "| Phone | `555-01xx` | NANPA reserved for fiction |\n"
            "| MRN | `MRN-224xxxx` | Synthetic prefix, no real system overlap |\n"
            "| Student ID | `SYN-xxxxxx` | Explicit synthetic prefix |"
        )


if __name__ == "__main__":
    main()
