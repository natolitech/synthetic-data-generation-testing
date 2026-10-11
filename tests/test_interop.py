"""FHIR + HL7 export tests."""

import base64
import random

from faker import Faker

from synthgen.bundle import generate_clinical_cohort
from synthgen.fhir import cohort_to_bundles
from synthgen.hl7 import cohort_to_hl7_messages


def _cohort(seed=42, n=30):
    random.seed(seed)
    Faker.seed(seed)
    return generate_clinical_cohort(n, Faker())


def _walk_refs(obj, refs):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "reference" and isinstance(v, str) and "/" in v and not v.startswith("http"):
                refs.append(v)
            _walk_refs(v, refs)
    elif isinstance(obj, list):
        for item in obj:
            _walk_refs(item, refs)


class TestFHIR:
    def test_combined_bundle_references_resolve(self):
        _, bundle = next(cohort_to_bundles(_cohort()))
        ids = {f'{e["resource"]["resourceType"]}/{e["resource"]["id"]}' for e in bundle["entry"]}
        refs = []
        _walk_refs(bundle, refs)
        assert refs, "expected internal references"
        dangling = [r for r in refs if r not in ids]
        assert dangling == [], dangling[:5]

    def test_expected_resource_types(self):
        _, bundle = next(cohort_to_bundles(_cohort()))
        types = {e["resource"]["resourceType"] for e in bundle["entry"]}
        assert {"Patient", "Practitioner", "Encounter", "Condition",
                "MedicationRequest", "Observation", "DocumentReference"} <= types

    def test_document_reference_payload_decodes(self):
        for fname, bundle in cohort_to_bundles(_cohort(n=10)):
            if "clinical_notes" not in fname:
                continue
            dr = next(e["resource"] for e in bundle["entry"]
                      if e["resource"]["resourceType"] == "DocumentReference")
            data = dr["content"][0]["attachment"]["data"]
            text = base64.b64decode(data).decode("utf-8")
            assert "Patient:" in text or "BEGIN DICTATION" in text

    def test_bundle_meta(self):
        _, bundle = next(cohort_to_bundles(_cohort(n=5)))
        assert bundle["resourceType"] == "Bundle"
        assert bundle["total"] == len(bundle["entry"])


class TestHL7:
    def test_messages_well_formed(self):
        files = dict(cohort_to_hl7_messages(_cohort(n=25)))
        adt = files["synthetic_adt_messages.hl7"].split("\n\n")
        for msg in adt:
            segs = msg.split("\n")
            assert segs[0].startswith("MSH|^~\\&|"), "MSH must be first with encoding chars"
            assert "ADT^A01" in segs[0]
            assert any(s.startswith("PID|") for s in segs)
            assert any(s.startswith("PV1|") for s in segs)

    def test_oru_has_obx(self):
        files = dict(cohort_to_hl7_messages(_cohort(n=40)))
        oru = files["synthetic_oru_lab_messages.hl7"]
        assert "ORU^R01" in oru.split("\n")[0]
        assert "\nOBX|" in oru

    def test_no_unescaped_delimiters_from_content(self):
        # content fields (names/cities) must not inject raw delimiters
        files = dict(cohort_to_hl7_messages(_cohort(n=60)))
        for text in files.values():
            for msg in text.split("\n\n"):
                for seg in msg.split("\n"):
                    if seg.startswith(("PID|", "PV1|")):
                        # every segment must have consistent field structure:
                        # no empty trailing garbage from injected '|'
                        assert not seg.endswith("|" * 3)
