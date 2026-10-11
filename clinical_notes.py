#!/usr/bin/env python3
"""
Clinical Notes & Dictation Generator (compat shim)
===================================================
The canonical implementation lives in ``synthgen.notes``. This shim keeps the
historical ``python clinical_notes.py`` entry point and import path working.

Run:
    python clinical_notes.py -n 20 --validate
    python clinical_notes.py -n 50 -t dictation_transcript -f txt --ground-truth
"""

import sys

from synthgen.notes import *  # noqa: F401,F403 — re-export public API
from synthgen.notes import (BH_CONDITIONS, CONDITIONS, NON_DICTATABLE,  # noqa: F401
                            NOTE_LABELS, NOTE_TYPES, SPANISH_SNIPPETS,
                            NoteBuilder, build_note, generate_clinical_notes,
                            generate_note, generate_notes_dataframe,
                            make_context, main)

if __name__ == "__main__":
    sys.exit(main())
