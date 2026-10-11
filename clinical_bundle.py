#!/usr/bin/env python3
"""
Clinical Bundle Generator — referentially-linked synthetic EHR dataset
(compat shim)
======================================================================
The canonical implementation lives in ``synthgen.bundle``. This shim keeps the
historical ``python clinical_bundle.py`` entry point and import path working.

Run:
    python clinical_bundle.py -n 100 --validate --zip
    python clinical_bundle.py -n 250 --format fhir
"""

import sys

from synthgen.bundle import *  # noqa: F401,F403 — re-export public API
from synthgen.bundle import (CONDITION_LABS, LOCALES, TABLE_ORDER,  # noqa: F401
                             apply_dirty_mode, build_manifest,
                             check_integrity, generate_clinical_cohort, main)

if __name__ == "__main__":
    sys.exit(main())
