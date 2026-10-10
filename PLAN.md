# Improvement Plan — Synthetic Data Generation Toolkit

Status: **Phase 1 + 2 + 3 delivered.** Phase 3 shipped: correlated medications table +
condition-biased labs, DOB↔age reconciliation, four new narrative PHI types
(radiology, behavioral health w/ 42 CFR Part 2, portal messages, call transcripts),
locale packs (us/uk/ca/eu), and dirty-data mode. Remaining polish and Phases 4–5 below.
Everything is a living roadmap; items are ordered by value-to-effort.

---

## What was just delivered (Phase 1)

| Item | Detail |
|------|--------|
| **Clinical notes & dictations** | `clinical_notes.py` generates 6 note types (progress, H&P, discharge summary, ED, telehealth, procedure) in two renderings: transcribed note or raw dictation transcript (spoken punctuation, disfluencies, `[inaudible]`, corrections). |
| **Ground-truth PHI spans** | Every note ships with character-offset annotations (`PATIENT`, `MRN`, `DOB`, `SSN`, `PHONE`, `ADDRESS`, `PROVIDER`, `NPI`, `DATE`, `ENCOUNTER`, `CONTACT`, `ICD10`) so de-identification pipelines can be scored for recall/precision — not just eyeballed. `--ground-truth` writes a sidecar JSON. |
| **Schema integration** | `note_text`, `dictation_text`, `progress_note`, `hpi`, `chief_complaint`, `note_type`, `author`, `transcription_status` (and friends) are now mapped semantically in both `schema_app.py` and `generate_from_schema.py`, with length-aware truncation for `VARCHAR(n)`. |
| **Demo app** | New "Clinical Notes / Dictations" table in the Clinical/EHR domain, with per-note expanders showing full text + PHI span counts. |
| **`run.sh`** | One entry point for everything: `demo`, `schema`, `notes`, `gen`, `patient`, `validate`, `install-skill`, `doctor`, `update`. Auto-finds a Python with the right deps. |

---

## Phase 2 — Usability ✅ delivered (Oct 2026)

1. **Referentially-linked bundles.** ✅ `clinical_bundle.py` generates patients → encounters → diagnoses → labs → notes from one shared pool: encounters reference real patients, note identity/dx/timeline match their encounter (DOB < admit < discharge, note time inside the window), and `check_integrity()` verifies it on every run. Exposed in the demo app as "Full Dataset — linked (5 tables)".
2. **In-app generator override.** ✅ The schema-app preview table is now an editable grid — swap any column's generator via dropdown (~30 registered generators incl. note text, dictation, safe SSN/phone). PK/FK columns stay locked to preserve referential integrity; overrides persist in `st.session_state`.
3. **FHIR R4 / HL7 v2 output.** ✅ `fhir_export.py` (Patient, Practitioner, Encounter, Condition, Observation, DocumentReference with base64 note payloads — all internal references resolve inside the combined Bundle) and `hl7_export.py` (ADT^A01 + ORU^R01 v2.5.1, delimiter-escaped). Available via `--format fhir|hl7` on the bundle CLI and as a FHIR download in the demo app's bundle mode. *Not* wired for arbitrary DDL schemas (resource mapping is clinical-specific by design).
4. **Volume handling.** ✅ Row cap raised 500 → 5000 in both apps; CLI already unbounded. ⚠️ Remaining: chunked generation with a progress bar for very large note volumes.
5. **Download-all / zip export.** ✅ Demo app bundle mode and schema-app all-tables mode both offer zip downloads (CSVs + manifest; demo zip also includes PHI ground truth). Bundle CLI has `--zip`.
6. **Generation manifest.** ✅ Bundle CLI always writes `manifest.json` (seed, row counts, tool versions, timestamp); `generate_from_schema.py --manifest` adds schema SHA-256 for exact reproduction.

**Phase 2 leftovers (small):** progress bars for >1k note generation; FHIR output for non-clinical domains (out of scope by design); manifest download button in single-table app modes.

## Phase 3 — Data realism ✅ delivered (Oct 2026)

