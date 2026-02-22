# Synthetic Data Generator — Claude Code Skill

## Deployment Instructions

### Install the Skill

Copy the `synth-data-gen/` directory into your Claude Code skills folder:

```bash
# If you have a project-level .claude/ directory:
cp -r synth-data-gen/ /path/to/your/project/.claude/skills/synth-data-gen/

# Or for user-level skills:
cp -r synth-data-gen/ ~/.claude/skills/synth-data-gen/
```

### Python Dependencies

The generated scripts require these packages (devs install in their environment):

```bash
pip install faker pandas
# Optional, for Parquet output:
pip install pyarrow
```

### How Developers Use It

Once installed, developers invoke the skill naturally in Claude Code:

```
> I need test data for the patient demographics table

> Generate 500 synthetic encounters with related diagnoses and labs in CSV

> Create a FHIR Patient bundle with 50 records for our API mock server

> I need fake Active Directory user accounts with group memberships for testing SailPoint

> Build me a Python script that generates synthetic student enrollment data I can run repeatedly
```

The skill will:
1. Ask clarifying questions about schema, volume, and format
2. Consult domain-specific rules for realistic value generation
3. Generate data or a reusable generator script
4. Run validation to check for accidental PII/PHI leakage
5. Deliver with a clear "all data is synthetic" attestation

### What's Included

```
synth-data-gen/
├── SKILL.md                              # Main skill instructions
├── references/
│   ├── data-domains.md                   # Field rules for clinical, student, IAM, HR, research, financial
│   └── format-templates.md               # FHIR, HL7, SQL, CSV, JSON, Parquet templates
├── scripts/
│   ├── validate_synthetic.py             # Checks output for real-world data leakage
│   └── example_patient_generator.py      # Working example generator
└── assets/                               # (reserved for future templates)
```

### Validation

The included validator catches common mistakes:

```bash
python scripts/validate_synthetic.py output_file.csv
```

It checks for:
- SSNs in real-world ranges (should be 987-65-xxxx or 900-999)
- Real email domains (should be @example.com or @test.invalid)
- Phone numbers outside the 555-01xx safe range
- IP addresses outside RFC 5737 documentation ranges
- Potential real NPI numbers
- Missing NULL distributions (real data always has gaps)
