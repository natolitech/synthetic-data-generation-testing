# Glossary — Acronyms & Synthetic-Data Terminology

Every abbreviation, clinical code, standard, and project-specific term used in
this repo. If you're new to healthcare data, synthetic data, or both — start here.

---

## Privacy & compliance

| Term | Meaning |
|------|---------|
| **PII** | Personally Identifiable Information — any data that can identify a person (names, emails, SSNs, phone numbers, addresses). |
| **PHI** | Protected Health Information — PII in a healthcare context: demographics tied to care, diagnoses, notes, MRNs, dates of service. Regulated under HIPAA. |
| **HIPAA** | Health Insurance Portability and Accountability Act (US, 1996) — the law governing PHI handling. |
| **42 CFR Part 2** | US federal rule giving *substance use disorder* (SUD) records stricter protection than general HIPAA. Redisclosure requires written consent. Our behavioral-health notes carry explicit Part 2 banners so you can test special-handling logic. |
| **FERPA** | Family Educational Rights and Privacy Act — governs student records (why the Student domain exists). |
| **De-identification** | Removing/transforming PHI from text or data. A *scrubber* is a de-identification program; this repo can **score** scrubbers (see De-id harness below). |
| **Safe range** | A number/string range officially reserved for fiction or testing that can never collide with a real person's identifier — the foundation of this project (see table below). |

## Identifiers & clinical codes

| Term | Meaning |
|------|---------|
| **SSN** | Social Security Number (US). Synthetic output uses the IRS test range `987-65-xxxx` only. |
| **MRN** | Medical Record Number — a hospital's internal patient identifier. Ours always use the `MRN-224xxxx` pattern. |
| **NPI** | National Provider Identifier — a 10-digit US provider ID with a Luhn **check digit computed over the prefix `80840` + first 9 digits** (CMS rule). We generate checksum-**valid** NPIs starting with `9` (safe range; issued NPIs start with `1`), so they pass NPI format checks without being real. |
| **ICD-10** | International Classification of Diseases, 10th revision — diagnosis codes (`E11.9` = type 2 diabetes). |
| **CPT** | Current Procedural Terminology — billing codes for procedures/visits (`99213` = office visit). |
| **LOINC** | Logical Observation Identifiers Names and Codes — lab/test codes (`4548-4` = HbA1c). Also used for document-type codes (`34117-2` = progress note). |
| **dx** | Shorthand for diagnosis. "Principal dx" = the primary reason for the encounter. |
| **DOB** | Date of birth. |

## Clinical vocabulary used by the note generators

| Term | Meaning |
|------|---------|
| **EHR** | Electronic Health Record (Epic, Cerner, …). |
| **SOAP** | Subjective / Objective / Assessment / Plan — the standard progress-note structure. |
| **H&P** | History & Physical — the admission workup note. |
| **HPI** | History of Present Illness (part of an H&P). |
| **CC** | Chief Complaint — the patient's stated reason for the visit. |
| **PMH** | Past Medical History. |
| **ROS** | Review of Systems. |
| **MSE** | Mental Status Exam (behavioral-health notes). |
| **PHQ-9 / GAD-7** | Standard depression / anxiety screening questionnaires (scored 0–27 and 0–21). |
| **ED** | Emergency Department. |
| **AMA** | Against Medical Advice (a discharge disposition). |
| **LOS** | Length of Stay. |
| **EBL** | Estimated Blood Loss (procedure notes). |
| **Vitals shorthand** | BP (blood pressure), HR (heart rate), RR (respiratory rate), SpO₂ (oxygen saturation), Temp (temperature). |
| **Labs in output** | HbA1c (3-month glucose average — our generator biases it high for diabetic patients), WBC (white blood cells — high in infection), BUN/Creatinine (kidney), TSH (thyroid), Na/K (electrolytes). |
| **Dictation** | Physicians historically speak notes into a recorder; an ASR (speech recognition) system or transcriptionist converts them to text. Our "raw dictation" rendering mimics ASR output: spoken punctuation ("period", "comma"), "new paragraph" commands, disfluencies ("um", "uh"), `[inaudible]` markers, and mid-sentence corrections. |