7. **Correlated columns.** ✅ New `medications` table in the bundle: meds drawn from the encounter's actual diagnoses with temporal consistency (`start_date` ≥ matching dx onset, ≤ admit; `end_date` ≥ start or NULL; status Active/Discontinued/Completed). Labs are now condition-correlated with biased values (diabetes → HbA1c/glucose high ~65% of the time, pneumonia → WBC high, etc.). `check_integrity()` verifies med↔dx correlation and all temporal orderings every run.
8. **Temporal consistency.** ✅ DOB↔age reconciliation in both schema tools (`_reconcile_age`): a table with both `dob` and `age` columns derives age from DOB. Med onset ordering above; note-in-encounter-window checks shipped in Phase 2.
9. **More narrative PHI flavors.** ✅ Four new note types: **radiology report** (exam/technique/findings/impression correlated with the dx, dictatable), **behavioral health note** (42 CFR Part 2 banners for SUD, MSE, crisis resources — gated to encounters with BH/SUD dx), **patient portal message** (patient-written, typos, DOB/phone/address PHI), **phone call transcript** (identity-verification dialog). Non-English (Spanish) interpreter/family-translator quotes appear across note types. Two new conditions (GAD F41.1, alcohol use disorder in remission F10.21) power the BH/SUD scenarios.
10. **Locale packs.** ✅ `--locale us|uk|ca|eu` on the bundle CLI + demo-app bundle mode: localized Faker names/addresses, region-appropriate fictional ranges (UK Ofcom `01632 960xxx` + `ZZ99` postcodes; Canada NANP phones + unassigned `Z` FSA postcodes; EU synthetic `+49 30 5550-xxx`), per-locale language weights, NULL ssn for non-US patients. Manifest records the locale.
11. **Realistic dirty data mode.** ✅ `--dirty` on the bundle CLI + demo-app toggle: ~1% duplicate patient rows, mixed date formats (ISO/MM-DD-YYYY/YYYYMMDD), whitespace/casing drift, ZIP+4 mixing, empty-string-vs-NULL, OCR-ish character damage in ~6% of notes. Applied strictly AFTER integrity verification; manifest records `dirty_mode: true`.

**Phase 3 leftovers (small):** locale support for the standalone notes CLI and schema-driven tools (US-centric by design for now); more locales (AU, JP); dirty-mode dial (`--dirty-severity`).

## Phase 4 — Architecture & quality

12. **Extract a shared package** (`synthgen/`): schema parser, semantic mapper, validator, and domain pools currently live in 2–3 parallel copies (root + skill). Keep the skill self-contained but *generate* its copies from the package via a `make sync-skill` build step instead of hand-editing both.
13. **Tests.** Pytest golden-file tests (seeded outputs must be byte-stable), schema-parser unit tests, validator round-trips (generate → validate must always pass). Target the invariant: *validator never flags generator output*.
14. **CI (GitHub Actions).** Lint (ruff), run tests, generate fixtures and validate them on every push. Prevents "works on my machine" drift between the app and skill copies.
15. **Typed, documented API.** Docstrings + type hints throughout; the generators become importable building blocks, not just scripts.
16. **Packaging.** `pyproject.toml` + console script (`synthgen generate|validate|notes`) published to PyPI; skill install becomes `pip install synthgen[skill]`-friendly.
17. **Docker.** `Dockerfile` + compose for the Streamlit apps — zero-Python demos and CI-friendly screenshots.

## Phase 5 — Validator depth

18. **NPI checksum** (Luhn) validation instead of prefix-only checks; MRN pattern check.
19. **De-id scoring harness.** Given notes + ground-truth spans, score any scrubber: recall, precision, F1 per PHI type. Turns this repo into a de-identification benchmarking tool.
20. **HTML validation report** with per-column breakdown, suitable for compliance review artifacts.
21. **JSON Schema validation** for FHIR output conformance.

---

## Quick wins not yet scheduled (pick up anytime)

- `--quiet`/`--verbose` flags and proper logging across CLIs
- README screenshots of both apps (big usability boost for newcomers)
- `.gitignore` the `synthetic_output/` fixtures or move them to `examples/` with intent
- Type-check `dictation_ratio` bounds (0.0–1.0) in the CLI
- `files.zip` at repo root looks stale — verify it's still needed or delete
