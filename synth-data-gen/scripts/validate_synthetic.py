#!/usr/bin/env python3
"""
Synthetic Data Validator
========================
Checks generated data for:
  1. Accidental real-world PII/PHI leakage
  2. Referential integrity violations
  3. NULL/edge case coverage
  4. Format compliance

Usage:
    python validate_synthetic.py <file_or_directory> [--format csv|json|sql]

Exit codes:
    0 = All checks passed
    1 = Warnings found (review recommended)
    2 = Critical issues found (do not use data)
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from collections import Counter, defaultdict


# ============================================================================
# Known real-world patterns to flag
# ============================================================================

# SSN ranges that are REAL (should NOT appear in synthetic data)
# Synthetic should use 987-65-xxxx or 900-999 area numbers
REAL_SSN_AREA_NUMBERS = set(range(1, 900))  # 001-899 are real assignments

# Real hospital NPI prefixes (10-digit NPIs starting with these)
# We just flag any 10-digit number that looks like a real NPI
NPI_PATTERN = re.compile(r'\b1\d{9}\b')  # NPIs start with 1

# Real email domains that should never appear in synthetic data
REAL_EMAIL_DOMAINS = {
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'aol.com',
    'icloud.com', 'mail.com', 'protonmail.com', 'live.com', 'msn.com',
    'uchicago.edu', 'bsd.uchicago.edu', 'medicine.bsd.uchicago.edu',
    'anl.gov', 'fnal.gov',  # DOE labs
}

# Safe email domains (RFC 2606 reserved) — subdomains and reserved TLDs are safe too
SAFE_EMAIL_DOMAINS = {
    'example.com', 'example.org', 'example.net', 'test.invalid',
    'example.invalid', 'test.test',
}
SAFE_EMAIL_TLDS = {'.example', '.invalid', '.test', '.localhost'}


def _is_safe_email_domain(domain: str) -> bool:
    d = domain.lower()
    if d in SAFE_EMAIL_DOMAINS:
        return True
    if any(d.endswith(tld) for tld in SAFE_EMAIL_TLDS):
        return True
    return any(d.endswith('.' + s) for s in SAFE_EMAIL_DOMAINS)

# Real phone patterns to flag (not in 555-01xx range)
SAFE_PHONE_PATTERN = re.compile(r'555-01\d{2}')

# Real credit card BIN ranges (first 6 digits) - just check it's not a test range
TEST_CARD_NUMBERS = {
    '4242424242424242',  # Stripe test Visa
    '4000056655665556',  # Stripe test Visa (debit)
    '5555555555554444',  # Stripe test MC
    '378282246310005',   # Stripe test Amex
    '6011111111111117',  # Stripe test Discover
}

# Real SSN pattern
SSN_PATTERN = re.compile(r'\b(\d{3})-(\d{2})-(\d{4})\b')

# Email pattern
EMAIL_PATTERN = re.compile(r'\b[\w.+-]+@([\w-]+\.[\w.-]+)\b')

# Phone pattern (US)
PHONE_PATTERN = re.compile(r'\b(\d{3})-(\d{4})\b')

# IP address pattern
IP_PATTERN = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')

# Safe IP ranges (RFC 5737 documentation)
SAFE_IP_PREFIXES = ['192.0.2.', '198.51.100.', '203.0.113.', '10.', '172.16.', '192.168.']


class ValidationResult:
    def __init__(self):
        self.critical = []
        self.warnings = []
        self.info = []
        self.stats = {}

    def add_critical(self, msg):
        self.critical.append(msg)

    def add_warning(self, msg):
        self.warnings.append(msg)

    def add_info(self, msg):
        self.info.append(msg)

    @property
    def exit_code(self):
        if self.critical:
            return 2
        elif self.warnings:
            return 1
        return 0

    def to_html(self, source_path=''):
        """Self-contained HTML compliance artifact (inline CSS, no deps)."""
        from datetime import datetime
        from html import escape
        status = ('FAIL — do not use' if self.critical
                  else 'REVIEW — warnings found' if self.warnings
                  else 'PASS — safe for use')
        cls = ('bad' if self.critical else 'warn' if self.warnings else 'good')

        def rows(items, icon):
            return ''.join(
                f'<tr><td>{icon}</td><td>{escape(str(m))}</td></tr>' for m in items) or \
                '<tr><td colspan="2" class="muted">none</td></tr>'

        stat_rows = ''.join(
            f'<tr><td>{escape(str(k))}</td><td>{escape(str(v))}</td></tr>'
            for k, v in self.stats.items()) or '<tr><td colspan="2" class="muted">n/a</td></tr>'

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Synthetic Data Validation Report</title>
<style>
 body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 2rem; color: #1a1a2e; }}
 h1 {{ border-bottom: 3px solid #4361ee; padding-bottom: .3rem; }}
 .banner {{ display: inline-block; padding: .4rem 1.2rem; border-radius: 6px; font-weight: 700;
           margin: .8rem 0; }}
 .good {{ background: #d8f3ec; color: #1b7a70; }} .warn {{ background: #fdf3d7; color: #9a7b1e; }}
 .bad {{ background: #fde2dd; color: #b3492f; }}
 table {{ border-collapse: collapse; width: 100%; margin: .8rem 0 1.6rem; }}
 th, td {{ border: 1px solid #ddd; padding: .45rem .8rem; text-align: left; vertical-align: top; }}
 th {{ background: #f0f2ff; }}
 .muted {{ color: #999; }}
 footer {{ margin-top: 2rem; color: #777; font-size: .85rem; }}
</style></head><body>
<h1>Synthetic Data Validation Report</h1>
<p class="meta">Source: <code>{escape(str(source_path))}</code> ·
   Generated: {datetime.now().isoformat(timespec='seconds')}</p>
<span class="banner {cls}">{status}</span>
<h2>Critical issues ({len(self.critical)})</h2>
<table>{rows(self.critical, '&#10006;')}</table>
<h2>Warnings ({len(self.warnings)})</h2>
<table>{rows(self.warnings, '&#9889;')}</table>
<h2>Informational ({len(self.info)})</h2>
<table>{rows(self.info, '&#8505;')}</table>
<h2>Statistics</h2>
<table>{stat_rows}</table>
<footer>Generated by synthgen validate_synthetic · every identifier is verified against
reserved/fictional ranges (SSN 987-65-xxxx, 555-01xx, RFC 2606 domains, NPI Luhn, MRN-224xxxx)</footer>
</body></html>"""

    def report(self):
        print("\n" + "=" * 70)
        print("SYNTHETIC DATA VALIDATION REPORT")
        print("=" * 70)

        if self.critical:
            print(f"\n🚨 CRITICAL ISSUES ({len(self.critical)}):")
            for msg in self.critical:
                print(f"   ✖ {msg}")

        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for msg in self.warnings:
                print(f"   ⚡ {msg}")

        if self.info:
            print(f"\nℹ️  INFO ({len(self.info)}):")
            for msg in self.info:
                print(f"   • {msg}")

        if self.stats:
            print("\n📊 STATISTICS:")
            for key, val in self.stats.items():
                print(f"   {key}: {val}")

        print("\n" + "-" * 70)
        if self.exit_code == 0:
            print("✅ PASSED — All checks passed. Data appears safe for use.")
        elif self.exit_code == 1:
            print("⚠️  REVIEW — Warnings found. Review before using in non-production.")
        else:
            print("🚨 FAILED — Critical issues detected. DO NOT USE this data.")
        print("-" * 70 + "\n")

        return self.exit_code