## Interoperability standards (FHIR & HL7)

| Term | Meaning |
|------|---------|
| **FHIR** | Fast Healthcare Interoperability Resources — the modern HL7 API standard for health data, as JSON. **R4** is version 4. |
| **FHIR resource** | A typed JSON object: `Patient`, `Practitioner`, `Encounter`, `Condition` (diagnosis), `Observation` (lab result), `MedicationRequest`, `DocumentReference` (a note document, note text carried as base64). |
| **FHIR Bundle** | A JSON envelope holding many resources with cross-references (`"reference": "Patient/SYN-000001"`). Our combined bundle has **zero dangling references** — validated by `synthgen fhir-check` and tests. |
| **US Core** | The US profile/conformance rules on top of base FHIR (why our Patient resources carry `meta.profile`). |
| **HL7 v2** | The older pipe-delimited messaging standard still ubiquitous in hospital interfaces. |
| **ADT^A01** | "Admit/notify" HL7 message (patient admitted). Segments: **MSH** (header), **EVN** (event), **PID** (patient identification), **PV1** (patient visit), **IN1** (insurance). |
| **ORU^R01** | HL7 observation-result message (lab results). Adds **OBR** (order) and **OBX** (result) segments; `|` separates fields, `^` components, `~` repeats. |
| **BCP-47** | Language tag standard (`es` = Spanish) used in FHIR `communication.language`. |
| **CDCREC** | CDC race/ethnicity code system used in HL7 PID segments. |

## Reserved ranges — why each "safe" value is safe

| Identifier | Synthetic pattern | Why it can't be real |
|------------|-------------------|----------------------|
| SSN | `987-65-xxxx` | IRS test range — never assigned |
| Phone (US/CA) | `555-01xx` | NANP reserves `555-0100–0199` for fiction |
| Phone (UK) | `01632 960xxx` | Ofcom "drama range" for TV/fiction |
| Phone (EU) | `+49 30 5550-xxx` | Synthetic pattern (documented convention of this repo) |
| Email | `@example.com`, `@example.org`, `@test.invalid`, any `*.example.com`, reserved TLDs | RFC 2606 reserves these domains/TLDs (`.example`, `.invalid`, `.test`, `.localhost`) |
| IP address | `192.0.2.x`, `198.51.100.x`, `203.0.113.x` | RFC 5737 documentation ranges |
| MRN | `MRN-224xxxx` | Project-owned synthetic prefix |
| Patient/Student/Encounter/Note IDs | `SYN-`, `ENC-`, `NOTE-` prefixes | Explicit synthetic prefixes |
| NPI | `9xxxxxxxxx` **with valid Luhn check digit** | Issued NPIs start with `1`; 9-prefix + valid checksum passes format checks but can't be an assigned NPI |
| Credit card | `4242424242424242` | Stripe's published test card |
| UK postcode | `ZZ99 9xx` | UK/NHS test-data convention |
| Canadian postal code | `Z1A 1B1` style | Canadian postal FSAs beginning with `Z` are unassigned |
| Insurance group # | `987654321` | Placeholder used in HL7 IN1 test messages |

## Data-engineering terms

