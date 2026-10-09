#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run.sh — single entry point for the synthetic-data-generation toolkit
#
# Usage:   ./run.sh <command> [extra flags passed through to the command]
#
# Commands:
#   demo               Launch the domain-based Streamlit app (demo_app.py)
#   schema             Launch the schema-driven Streamlit app (schema_app.py)
#   notes              Generate clinical notes / dictations (clinical_notes.py)
#   gen                Schema-driven CLI generator (generate_from_schema.py)
#   patient            Standalone patient generator (example_patient_generator.py)
#   validate <path>    Run PII/PHI validation on a file or directory
#   install-skill      Install the synth-data-gen Claude Code skill
#   doctor             Check environment and dependencies
#   update             Fast-forward pull from origin/main
#
# Environment:
#   PYTHON   Python interpreter to use (default: auto-detected, needs
#            faker + pandas + streamlit)
#   PORT     Streamlit port (default: 8501 / 8502)
#
# Examples:
#   ./run.sh demo
#   ./run.sh notes -n 50 --validate --ground-truth
#   ./run.sh gen schema/ --rows 200 --format sql --validate
#   ./run.sh validate synthetic_output/
#   PYTHON=/usr/bin/python3 ./run.sh demo
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- locate a Python with the required deps ----------------------------------
find_python() {
    local candidates=()
    [[ -n "${PYTHON:-}" ]] && candidates+=("$PYTHON")
    candidates+=("python3" "python")
    for c in "${candidates[@]}"; do
        if command -v "$c" >/dev/null 2>&1 \
           && "$c" -c "import faker, pandas, streamlit" >/dev/null 2>&1; then
            command -v "$c"
            return 0
        fi
    done
    return 1
}

need_deps() {
    echo "ERROR: No Python interpreter with faker + pandas + streamlit found."
    echo "Fix one of these ways:"
    echo "  1. pip install -r requirements.txt"
    echo "  2. PYTHON=/path/to/venv/bin/python ./run.sh $1"
    exit 3
}

PY="$(find_python || true)"
CMD="${1:-help}"
[[ $# -gt 0 ]] && shift || true

case "$CMD" in
    demo|schema)
        [[ -n "$PY" ]] || need_deps "$CMD"
        APP="demo_app.py"; PORT="${PORT:-8501}"
        [[ "$CMD" == "schema" ]] && APP="schema_app.py" && PORT="${PORT:-8502}"
        echo ">>> streamlit run $APP (http://localhost:$PORT)"
        exec "$PY" -m streamlit run "$APP" --server.port "$PORT" "$@"
        ;;

    notes)
        [[ -n "$PY" ]] || need_deps "$CMD"
        echo ">>> clinical_notes.py $*"
        exec "$PY" clinical_notes.py "$@"
        ;;

    gen)
        [[ -n "$PY" ]] || need_deps "$CMD"
        echo ">>> generate_from_schema.py $*"
        exec "$PY" synth-data-gen/scripts/generate_from_schema.py "$@"
        ;;

    patient)
        [[ -n "$PY" ]] || need_deps "$CMD"
        echo ">>> example_patient_generator.py $*"
        exec "$PY" example_patient_generator.py "$@"
        ;;

    validate)
        if [[ $# -lt 1 ]]; then
            echo "Usage: ./run.sh validate <file_or_directory> [--format csv|json|sql]"
            exit 2
        fi
        [[ -n "$PY" ]] || need_deps "$CMD"
        echo ">>> validate_synthetic.py $*"
        exec "$PY" validate_synthetic.py "$@"
        ;;

    install-skill)
        TARGET="${1:-$HOME/.claude/skills/synth-data-gen}"
        echo ">>> Installing skill to $TARGET"
        mkdir -p "$(dirname "$TARGET")"
        rm -rf "$TARGET"
        cp -R synth-data-gen "$TARGET"
        echo "Installed. Claude Code can now generate synthetic data on request."
        echo "Tip: pass a project path to install project-level instead:"
        echo "  ./run.sh install-skill /path/to/project/.claude/skills/synth-data-gen"
        ;;

    doctor)
        echo "Python:"
        if [[ -n "$PY" ]]; then
            "$PY" --version
            echo "  interpreter : $PY"
            echo "  faker       : $("$PY" -c 'import importlib.metadata as m; print(m.version("faker"))')"
            echo "  pandas      : $("$PY" -c 'import pandas; print(pandas.__version__)')"
            echo "  streamlit   : $("$PY" -c 'import streamlit; print(streamlit.__version__)')"
        else
            echo "  ✗ no interpreter with faker+pandas+streamlit (run: pip install -r requirements.txt)"
        fi
        echo "Git:"
        git fetch --quiet 2>/dev/null || true
        git status -sb | head -1
        echo "Outputs: $(ls synthetic_output 2>/dev/null | wc -l | tr -d ' ') file(s) in ./synthetic_output"
        ;;

    update)
        echo ">>> git pull --ff-only"
        git pull --ff-only origin main
        ;;

    help|-h|--help|*)
        sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//'
        ;;
esac