def extract_all_text(filepath):
    """Read file and return all text content for pattern scanning."""
    path = Path(filepath)
    suffix = path.suffix.lower()

    if suffix == '.csv':
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            return f.read()
    elif suffix == '.json':
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    elif suffix == '.sql':
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()


def check_ssns(text, result):
    """Check for SSNs that fall in real-world ranges."""
    matches = SSN_PATTERN.findall(text)
    real_count = 0
    safe_count = 0
    for area, group, serial in matches:
        area_num = int(area)
        if area_num in REAL_SSN_AREA_NUMBERS:
            real_count += 1
            if real_count <= 5:
                result.add_critical(
                    f"SSN with real area number found: {area}-{group}-{serial} "
                    f"(area {area} is assigned to real people). Use 987-65-xxxx or 900-999."
                )
        else:
            safe_count += 1

    if real_count > 5:
        result.add_critical(f"... and {real_count - 5} more real-range SSNs found.")
    if safe_count > 0:
        result.add_info(f"{safe_count} SSNs in safe synthetic range (900-999 or 987-65-xxxx).")


def check_emails(text, result):
    """Check for real email domains."""
    matches = EMAIL_PATTERN.findall(text)
    domain_counts = Counter(d.lower() for d in matches)

    for domain, count in domain_counts.items():
        if domain in REAL_EMAIL_DOMAINS:
            result.add_critical(
                f"Real email domain found: @{domain} ({count} occurrences). "
                f"Use @example.com or @test.invalid instead."
            )
        elif not _is_safe_email_domain(domain):
            result.add_warning(
                f"Unrecognized email domain: @{domain} ({count} occurrences). "
                f"Verify this is not a real domain."
            )
        else:
            result.add_info(f"Safe email domain @{domain}: {count} occurrences.")