| Term | Meaning |
|------|---------|
| **DDL** | Data Definition Language — SQL `CREATE TABLE` statements describing a schema. Paste yours into `schema_app.py`. |
| **PK / FK** | Primary Key / Foreign Key. FK integrity = child rows only reference parent rows that exist (our bundle generator and its `check_integrity()` guarantee this). |
| **NULL** | SQL "no value". Real datasets have gaps, so we inject realistic NULL rates (0% required fields, 7–12% optional, ~38% soft-delete/notes). |
| **Seed** | Integer that initializes the RNG. Same seed + same code = identical output (determinism). Recorded in every manifest. |
| **Manifest** | `manifest.json` sidecar written with each run: seed, row counts, tool versions, timestamp, schema SHA-256 — everything needed to reproduce a dataset. |
| **ISO-8601** | International date/time format (`2026-10-11T14:30:00`). Default for all our timestamps. |
| **CSV / JSON / SQL INSERT / Parquet** | Supported output formats (CSV with a `#` synthetic-marker header, JSON wrapped in `_meta.synthetic`, SQL as `INSERT INTO ...` statements). |

## Machine-learning / de-identification terms

| Term | Meaning |
|------|---------|
| **ASR** | Automatic Speech Recognition — turns dictation audio into (messy) text. |
| **NER** | Named Entity Recognition — ML models that find names/dates/IDs in text; a common scrubber technology. |
| **OCR** | Optical Character Recognition — scanned-document text; notoriously introduces character damage (our dirty mode simulates this: `rn→m`, `cl→d`). |
| **Ground-truth span** | A annotated PHI location: `{type, text, start, end}` — exact character offsets of each PHI instance in a note. Our generators emit these alongside the text because they *constructed* the text from labeled segments. |
| **Recall** | Of all true PHI spans, the fraction your scrubber caught. Low recall = leaks. |
| **Precision** | Of everything your scrubber redacted, the fraction that was actually PHI. We measure this **per character**: bluntly redacting a whole document scores low precision even at 100% recall. |
| **F1** | Harmonic mean of recall and precision. |
| **Collateral (over-redaction)** | Non-PHI characters your scrubber destroyed. High collateral destroys clinical meaning while technically "safe". |
| **De-id harness** | `python -m synthgen deid` — scores any scrubber against ground-truth spans and reports the metrics above per PHI type. |

## Project-specific terms

| Term | Meaning |
|------|---------|
| **synthgen** | The canonical Python package containing all generation logic (`schema`, `generators`, `notes`, `bundle`, `fhir`, `hl7`, `validators`, `deid`, …). |
| **Skill** | The `synth-data-gen/` directory — a self-contained Claude Code plugin whose scripts are **generated** from the package by `make sync-skill`. |
| **Bundle (clinical bundle)** | The linked 6-table dataset: patients → encounters → diagnoses / medications / labs / notes, all referencing one shared patient pool. |
| **Cohort** | One run's set of patients and everything linked to them. |
| **Note type** | One of 10 narrative formats: progress note, history & physical, discharge summary, ED note, telehealth note, procedure note, radiology report, behavioral health note, patient portal message, phone call transcript. |
| **Dictation ratio** | Fraction of notes rendered as raw dictation transcripts instead of transcribed notes (default 0.35). |
| **NON_DICTATABLE** | Note types never rendered as dictation (portal messages are patient-written; call transcripts are already audio→text). |
| **Locale pack** | `--locale us|uk|ca|eu`: localized names/addresses/phones with region-appropriate safe ranges. Non-US patients get NULL SSN (no safe range exists). |
| **Dirty mode** | `--dirty`: realistic data-quality damage — duplicate rows, mixed date formats, whitespace/casing drift, ZIP+4, empty-string-vs-NULL, OCR-ish note damage. Applied *after* integrity verification. |
| **Edge-case names** | ~8% of records use tricky names (O'Brien, García-López, 李王小明, van der Berg) so unicode/quote handling gets tested. |
| **Drift gate** | CI step (`make check-sync`) that fails if the skill's generated copies diverge from the package. |
| **Invariant suite** | Tests asserting *the validator never flags generator output* across every generator/format/locale — the project's core safety property. |
| **Frozen clock** | `synthgen.clock` lets tests freeze time so seeded runs are byte-identical (determinism testing). |
| **Validator exit codes** | 0 = clean, 1 = warnings (review), 2 = critical (do not use), 3 = schema/usage error. |
