"""Phase 5 depth tests: NPI Luhn, MRN checks, de-id harness, FHIR checker, HTML."""

import json
import random

from faker import Faker

from synthgen.deid import (DeidScore, changed_regions, html_report,
                           regex_baseline, score_note, score_scrubber)
from synthgen.fhir_validate import validate_fhir
from synthgen.notes import safe_npi
from synthgen.validators import is_valid_npi, npi_check_digit, validate


class TestNpiLuhn:
    def test_canonical_example_valid(self):
        # CMS documentation example NPI
        assert is_valid_npi("1234567893")

    def test_tampered_invalid(self):
        assert not is_valid_npi("1234567894")
        assert not is_valid_npi("12345678931")  # too long
        assert not is_valid_npi("12345678a3")   # non-digit

    def test_check_digit_roundtrip(self):
        assert npi_check_digit("123456789") == "3"

    def test_generated_npis_are_checksum_valid(self):
        assert all(is_valid_npi(safe_npi()) for _ in range(100))

    def test_generated_npis_keep_safe_prefix(self):
        assert all(safe_npi().startswith("9") for _ in range(50))

    def test_validator_flags_real_npi(self):
        res = validate("Provider NPI: 1234567893")
        assert any("REAL NPI" in c for c in res["critical"])

    def test_validator_accepts_safe_npi(self):
        res = validate(f"Provider NPI: {safe_npi()}")
        assert res["critical"] == []
        assert any("Luhn" in i for i in res["info"])

    def test_validator_warns_bad_checksum(self):
        res = validate("NPI: 9123456780")  # wrong check digit
        assert any("checksum" in w for w in res["warnings"])


class TestMrnCheck:
    def test_synthetic_mrn_passes(self):
        assert validate("MRN-2240001 seen")["warnings"] == []

    def test_foreign_mrn_warns(self):
        res = validate("MRN-8881234 seen")
        assert any("MRN" in w for w in res["warnings"])


class TestDeidHarness:
    def _note(self, text, spans):
        return {"note_id": "N1", "text": text, "phi_spans": spans}

    def test_changed_regions_exact(self):
        assert changed_regions("hello world", "hello [X]") == [(6, 11)]
        assert changed_regions("same", "same") == []

    def test_perfect_scrubber_scores_perfectly(self):
        text = "Patient John Smith MRN-2240001 called"
        spans = [{"type": "PATIENT", "text": "John Smith", "start": 8, "end": 18},
                 {"type": "MRN", "text": "MRN-2240001", "start": 19, "end": 30}]

        def perfect(t, _spans=spans):
            out = list(t)
            for s in sorted(_spans, key=lambda s: -s["start"]):
                out[s["start"]:s["end"]] = ["*"] * (s["end"] - s["start"])
            return "".join(out)

        score = score_scrubber([self._note(text, spans)], perfect)
        assert score.recall == 1.0
        # adjacent spans: the 1-char gap between them counts as collateral
        assert score.precision >= 0.95
        assert score.f1 >= 0.97

    def test_identity_scrubber_zero_recall(self):
        text = "Patient John Smith called"
        spans = [{"type": "PATIENT", "text": "John Smith", "start": 8, "end": 18}]
        score = score_scrubber([self._note(text, spans)], lambda t: t)
        assert score.recall == 0.0
        assert score.spans_detected == 0

    def test_over_redaction_hurts_precision(self):
        text = "Nothing sensitive here at all"
        spans = [{"type": "PATIENT", "text": "sensitive", "start": 8, "end": 17}]
        score = score_scrubber([self._note(text, spans)], lambda t: "[X]")
        assert score.recall == 1.0
        assert score.precision < 1.0
        assert score.collateral_chars > 0

    def test_score_note_misses_reported(self):
        text = "Patient John Smith called"
        spans = [{"type": "PATIENT", "text": "John Smith", "start": 8, "end": 18}]
        r = score_note(text, "Patient [REDACTED] called", spans)
        assert len(r["detected"]) == 1 and not r["missed"]
        r2 = score_note(text, text, spans)
        assert len(r2["missed"]) == 1

    def test_baseline_on_generated_notes(self):
        random.seed(42)
        Faker.seed(42)
        from synthgen.notes import generate_notes_dataframe
        df = generate_notes_dataframe(20, Faker(), "progress_note", dictation_ratio=0.3)
        notes = [{"note_id": r["note_id"], "text": r["note_text"],
                  "phi_spans": json.loads(r["phi_spans"])}
                 for _, r in df.iterrows()]
        score = score_scrubber(notes, regex_baseline)
        # structured identifiers caught...
        assert score.per_type["MRN"]["detected"] == score.per_type["MRN"]["total"]
        assert score.per_type["SSN"]["detected"] == score.per_type["SSN"]["total"]
        # ...names are the known blind spot
        assert score.per_type["PATIENT"]["detected"] < score.per_type["PATIENT"]["total"]
        assert 0.2 <= score.recall <= 0.95
        assert score.precision >= 0.5

    def test_html_report_contains_metrics(self):
        score = DeidScore()
        score.notes_scored = 3
        score.spans_total = score.spans_detected = 10
        score.edits_total = score.edits_on_phi = 10
        score.per_type = {"PATIENT": {"detected": 5, "total": 5}}
        html = html_report(score, "test scrubber")
        assert "Recall" in html and "100.0%" in html and "PATIENT" in html


