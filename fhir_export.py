#!/usr/bin/env python3
"""FHIR R4 export (compat shim) — canonical implementation: synthgen.fhir."""

from synthgen.fhir import (cohort_to_bundles, document_reference_resource,  # noqa: F401
                           encounter_resource, medication_request_resource,
                           observation_resource, patient_resource,
                           practitioner_resource, condition_resource)

__all__ = [
    "patient_resource", "practitioner_resource", "encounter_resource",
    "condition_resource", "observation_resource", "document_reference_resource",
    "medication_request_resource", "cohort_to_bundles",
]
