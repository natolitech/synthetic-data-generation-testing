# Improvement Plan — Synthetic Data Generation Toolkit

Status: **Phase 1 delivered** (clinical notes/dictations, `run.sh`, ground-truth PHI spans).
Everything below is a living roadmap; items are ordered by value-to-effort within each phase.

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

## Phase 2 — Usability (highest user-facing value)

1. **Referentially-linked bundles.** "Generate full dataset" produces patients → encounters → diagnoses → labs → notes that all reference the *same* patient pool and a consistent timeline (admit < discharge < note datetime). Today each table invents its own ID pool, so cross-table joins in the demo app are fiction.
2. **In-app generator override.** In `schema_app.py`, let users click a column in the inferred-generator table and swap it (e.g., force `department` → custom list) before generating. Persist overrides per schema in `st.session_state`.
3. **FHIR R4 / HL7 v2 output** in both apps. The format templates already exist in `synth-data-gen/references/format-templates.md`; the apps only emit CSV/JSON/SQL. FHIR `DocumentReference` for notes and `Patient`/`Encounter` resources would make this a real interoperability-test fixture generator.
4. **Volume handling.** Raise the 500-row cap; chunk generation with a progress bar; warn on memory-heavy formats. Target: 50k rows in the UI, 1M+ via CLI.
5. **Download-all / zip export** for multi-table runs (schema app + bundle mode).
6. **Generation manifest.** Sidecar `manifest.json` per output directory: seed, schema hash, tool versions, timestamp, row counts — so any dataset can be reproduced or attributed later.

## Phase 3 — Data realism

7. **Correlated columns.** Diagnoses ↔ medications ↔ abnormal labs ↔ note narrative should agree (the notes generator already does this internally; extend the model to tabular generators).
8. **Temporal consistency.** DOB ↔ age, admit ↔ discharge ordering, medication start dates after diagnosis dates.
9. **More narrative PHI flavors**: radiology reports, phone-call transcripts (scheduling/Referral), patient portal messages, behavioral health notes (42 CFR Part 2 sensitivity testing), non-English dictation fragments.
10. **Locale packs.** Non-US names/phones/postcodes with per-region safe ranges (UK, EU, CA) behind a `--locale` flag.
11. **Realistic dirty data mode.** Duplicate rows, mixed date formats, trailing whitespace, inconsistent casing, OCR-ish artifacts in notes — the things that break pipelines in production.

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
