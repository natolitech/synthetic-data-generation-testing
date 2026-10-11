"""Inline PII/PHI safety checks shared by generators and CLIs."""
import re

# --- NPI check-digit (Luhn with the 80840 prefix per CMS specification) -------

def npi_check_digit(first9: str) -> str:
    """Compute the NPI check digit: Luhn over '80840' + first 9 digits."""
    payload = "80840" + first9
    total = 0
    for i, ch in enumerate(reversed(payload)):
        d = int(ch)
        if i % 2 == 0:  # doubled relative to the future check-digit position
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def is_valid_npi(npi: str) -> bool:
    """True when the 10-digit NPI has a valid Luhn check digit."""
    return (len(npi) == 10 and npi.isdigit()
            and npi_check_digit(npi[:9]) == npi[9])

_REAL_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "mail.com", "protonmail.com", "live.com", "msn.com",
}
_SAFE_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "test.invalid", "example.edu"}
_SAFE_EMAIL_TLDS = (".example", ".invalid", ".test", ".localhost")


def _safe_domain(d: str) -> bool:
    """Exact reserved domains, reserved TLDs, and their subdomains are safe."""
    d = d.lower()
    return (d in _SAFE_EMAIL_DOMAINS
            or any(d.endswith(t) for t in _SAFE_EMAIL_TLDS)
            or any(d.endswith("." + s) for s in _SAFE_EMAIL_DOMAINS))
_SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@([\w-]+\.[\w.-]+)\b")
_PHONE_RE = re.compile(r"\b(\d{3})[-.)]?\s*(\d{3})[-.]\s*(\d{4})\b")
_NPI_RE = re.compile(r"\b(\d{10})\b")
_MRN_RE = re.compile(r"\bMRN-(\d{4,10})\b")


def validate(text: str) -> dict:
    results: dict = {"critical": [], "warnings": [], "info": []}
    safe_ssns = 0
    for area, _, _s in _SSN_RE.findall(text):
        if int(area) in range(1, 900):
            results["critical"].append(f"Real-range SSN area: {area}")
        else:
            safe_ssns += 1
    if safe_ssns:
        results["info"].append(f"{safe_ssns} SSN(s) in safe range (987-65-xxxx)")

    seen: set = set()
    for domain in _EMAIL_RE.findall(text):
        d = domain.lower()
        if d in seen:
            continue
        seen.add(d)
        if d in _REAL_EMAIL_DOMAINS:
            results["critical"].append(f"Real email domain: @{d}")
        elif not _safe_domain(d):
            results["warnings"].append(f"Unrecognized email domain: @{d}")

    unsafe = safe = 0
    for _, exchange, number in _PHONE_RE.findall(text):
        if exchange == "555" and number.startswith("01"):
            safe += 1
        else:
            unsafe += 1
    if unsafe:
        results["warnings"].append(f"{unsafe} phone(s) outside safe 555-01xx range")
    if safe:
        results["info"].append(f"{safe} phone(s) in safe range")

    # NPIs: checksum validity is a data-quality signal; a VALID checksum on a
    # real-range prefix (1x) means the number could be an issued NPI.
    valid_npis = invalid_npis = 0
    for npi in _NPI_RE.findall(text):
        if is_valid_npi(npi):
            if npi.startswith("1"):
                results["critical"].append(
                    f"Potential REAL NPI (valid checksum, real-range prefix): {npi}")
            else:
                valid_npis += 1
        else:
            invalid_npis += 1
    if valid_npis:
        results["info"].append(f"{valid_npis} NPI(s) pass the Luhn check")
    if invalid_npis:
        results["warnings"].append(
            f"{invalid_npis} NPI(s) fail the Luhn checksum (data quality)")

    # MRNs: outside the synthetic MRN-224xxxx range
    bad_mrns = [m for m in _MRN_RE.findall(text) if not 2240000 <= int(m) <= 2249999]
    if bad_mrns:
        results["warnings"].append(
            f"{len(bad_mrns)} MRN(s) outside synthetic range MRN-224xxxx")

    return results