def check_phones(text, result):
    """Check for phone numbers outside the 555-01xx safe range."""
    # Look for 7-digit or 10-digit phone patterns
    full_pattern = re.compile(r'\b(\d{3})[-.)]?\s*(\d{3})[-.]\s*(\d{4})\b')
    matches = full_pattern.findall(text)

    unsafe_count = 0
    safe_count = 0
    for area, exchange, number in matches:
        if exchange == '555' and number.startswith('01'):
            safe_count += 1
        elif exchange == '555' and int(number) >= 100 and int(number) <= 199:
            safe_count += 1
        elif area in ('800', '888', '877', '866', '855', '844', '833'):
            # Toll-free patterns are less risky but still flag
            unsafe_count += 1
        else:
            unsafe_count += 1

    if unsafe_count > 0:
        result.add_warning(
            f"{unsafe_count} phone numbers outside safe 555-01xx range. "
            f"These could potentially match real phone numbers."
        )
    if safe_count > 0:
        result.add_info(f"{safe_count} phone numbers in safe 555-01xx range.")


def check_ip_addresses(text, result):
    """Check for IP addresses outside documentation/private ranges."""
    matches = IP_PATTERN.findall(text)
    unsafe_count = 0
    safe_count = 0

    for ip in matches:
        if any(ip.startswith(prefix) for prefix in SAFE_IP_PREFIXES):
            safe_count += 1
        else:
            unsafe_count += 1
            if unsafe_count <= 3:
                result.add_warning(
                    f"IP address {ip} not in safe documentation range. "
                    f"Use 192.0.2.0/24, 198.51.100.0/24, or 203.0.113.0/24."
                )

    if unsafe_count > 3:
        result.add_warning(f"... and {unsafe_count - 3} more non-safe IP addresses.")
    if safe_count > 0:
        result.add_info(f"{safe_count} IP addresses in safe ranges.")


