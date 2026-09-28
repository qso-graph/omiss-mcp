"""Being a good neighbour: spacing, back-off, caching, stale answers."""

from __future__ import annotations

from importlib.resources import files

import pytest

from netlogger_mcp.limiter import Cache, RateLimiter, SharedRateLimiter
from omiss_mcp import __version__
from omiss_mcp.html import OmissError
from omiss_mcp.omiss import LIMITS, SPACING, OmissSource, RateLimited, user_agent


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


class Site:
    """omiss.net, with a status to answer."""

    def __init__(self):
        self.calls = 0
        self.status = 200
        self.retry_after = None

    def __call__(self, url):
        self.calls += 1
        body = files("omiss_mcp.samples").joinpath("vipListing.html").read_bytes()
        return self.status, body if self.status == 200 else b"", self.retry_after


@pytest.fixture
def setup():
    clock, site = Clock(), Site()
    limiter = RateLimiter(LIMITS, window=SPACING, clock=clock)
    cache = Cache(clock=clock)
    return clock, site, OmissSource(fetch=site, limiter=limiter, cache=cache, sleep=clock.sleep)


def test_requests_are_spaced(setup):
    clock, site, source = setup
    start = clock.now
    for _ in range(3):
        source._cache = Cache(clock=clock)  # force a fetch each time
        source.officers()
    assert site.calls == 3
    assert clock.now - start >= 2 * SPACING  # waited its turn twice


def test_cached_answers_are_reused(setup):
    clock, site, source = setup
    source.officers()
    r = source.officers()
    assert site.calls == 1 and r["cached"] is True and r["stale"] is False


def test_429_backs_off_and_serves_stale(setup):
    clock, site, source = setup
    source.officers()
    clock.now += 2 * 86400  # the cached answer is now old
    site.status, site.retry_after = 429, "120"
    r = source.officers()
    assert r["stale"] is True and "slow down" in r["note"]
    site.status = 200
    r = source.officers()  # still backing off: no request
    assert site.calls == 2 and r["stale"] is True
    clock.now += 121
    assert source.officers()["stale"] is False and site.calls == 3


def test_503_backs_off_too(setup):
    clock, site, source = setup
    site.status = 503
    with pytest.raises(RateLimited) as e:
        source.officers()
    assert e.value.retry_after >= 60


def test_server_error_without_cache(setup):
    _, site, source = setup
    site.status = 500
    with pytest.raises(OmissError, match="HTTP 500"):
        source.officers()


def test_shared_spacing_across_processes(tmp_path):
    """Two sources with the same limits file take turns, like two AI apps would."""
    clock = Clock()
    path = tmp_path / "limits.json"
    a = SharedRateLimiter(LIMITS, path, window=SPACING, clock=clock)
    b = SharedRateLimiter(LIMITS, path, window=SPACING, clock=clock)
    assert a.try_acquire("omiss") == 0
    assert b.try_acquire("omiss") > 0
    clock.now += SPACING
    assert b.try_acquire("omiss") == 0


def test_user_agent_names_the_program():
    assert user_agent() == f"omiss-mcp/{__version__} (+https://github.com/qso-graph/omiss-mcp)"
    assert user_agent("MyLogger", "1.0").startswith("MyLogger/1.0 omiss-mcp/")
    with pytest.raises(OmissError):
        user_agent("My Logger", "1.0")


@pytest.mark.live
def test_live_schedule_and_officers():
    """Two real requests to omiss.net (run with --live)."""
    source = OmissSource(program_id="omiss-mcp-tests")
    s = source.net_schedule()
    assert len(s["nets"]) >= 5 and all(n["time_utc"] for n in s["nets"])
    o = source.officers()
    assert any(sec["section"] == "Officers of the Society" for sec in o["sections"])
