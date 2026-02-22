# Format Templates Reference

Templates and structural guidance for generating synthetic data in healthcare-specific and
enterprise formats. Read only the sections relevant to the current request.

## Table of Contents

1. [FHIR R4 Bundles](#fhir-r4-bundles)
2. [HL7 v2.x Messages](#hl7-v2x-messages)
3. [SQL DDL + INSERT Patterns](#sql-ddl--insert-patterns)
4. [CSV Best Practices](#csv-best-practices)
5. [JSON API Mocking](#json-api-mocking)
6. [Parquet / Columnar](#parquet--columnar)

---

## FHIR R4 Bundles

Use for systems integrating with FHIR APIs (Epic FHIR, Cerner, SMART on FHIR apps).

### Patient Resource

```json
{
  "resourceType": "Patient",
  "id": "syn-patient-001",
  "meta": {
    "profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]
  },
  "identifier": [
    {
      "use": "usual",
      "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MR"}]},
      "system": "urn:example:hospital:mrn",
      "value": "MRN-2240001"
    },
    {
      "use": "official",
      "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "SS"}]},
      "system": "urn:oid:2.16.840.1.113883.4.1",
      "value": "987-65-0001"
    }
  ],
  "active": true,
  "name": [
    {
      "use": "official",
      "family": "García-López",
      "given": ["María", "Elena"],
      "prefix": ["Mrs."]
    }
  ],
  "telecom": [
    {"system": "phone", "value": "555-0101", "use": "home"},
    {"system": "email", "value": "maria.garcia@example.com"}
  ],
  "gender": "female",
  "birthDate": "1956-03-12",
  "deceasedBoolean": false,
  "address": [
    {
      "use": "home",
      "line": ["742 Synthetic Ave", "Apt 3B"],
      "city": "Testville",
      "state": "IL",
      "postalCode": "60601",
      "country": "US"
    }
  ],
  "communication": [
    {
      "language": {"coding": [{"system": "urn:ietf:bcp:47", "code": "es"}], "text": "Spanish"},
      "preferred": true
    }
  ]
}
```

### Encounter Resource

```json
{
  "resourceType": "Encounter",
  "id": "syn-encounter-001",
  "status": "finished",
  "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "ambulatory"},
  "type": [{"coding": [{"system": "http://www.ama-assn.org/go/cpt", "code": "99214"}]}],
  "subject": {"reference": "Patient/syn-patient-001"},
  "participant": [
    {
      "individual": {"reference": "Practitioner/syn-provider-001", "display": "Dr. Sarah Chen"}
    }
  ],
  "period": {"start": "2024-09-15T10:30:00-05:00", "end": "2024-09-15T11:00:00-05:00"},
  "diagnosis": [
    {
      "condition": {"reference": "Condition/syn-dx-001"},
      "use": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/diagnosis-role", "code": "billing"}]}
    }
  ]
}
```

### Bundle Wrapper

```json
{
  "resourceType": "Bundle",
  "type": "searchset",
  "total": 2,
  "entry": [
    {"resource": {"resourceType": "Patient", "...": "..."}, "fullUrl": "urn:uuid:syn-patient-001"},
    {"resource": {"resourceType": "Encounter", "...": "..."}, "fullUrl": "urn:uuid:syn-encounter-001"}
  ]
}
```

**Key rules for FHIR generation:**
- Always include `meta.profile` for US Core compliance
- Use `urn:example:` or `urn:uuid:` for system URIs — never real OIDs
- Identifiers must have proper `type.coding` with system/code
- Reference fields use relative references: `"Patient/syn-patient-001"`
- Dates in FHIR format: `YYYY-MM-DD` or `YYYY-MM-DDThh:mm:ss±hh:mm`

---

## HL7 v2.x Messages

Use for legacy integration testing (ADT feeds, lab interfaces, order messages).

### ADT^A01 (Admit)

```
MSH|^~\&|SYNTHSYS|SYNFAC|RECVSYS|RECVFAC|20240915103000||ADT^A01|SYN-MSG-0001|P|2.5.1
EVN|A01|20240915103000
PID|1||MRN-2240001^^^SYNFAC^MR~987-65-0001^^^USSSA^SS||García-López^María^Elena^^Mrs.||19560312|F||2106-3^White^CDCREC|742 Synthetic Ave^Apt 3B^Testville^IL^60601^US||^PRN^PH^^^555^0101|||||||||N^Not Hispanic^CDCREC
PV1|1|I|CARD^101^A^SYNFAC||||SYN-PROV-001^Chen^Sarah^^^Dr.|||CAR||||A|||SYN-PROV-001^Chen^Sarah^^^Dr.|IN||||||||||||||||||SYNFAC|||||20240915103000
IN1|1|SYNPLAN001^Blue Cross Synthetic|SYNPAY001|Blue Cross Test Plan|PO Box 99999^^Testville^IL^60601|||||||||||||||||||||||||||||987654321
```

### ORU^R01 (Lab Result)

```
MSH|^~\&|SYNTHLAB|SYNFAC|SYNTHEHR|SYNFAC|20240915140000||ORU^R01|SYN-MSG-0002|P|2.5.1
PID|1||MRN-2240001^^^SYNFAC^MR||García-López^María||19560312|F
OBR|1|SYN-ORD-001|SYN-LAB-001|80053^Comprehensive Metabolic Panel^CPT||||20240915103000|||||||||SYN-PROV-001^Chen^Sarah
OBX|1|NM|2951-2^Sodium^LN||141|mmol/L|136-145|N|||F
OBX|2|NM|2823-3^Potassium^LN||4.2|mmol/L|3.5-5.0|N|||F
OBX|3|NM|2160-0^Creatinine^LN||1.4|mg/dL|0.6-1.2|H|||F
```

**Key rules for HL7 v2 generation:**
- Field separator is `|`, component separator is `^`
- MSH segment always first, encoding characters in MSH-2
- Use `SYN` or `SYNTH` prefixes for facility/application names
- PID-3 repeats use `~` delimiter for multiple identifiers
- Maintain segment ordering per message type specification
- Timestamps: `YYYYMMDDHHmmss` format

---

## SQL DDL + INSERT Patterns

### DDL Template (PostgreSQL-flavored)

```sql
-- Synthetic Data Schema
-- Generated by synth-data-gen | All data is fictional

CREATE TABLE IF NOT EXISTS patients (
    patient_id      VARCHAR(20) PRIMARY KEY,
    first_name      VARCHAR(100) NOT NULL,
    last_name       VARCHAR(100) NOT NULL,
    dob             DATE NOT NULL,
    ssn             VARCHAR(11),
    mrn             VARCHAR(20) UNIQUE NOT NULL,
    gender          VARCHAR(20),
    race            VARCHAR(50),
    ethnicity       VARCHAR(50),
    email           VARCHAR(255),
    phone           VARCHAR(20),
    address_line1   VARCHAR(255),
    address_city    VARCHAR(100),
    address_state   CHAR(2),
    address_zip     VARCHAR(10),
    preferred_lang  VARCHAR(50) DEFAULT 'English',
    deceased_flag   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS encounters (
    encounter_id    VARCHAR(36) PRIMARY KEY,
    patient_id      VARCHAR(20) NOT NULL REFERENCES patients(patient_id),
    encounter_type  VARCHAR(20) NOT NULL,
    admit_datetime  TIMESTAMP WITH TIME ZONE NOT NULL,
    discharge_datetime TIMESTAMP WITH TIME ZONE,
    department      VARCHAR(100),
    attending_id    VARCHAR(20),
    disposition     VARCHAR(50),
    -- ...
    CONSTRAINT fk_enc_patient FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
);

-- Indexes for realistic query patterns
CREATE INDEX idx_patients_mrn ON patients(mrn);
CREATE INDEX idx_patients_name ON patients(last_name, first_name);
CREATE INDEX idx_encounters_patient ON encounters(patient_id);
CREATE INDEX idx_encounters_dates ON encounters(admit_datetime);
```

### INSERT Template

```sql
-- Batch insert with ON CONFLICT for idempotency
INSERT INTO patients (patient_id, first_name, last_name, dob, ssn, mrn, gender, email, phone)
VALUES
    ('SYN-000001', 'María', 'García-López', '1956-03-12', '987-65-0001', 'MRN-2240001', 'Female', 'maria.garcia@example.com', '555-0101'),
    ('SYN-000002', 'James', 'O''Brien', '1989-11-28', '987-65-0002', 'MRN-2240002', 'Male', NULL, '555-0102')
ON CONFLICT (patient_id) DO NOTHING;
```

**Key rules for SQL output:**
- Escape single quotes in names (O'Brien → O''Brien)
- Use NULL keyword, not empty string, for missing data
- Include DDL if requested; otherwise just INSERTs
- Add `ON CONFLICT` for safe re-runs
- Comment header with generation timestamp and seed

---

## CSV Best Practices

```csv
# Generated by synth-data-gen | Seed: 42 | All data is fictional
patient_id,first_name,last_name,dob,ssn,mrn,gender,email,phone
SYN-000001,María,García-López,1956-03-12,987-65-0001,MRN-2240001,Female,maria.garcia@example.com,555-0101
SYN-000002,James,"O'Brien",1989-11-28,987-65-0002,MRN-2240002,Male,,555-0102
```

**Key rules:**
- Quote fields containing commas, quotes, or newlines
- Use empty field (not "NULL") for missing values in CSV
- UTF-8 encoding with BOM if consumers might be Excel
- Include header row always
- Date format: ISO 8601 (YYYY-MM-DD)
- Comment header line (with `#`) noting synthetic origin

---

## JSON API Mocking

For REST API test fixtures and mock server data.

### Collection Format

```json
{
  "_meta": {
    "generated_by": "synth-data-gen",
    "seed": 42,
    "record_count": 100,
    "synthetic": true,
    "generated_at": "2025-01-15T10:00:00Z"
  },
  "data": [
    {"patient_id": "SYN-000001", "...": "..."},
    {"patient_id": "SYN-000002", "...": "..."}
  ],
  "pagination": {
    "total": 100,
    "page": 1,
    "per_page": 20,
    "total_pages": 5
  }
}
```

**Key rules:**
- Include `_meta` block marking data as synthetic
- Match pagination structure of the target API
- Use camelCase or snake_case consistently (match target system)
- Include realistic error response fixtures too

---

## Parquet / Columnar

Generate via Python script using pandas + pyarrow:

```python
import pandas as pd

df = pd.DataFrame(data)
# Set appropriate dtypes
df['dob'] = pd.to_datetime(df['dob'])
df['patient_id'] = df['patient_id'].astype('string')

df.to_parquet('synthetic_patients.parquet', engine='pyarrow', index=False)
```

**Key rules:**
- Set pandas dtypes explicitly (don't let inference guess wrong)
- Use `string` type (not `object`) for string columns
- Date columns as proper datetime64
- Include metadata in parquet file properties if possible