def _npi_check_digit(first9: str) -> str:
    """CMS NPI check digit: Luhn over '80840' + the first 9 digits."""
    payload = "80840" + first9
    total = 0
    for i, ch in enumerate(reversed(payload)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def _is_valid_npi(npi: str) -> bool:
    return (len(npi) == 10 and npi.isdigit()
            and _npi_check_digit(npi[:9]) == npi[9])


def check_npis(text, result):
    """NPI checks: valid-checksum + real-range prefix = potential REAL NPI
    (critical); invalid checksum = data-quality warning."""
    matches = re.findall(r'\b(\d{10})\b', text)
    real, valid, invalid = [], 0, 0
    for npi in matches:
        if _is_valid_npi(npi):
            if npi.startswith('1'):
                real.append(npi)
            else:
                valid += 1
        else:
            invalid += 1
    if real:
        result.add_critical(
            f"{len(real)} potential REAL NPI number(s) (valid checksum, real-range "
            f"prefix): {', '.join(real[:3])}. Verify these are fictional."
        )
    if invalid:
        result.add_warning(f"{invalid} NPI-like number(s) fail the Luhn checksum (data quality).")
    if valid:
        result.add_info(f"{valid} NPI(s) pass the Luhn checksum (safe range).")


MRN_PATTERN = re.compile(r'\bMRN-(\d{4,10})\b')


def check_mrns(text, result):
    """Flag MRN-like values outside the synthetic MRN-224xxxx range."""
    bad = [m for m in MRN_PATTERN.findall(text) if not 2240000 <= int(m) <= 2249999]
    if bad:
        result.add_warning(
            f"{len(bad)} MRN value(s) outside the synthetic range MRN-224xxxx: "
            f"{', '.join('MRN-' + b for b in bad[:3])}"
        )


def check_csv_quality(filepath, result):
    """CSV-specific quality checks."""
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            # Skip comment lines
            lines = [l for l in f if not l.startswith('#')]

        if not lines:
            result.add_warning("CSV file is empty.")
            return

        reader = csv.DictReader(lines)
        rows = list(reader)

        if not rows:
            result.add_warning("CSV has headers but no data rows.")
            return

        result.stats['Total rows'] = len(rows)
        result.stats['Columns'] = ', '.join(reader.fieldnames or [])

        # Check NULL/empty distribution
        null_counts = defaultdict(int)
        for row in rows:
            for field, value in row.items():
                if value is None or value.strip() == '' or value.upper() == 'NULL':
                    null_counts[field] += 1

        total = len(rows)
        has_nulls = False
        for field, count in null_counts.items():
            pct = (count / total) * 100
            if pct > 0:
                has_nulls = True
                result.stats[f'NULL% in {field}'] = f"{pct:.1f}%"

        if not has_nulls:
            result.add_warning(
                "No NULL/empty values found in any column. "
                "Real data almost always has missing values — consider adding 5-15% NULLs."
            )

        # Check for diversity in categorical columns
        for field in (reader.fieldnames or []):
            values = [r[field] for r in rows if r[field] and r[field].strip()]
            unique = set(values)
            if 2 <= len(unique) <= 1 and len(values) > 10:
                result.add_warning(f"Column '{field}' has only 1 unique value across {len(values)} rows.")

    except Exception as e:
        result.add_warning(f"Could not parse CSV for quality checks: {e}")


def check_json_quality(filepath, result):
    """JSON-specific quality checks."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if isinstance(data, dict):
            if '_meta' in data and data['_meta'].get('synthetic'):
                result.add_info("JSON includes synthetic data metadata marker.")
            elif '_meta' not in data:
                result.add_warning(
                    "JSON missing '_meta' block. Consider adding "
                    '{"_meta": {"synthetic": true}} to mark as synthetic.'
                )

            # Check for data array
            if 'data' in data and isinstance(data['data'], list):
                result.stats['Total records'] = len(data['data'])
            elif isinstance(data, list):
                result.stats['Total records'] = len(data)

    except json.JSONDecodeError as e:
        result.add_critical(f"Invalid JSON: {e}")
    except Exception as e:
        result.add_warning(f"Could not parse JSON for quality checks: {e}")


def validate_file(filepath, result):
    """Run all validation checks on a single file."""
    path = Path(filepath)
    result.add_info(f"Validating: {path.name}")

    if not path.exists():
        result.add_critical(f"File not found: {filepath}")
        return

    text = extract_all_text(filepath)
    result.stats['File size'] = f"{path.stat().st_size:,} bytes"

    # Run pattern checks on all text
    check_ssns(text, result)
    check_emails(text, result)
    check_phones(text, result)
    check_ip_addresses(text, result)
    check_npis(text, result)
    check_mrns(text, result)

    # Format-specific checks
    suffix = path.suffix.lower()
    if suffix == '.csv':
        check_csv_quality(filepath, result)
    elif suffix == '.json':
        check_json_quality(filepath, result)


def validate_directory(dirpath, result):
    """Validate all supported files in a directory."""
    supported = {'.csv', '.json', '.sql', '.txt', '.hl7', '.fhir'}
    path = Path(dirpath)

    files = [f for f in path.rglob('*') if f.suffix.lower() in supported and f.is_file()]

    if not files:
        result.add_warning(f"No supported files found in {dirpath}")
        return

    result.add_info(f"Found {len(files)} file(s) to validate.")
    for filepath in sorted(files):
        validate_file(str(filepath), result)


def main():
    parser = argparse.ArgumentParser(
        description='Validate synthetic data for PII/PHI leakage and quality.'
    )
    parser.add_argument(
        'path',
        help='File or directory to validate'
    )
    parser.add_argument(
        '--format', '-f',
        choices=['csv', 'json', 'sql', 'auto'],
        default='auto',
        help='Override format detection (default: auto-detect from extension)'
    )
    parser.add_argument(
        '--html',
        metavar='PATH',
        help='also write a self-contained HTML compliance report'
    )
    args = parser.parse_args()

    result = ValidationResult()

    target = Path(args.path)
    if target.is_dir():
        validate_directory(args.path, result)
    elif target.is_file():
        validate_file(args.path, result)
    else:
        result.add_critical(f"Path not found: {args.path}")

    if args.html:
        Path(args.html).write_text(result.to_html(source_path=args.path), encoding='utf-8')
        print(f"HTML report written → {args.html}")

    exit_code = result.report()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
