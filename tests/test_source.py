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


# ---------------------------------------------------------------------------
# as_of_utc and next_utc (#4, #5)
# ---------------------------------------------------------------------------

from datetime import datetime, timezone  # noqa: E402

from omiss_mcp.omiss import next_run  # noqa: E402


def _schedule_at(now: datetime) -> dict:
    body = files("omiss_mcp.samples").joinpath("index.html").read_bytes()
    source = OmissSource(fetch=lambda url: (200, body, None), limiter=RateLimiter(LIMITS, window=0.0),
                         now=lambda: now)
    r = source.net_schedule()
    return r | {"by_band": {n["band"]: n for n in r["nets"]}}


def test_every_response_has_as_of():
    r = _schedule_at(datetime(2026, 9, 28, 23, 19, 5, tzinfo=timezone.utc))
    assert r["as_of_utc"] == "2026-09-28T23:19:05Z"


def test_next_utc_on_a_monday_evening():
    # Monday 23:19 UTC: the daily 20m net ran at 18:30; the weekend nets are Saturday.
    b = _schedule_at(datetime(2026, 9, 28, 23, 19, tzinfo=timezone.utc))["by_band"]
    assert b["20m"]["next_utc"] == "2026-09-29T18:30:00Z" and b["20m"]["next_is_holiday"] is False
    assert b["10m"]["next_utc"] == "2026-10-03T18:00:00Z"
    assert b["12m"]["next_utc"] == "2026-09-30T20:30:00Z"  # Wednesdays July-September
    assert "next_utc" not in b["80m Late"] and "winter" in b["80m Late"]["next_utc_note"]
    assert "next_utc" not in b["160m"]


def test_next_utc_on_a_holiday():
    # Christmas 2026 is a Friday and on the page's holiday list. Nets citing
    # footnote 1 run that day, at their holiday time if they have one.
    b = _schedule_at(datetime(2026, 12, 24, 22, 0, tzinfo=timezone.utc))["by_band"]
    assert b["10m"]["next_utc"] == "2026-12-25T18:00:00Z" and b["10m"]["next_is_holiday"] is True
    assert b["12m"]["next_utc"] == "2026-12-25T16:30:00Z"  # its holiday time
    assert b["20m"]["next_utc"] == "2026-12-25T18:30:00Z" and b["20m"]["next_is_holiday"] is False


def test_a_net_already_started_today_is_next_tomorrow():
    b = _schedule_at(datetime(2026, 9, 29, 18, 30, tzinfo=timezone.utc))["by_band"]
    assert b["20m"]["next_utc"] == "2026-09-30T18:30:00Z"


def test_unreadable_days_get_a_note_not_a_guess():
    net = {"band": "20m", "time_utc": "18:30", "days": ["Every other full moon"]}
    assert "next_utc_note" in next_run(net, set(), datetime(2026, 9, 28, tzinfo=timezone.utc))


def test_winter_nets_carry_a_season():
    b = _schedule_at(datetime(2026, 9, 28, 23, 19, tzinfo=timezone.utc))["by_band"]
    assert b["160m"]["season"] == "winter" and b["80m Late"]["season"] == "winter"
    assert "season" not in b["20m"]
