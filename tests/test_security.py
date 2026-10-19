"""Security test suite — qso-graph MCP Security Framework v1.0.

These tests enforce the 10 non-negotiable security guarantees.
See: https://qso-graph.io/security/
"""

import re
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent / "src"


def _py_files():
    """Yield all .py files under src/."""
    yield from SRC_DIR.rglob("*.py")


def test_no_print_credentials():
    """Guarantee #1: Credentials never in logs (print statements)."""
    forbidden = re.compile(
        r'print\s*\(.*(?:password|api_key|creds|secret|token).*\)',
        re.IGNORECASE,
    )
    for py_file in _py_files():
        content = py_file.read_text()
        matches = forbidden.findall(content)
        assert not matches, f"Credential print in {py_file.name}: {matches}"


def test_no_logging_credentials():
    """Guarantee #1: Credentials never in logs (logging statements)."""
    forbidden = re.compile(
        r'logging\..*\(.*(?:password|api_key|creds|secret|token).*\)',
        re.IGNORECASE,
    )
    for py_file in _py_files():
        content = py_file.read_text()
        matches = forbidden.findall(content)
        assert not matches, f"Credential logging in {py_file.name}: {matches}"


def test_no_subprocess():
    """Guarantee #5: No command injection surface."""
    forbidden = re.compile(r'subprocess\.|os\.system|shell\s*=\s*True')
    for py_file in _py_files():
        content = py_file.read_text()
        matches = forbidden.findall(content)
        assert not matches, f"Shell execution in {py_file.name}: {matches}"


