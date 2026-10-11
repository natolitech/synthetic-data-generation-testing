# Streamlit demo image — zero local Python needed.
#   docker build -t synthgen-demo .
#   docker run -p 8501:8501 synthgen-demo
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY synthgen/ ./synthgen/
COPY demo_app.py schema_app.py clinical_notes.py clinical_bundle.py \
     fhir_export.py hl7_export.py validate_synthetic.py \
     example_patient_generator.py run.sh ./
COPY schema/ ./schema/

RUN chmod +x run.sh && mkdir -p /app/synthetic_output

EXPOSE 8501 8502
ENV STREAMLIT_SERVER_HEADLESS=true

CMD ["python", "-m", "streamlit", "run", "demo_app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
