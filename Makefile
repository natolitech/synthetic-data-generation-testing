.PHONY: help sync-skill check-sync test lint ci demo schema bundle docker-build

help:
	@echo "synthgen development tasks"
	@echo "  make sync-skill   Regenerate synth-data-gen/scripts from synthgen/ + root sources"
	@echo "  make check-sync   Verify skill copies are not drifted (CI gate)"
	@echo "  make test         Run pytest"
	@echo "  make lint         Run ruff"
	@echo "  make ci           lint + test + check-sync (what CI runs)"
	@echo "  make demo         Launch demo Streamlit app (:8501)"
	@echo "  make schema       Launch schema Streamlit app (:8502)"

sync-skill:
	python3 scripts/sync_skill.py

check-sync:
	python3 scripts/sync_skill.py --check

test:
	python3 -m pytest tests/ -q

lint:
	python3 -m ruff check synthgen/ tests/ scripts/ demo_app.py schema_app.py clinical_notes.py clinical_bundle.py fhir_export.py hl7_export.py validate_synthetic.py example_patient_generator.py

ci: lint test check-sync

demo:
	./run.sh demo

schema:
	./run.sh schema