class TestFhirChecker:
    def _bundle(self, n=15, seed=42):
        random.seed(seed)
        Faker.seed(seed)
        from synthgen.bundle import generate_clinical_cohort
        from synthgen.fhir import cohort_to_bundles
        cohort = generate_clinical_cohort(n, Faker())
        _, bundle = next(cohort_to_bundles(cohort))
        return bundle

    def test_generated_bundle_passes(self):
        rep = validate_fhir(self._bundle())
        assert rep.ok, rep.errors[:5]

    def test_missing_required_element_fails(self):
        bundle = self._bundle()
        for e in bundle["entry"]:
            if e["resource"]["resourceType"] == "Encounter":
                del e["resource"]["status"]
                break
        rep = validate_fhir(bundle)
        assert not rep.ok and any("status" in err for err in rep.errors)

    def test_invalid_status_fails(self):
        bundle = self._bundle()
        for e in bundle["entry"]:
            if e["resource"]["resourceType"] == "Observation":
                e["resource"]["status"] = "finalish"
                break
        rep = validate_fhir(bundle)
        assert any("invalid status" in err for err in rep.errors)

    def test_dangling_reference_fails(self):
        bundle = self._bundle()
        bundle["entry"][0]["resource"]["managingOrganization"] = {
            "reference": "Organization/NOPE"}
        rep = validate_fhir(bundle)
        assert any("dangling" in err for err in rep.errors)

    def test_bad_id_format_fails(self):
        bundle = self._bundle()
        bundle["entry"][0]["resource"]["id"] = "bad id with spaces!"
        rep = validate_fhir(bundle)
        assert any("invalid id" in err for err in rep.errors)

    def test_non_fhir_input_rejected(self):
        rep = validate_fhir({"foo": 1})
        assert not rep.ok


class TestHtmlReport:
    def test_to_html_renders_statuses(self):
        import validate_synthetic as vs
        r = vs.ValidationResult()
        r.add_critical("boom <script>")
        r.add_warning("careful")
        r.add_info("fine")
        r.stats["Rows"] = 10
        html = r.to_html(source_path="x.csv")
        assert "FAIL" in html
        assert "&lt;script&gt;" in html  # escaped
        assert "Rows" in html and "10" in html

    def test_pass_report(self):
        import validate_synthetic as vs
        r = vs.ValidationResult()
        html = r.to_html()
        assert "PASS" in html