def test_all_urls_https():
    """Guarantee #7: HTTPS only for external calls. Every file under src/, as the
    release gate checks it (the bundled sample pages included)."""
    http_url = re.compile(r'http://(?!localhost|127\.0\.0\.1|::1)')
    for py_file in (p for p in SRC_DIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        content = py_file.read_text(encoding="utf-8", errors="replace")
        matches = http_url.findall(content)
        assert not matches, f"Non-HTTPS URL in {py_file.name}: {matches}"


def test_error_messages_safe():
    """Guarantee #3/#10: Credentials never in error messages."""
    dangerous = re.compile(
        r'raise\s+\w+\([^)]*(?:password|api_key|creds|secret).*\)',
        re.IGNORECASE,
    )
    for py_file in _py_files():
        content = py_file.read_text()
        matches = dangerous.findall(content)
        assert not matches, f"Credential in exception in {py_file.name}: {matches}"


def test_no_eval_exec():
    """Guarantee #5: No code injection surface."""
    for py_file in _py_files():
        content = py_file.read_text()
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if re.search(r'\b(?:eval|exec)\s*\(', stripped):
                assert False, f"eval/exec in {py_file.name}:{i}: {stripped.strip()}"


# ---------------------------------------------------------------------------
# omiss-mcp: what reaches omiss.net, and what never comes back
# ---------------------------------------------------------------------------

import urllib.parse  # noqa: E402
from importlib.resources import files  # noqa: E402

import pytest  # noqa: E402
from netlogger_mcp.limiter import RateLimiter  # noqa: E402

from omiss_mcp.html import OmissError  # noqa: E402
from omiss_mcp.omiss import LIMITS, OmissSource  # noqa: E402

SAMPLES = {
    "index.php": "index.html",
    "searchResults.php": "searchResults.html",
    "listCheckinHistory.php": "listCheckinHistory.html",
    "displayCheckinHistory.php": "displayCheckinHistory.html",
    "statehoodSchedule.php": "statehoodSchedule.html",
    "vipListing.php": "vipListing.html",
    "awardRecipients.php": "awardRecipients.html",
    "awardRules.php": "awardRules.html",
    "GenAwardReport.php": "GenAwardReport.html",
    "statistics.php": "statistics.html",
    "rosterXML.php": "rosterXML.xml",
    "militaryRoster.php": "militaryRoster.html",
    "firstResponderRoster.php": "firstResponderRoster.html",
    "stateCapitalRoster.php": "stateCapitalRoster.html",
    "SKRoster.php": "SKRoster.html",
}

# Parameters each page may be sent, and nothing else.
ALLOWED_PARAMS = {
    "searchResults.php": {"criteria", "searchText", "scope"},
    "listCheckinHistory.php": {"Band", "NCS", "OMNum", "Call", "State", "County", "Grid", "Date", "Max", "Submit"},
    "displayCheckinHistory.php": {"id"},
    "GenAwardReport.php": {"AwardID"},
}
SAFE_VALUE = re.compile(r"[A-Za-z0-9/ -]*")


class Spy:
    def __init__(self):
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        page = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
        return 200, files("omiss_mcp.samples").joinpath(SAMPLES[page]).read_bytes(), None


@pytest.fixture
def spy():
    s = Spy()
    return s, OmissSource(fetch=s, limiter=RateLimiter(LIMITS, window=0.0))


def _check_urls(urls):
    for url in urls:
        parts = urllib.parse.urlparse(url)
        assert parts.scheme == "https" and parts.netloc == "www.omiss.net"
        page = parts.path.rsplit("/", 1)[-1]
        params = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        assert set(params) <= ALLOWED_PARAMS.get(page, set()), url
        for values in params.values():
            for v in values:
                assert SAFE_VALUE.fullmatch(v), f"unsafe value {v!r} sent in {url}"


HOSTILE = [
    "W1OMS' OR '1'='1", "W1OMS%", "W1OMS;--", "<script>", "W1OMS\x00", "' UNION SELECT 1 --",
    "W1OMS#", "%27", "W1 OMS", "x" * 500, "../etc/passwd", "W1OMS\nX",
]


@pytest.mark.parametrize("bad", HOSTILE)
def test_hostile_input_never_reaches_omiss(spy, bad):
    """Every value is checked before any request: hostile text is refused, and
    nothing is fetched for it."""
    s, source = spy
    calls = [
        lambda: source.member_lookup(callsign=bad),
        lambda: source.member_lookup(om_number_=bad),
        lambda: source.checkin_history(callsign=bad),
        lambda: source.checkin_history(om_number_=bad),
        lambda: source.checkin_history(band_=bad),
        lambda: source.checkin_history(date_=bad),
        lambda: source.checkin_history(net_control=bad),
        lambda: source.net_checkins(bad),
        lambda: source.award_recipients(bad),
        lambda: source.net_statistics(state_=bad),
    ]
    for c in calls:
        with pytest.raises(OmissError):
            c()
    # award_recipients reads the award list to check the ID; nothing else is fetched
    assert all("awardRecipients.php" in u for u in s.urls)


def test_every_request_is_https_to_omiss_with_known_params(spy):
    s, source = spy
    source.net_schedule()
    source.member_lookup(callsign="w1oms")
    source.member_lookup(om_number_="999")
    source.checkin_history(callsign="W1OMS", om_number_=999, band_="20", date_="2026-09", net_control="W3XCC")
    source.net_checkins(30001)
    source.statehood_schedule()
    source.officers()
    source.award_rules("100GOLD")
    source.award_recipients("alphabetsoup")
    source.net_statistics("CT")
    source.eligibility(["W1OMS"])
    assert len(s.urls) >= 14
    _check_urls(s.urls)


def test_no_email_or_address_or_sql_returned(spy):
    """The samples hold an email, a PO box and the SQL comment omiss.net prints;
    none of them comes back from any lookup."""
    import json

    _, source = spy
    out = json.dumps([
        source.net_schedule(), source.member_lookup(callsign="W1OMS"),
        source.checkin_history(), source.net_checkins(30001), source.statehood_schedule(),
        source.officers(), source.awards(), source.award_rules(), source.award_rules("100GOLD"),
        source.award_recipients("ALPHABETSOUP"), source.net_statistics("CT"),
        source.eligibility(["W1OMS", "W2XBB", "W3XCC", "KX0AA"]),
    ])
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", out)
    assert "PO Box" not in out and "Box 0000" not in out and "00000" not in out
    assert "SELECT" not in out and "CheckinHistory" not in out
    assert "mailto" not in out


def test_award_id_must_come_from_the_site_list(spy):
    s, source = spy
    with pytest.raises(OmissError):
        source.award_recipients("NOTANAWARD")
    assert not any("GenAwardReport" in u for u in s.urls)


def _code_only(path: Path) -> str:
    """The file with comments and string literals removed.

    Some checks must read what the code *does*, not what it says about itself.
    `_context()` carries a docstring explaining that `ssl.CERT_NONE` would be the wrong
    fix, and a plain text search cannot tell that sentence apart from the thing it warns
    against.
    """
    import tokenize

    kept = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


def test_tls_verification_is_never_disabled():
    """Guarantee #8: no context here stops checking certificates.

    This server holds no credential — the one thing it stores is a callsign, which is
    public — so a trust failure costs an answer rather than a secret. But `ssl.CERT_NONE`
    would still accept any certificate from anyone, which is a worse defect than the one
    qso-graph-devel#73 fixes, and an invisible one.
    """
    forbidden = re.compile(r"CERT_NONE|check_hostname\s*=\s*False|_create_unverified")
    for py_file in _py_files():
        matches = forbidden.findall(_code_only(py_file))
        assert not matches, f"TLS verification weakened in {py_file.name}: {matches}"


def test_the_root_set_is_carried_not_borrowed():
    """Guarantee #8: the roots come from certifi, not the host's OpenSSL store."""
    assert "cafile=certifi.where()" in (SRC_DIR / "omiss_mcp" / "omiss.py").read_text()


def test_certifi_is_declared_not_merely_inherited():
    """Guarantee #8: the root set is not borrowed from a sibling package.

    This repo differs from the rest of the fleet. Elsewhere `certifi` is not transitive
    at all, so an undeclared import is an outright ImportError. Here it *is* transitive —
    `netlogger-mcp` has carried it since 0.2.0, and omiss-mcp depends on netlogger-mcp.

    That makes the declaration easier to omit and no safer to omit. Measured 2026-10-18:
    `netlogger-mcp==0.1.10` — a resolution the floor `>=0.1.2` permits — pulls no
    `certifi`. So without a direct declaration, whether this server verifies against a
    current root set depends on which version of a sibling the user happens to resolve.
    """
    pyproject = (SRC_DIR.parent / "pyproject.toml").read_text()
    deps = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert re.search(r'^\s*"certifi', deps, re.MULTILINE), (
        "omiss.py imports certifi but [project] dependencies does not declare it; "
        "inheriting it from netlogger-mcp depends on which version resolves"
    )


def test_every_outbound_call_verifies():
    """Guarantee #8: a new fetch path cannot quietly skip the context.

    Scanned across the whole package rather than one file. There is one fetch here
    today; lotw-mcp, qrz-mcp and eqsl-mcp each turned out to have two, and a check
    written against the file you happen to be editing is a check that misses the other
    one.

    Line by line rather than by matching balanced parentheses: a regex for the whole
    call ends at the first ")", which is the one inside "_context()", so it would read a
    call that passes no context as though it did.
    """
    calls = [(py_file.name, i, line)
             for py_file in _py_files()
             for i, line in enumerate(py_file.read_text().splitlines(), 1)
             if "urllib.request.urlopen(" in line]
    assert calls, "no urlopen call found; has the fetch path moved?"
    for filename, number, line in calls:
        assert "context=_context()" in line, (
            f"{filename}:{number} opens a connection without a verifying context: "
            f"{line.strip()}"
        )
