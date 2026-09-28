"""OMISS source: omiss.net's public pages, read politely.

A plain library. Programs can use it directly; the MCP server is a thin layer
over it.

    from omiss_mcp.omiss import OmissSource
    om = OmissSource(program_id="MyLogger", program_version="1.0")
    om.member_lookup(callsign="KI7MT")

omiss.net is a small club server, not an API, so every request is spaced: one
at a time, at most one every 2 seconds, shared by every copy on the computer.
Answers are cached, and a stale answer stands in when the site is down or has
asked us to slow down. Every value sent to it is checked first; no free text is
ever sent.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from netlogger_mcp.limiter import Cache, RateLimiter, SharedRateLimiter

from . import __version__, pages
from .html import OmissError, PageChanged, decode
from .paths import limits_file

log = logging.getLogger("omiss_mcp")

BASE = "https://www.omiss.net/Facelift/"
SOURCE = "omiss"
REPO = "https://github.com/qso-graph/omiss-mcp"

SPACING = 2.0  # seconds between requests to omiss.net, across every copy
LIMITS = {"omiss": 1}  # one request per SPACING window
MAX_SPACING_WAIT = 10.0  # wait this long for our turn; longer means we were told to back off
MIN_BACKOFF = 60.0  # after a 429 or 503
MAX_BACKOFF = 3600.0
MAX_BODY = 5 * 1024 * 1024

HOUR = 3600.0
DAY = 24 * HOUR
TTL = {
    "schedule": DAY,
    "member": DAY,
    "history": HOUR,
    "net": DAY,
    "statehood": DAY,
    "officers": DAY,
    "awards": 7 * DAY,
    "rules": 7 * DAY,
    "recipients": DAY,
    "statistics": HOUR,
}

_CALLSIGN_RE = re.compile(r"(?=.*[A-Z])(?=.*[0-9])[A-Z0-9/]{3,20}")
_DATE_RE = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")
_TOKEN_RE = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}")
_STATE_RE = re.compile(r"[A-Z]{2}")
MAX_OM_NUMBER = 999_999
MAX_NET_ID = 999_999_999

# fetch(url) -> (HTTP status, body, Retry-After header or None)
Fetch = Callable[[str], "tuple[int, bytes, str | None]"]


class RateLimited(OmissError):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = max(1, round(retry_after))
        super().__init__(f"omiss.net asked us to slow down; try again in {self.retry_after} s")


# ---------------------------------------------------------------------------
# Input validation: nothing reaches omiss.net that isn't one of these
# ---------------------------------------------------------------------------


def normalize_callsign(value: str | None, what: str = "callsign") -> str:
    value = (value or "").strip().upper()
    if not _CALLSIGN_RE.fullmatch(value):
        raise OmissError(f"{what} must be an amateur radio callsign (e.g. KI7MT)")
    return value


def om_number(value: str | int | None) -> int:
    text = str(value if value is not None else "").strip().lstrip("#")
    if not text.isdigit() or not 1 <= int(text) <= MAX_OM_NUMBER:
        raise OmissError("om_number must be an OMISS member number (e.g. 7212)")
    return int(text)


def band(value: str | None) -> str:
    text = (value or "").strip().lower().replace(" ", "")
    if text.isdigit():
        text += "m"
    if text not in pages.BANDS:
        raise OmissError(f"band must be one of {', '.join(pages.BANDS)}")
    return text


def history_date(value: str | None) -> str:
    """YYYY, YYYY-MM or YYYY-MM-DD, and a real date."""
    text = (value or "").strip()
    m = _DATE_RE.fullmatch(text)
    ok = bool(m)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)
        try:
            date(y, mo, d)
        except ValueError:
            ok = False
        ok = ok and 1982 <= y <= 2100
    if not ok:
        raise OmissError("date must be YYYY, YYYY-MM or YYYY-MM-DD (e.g. 2026-09)")
    return text


def net_id(value: str | int | None) -> int:
    text = str(value if value is not None else "").strip()
    if not text.isdigit() or not 1 <= int(text) <= MAX_NET_ID:
        raise OmissError("net_id must be a number (from omiss_checkin_history)")
    return int(text)


def state(value: str | None) -> str:
    text = (value or "").strip().upper()
    if not _STATE_RE.fullmatch(text):
        raise OmissError("state must be a 2-letter abbreviation (e.g. ID)")
    return text


def _program_token(program_id: str | None, program_version: str | None) -> str:
    """ADIF's PROGRAMID and PROGRAMVERSION as a User-Agent product, or ""."""
    if not program_id:
        if program_version:
            raise OmissError("program_version needs program_id")
        return ""
    for what, value in (("program_id", program_id), ("program_version", program_version)):
        if value is not None and not _TOKEN_RE.fullmatch(value):
            raise OmissError(f"{what} must be 1-64 characters without spaces or '/'")
    return f"{program_id}/{program_version} " if program_version else f"{program_id} "


def user_agent(program_id: str | None = None, program_version: str | None = None) -> str:
    return f"{_program_token(program_id, program_version)}omiss-mcp/{__version__} (+{REPO})"


# ---------------------------------------------------------------------------
# When a scheduled net next runs
# ---------------------------------------------------------------------------

# Footnotes that mark a net as winter-schedule only. The page says when the
# winter schedule runs but not exactly what it changes, so these nets get no
# next time rather than a guess.
WINTER_FOOTNOTES = {2, 3}
HOLIDAY_FOOTNOTE = 1  # "And Monday if it is a Legal Holiday, plus ..." (the holiday table's dates)
LOOKAHEAD_DAYS = 15


def season(net: dict[str, Any]) -> dict[str, Any]:
    """{'season': 'winter'} for a net that cites the winter-schedule footnotes,
    so weekdays_utc isn't read as year-round; {} otherwise."""
    return {"season": "winter"} if set(net.get("footnotes", [])) & WINTER_FOOTNOTES else {}


def next_run(net: dict[str, Any], holidays: set[str], now: datetime) -> dict[str, Any]:
    """{'next_utc': ..., 'next_is_holiday': bool} or {'next_utc_note': why not}.

    Regular days are the net's UTC weekdays (and seasonal extras). A net citing
    footnote 1 also runs on the page's holiday dates, at its holiday time if it
    has one.
    """
    notes = set(net.get("footnotes", []))
    if notes & WINTER_FOOTNOTES:
        return {"next_utc_note": "winter-schedule net; see footnotes " +
                ", ".join(str(n) for n in sorted(notes & WINTER_FOOTNOTES))}
    weekdays = net.get("weekdays_utc")
    if weekdays is None:
        return {"next_utc_note": "the net's days couldn't be read; see days"}
    seasonal = net.get("seasonal_utc", [])

    def at(day: date, hhmm: str) -> datetime:
        h, m = (int(x) for x in hhmm.split(":"))
        return datetime(day.year, day.month, day.day, h, m, tzinfo=timezone.utc)

    start = now.astimezone(timezone.utc)
    for offset in range(LOOKAHEAD_DAYS):
        day = start.date() + timedelta(days=offset)
        name = pages.WEEKDAYS[day.weekday()]
        holiday = HOLIDAY_FOOTNOTE in notes and day.isoformat() in holidays
        regular = name in weekdays or any(
            name in s["weekdays"] and day.month in s["months"] for s in seasonal)
        if not (holiday or regular):
            continue
        when = at(day, net.get("holiday_time_utc") or net["time_utc"]) if holiday else at(day, net["time_utc"])
        if when > start:
            return {"next_utc": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "next_is_holiday": holiday}
    return {"next_utc_note": f"doesn't run in the next {LOOKAHEAD_DAYS} days"}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _urllib_fetch(agent: str) -> Fetch:
    def fetch(url: str) -> tuple[int, bytes, str | None]:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": agent})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, resp.read(MAX_BODY + 1), resp.headers.get("Retry-After")
        except urllib.error.HTTPError as e:
            return e.code, e.read(MAX_BODY + 1) if e.fp else b"", e.headers.get("Retry-After")
    return fetch


def _retry_after(header: str | None) -> float:
    try:
        seconds = float(header) if header else 0.0
    except ValueError:
        seconds = 0.0
    return min(max(seconds, MIN_BACKOFF), MAX_BACKOFF)


class OmissSource:
    """Every stage-1 lookup on omiss.net's public pages. One instance per
    process: the spacing covers all its callers."""

    def __init__(
        self,
        program_id: str | None = None,
        program_version: str | None = None,
        fetch: Fetch | None = None,
        limiter: RateLimiter | SharedRateLimiter | None = None,
        cache: Cache | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        """``program_id`` and ``program_version``: the app built on this library,
        as in ADIF's PROGRAMID and PROGRAMVERSION (e.g. "MyLogger", "1.0");
        optional. They lead the User-Agent, so the site can tell programs apart."""
        self.user_agent = user_agent(program_id, program_version)
        self._fetch = fetch or _urllib_fetch(self.user_agent)
        self._limiter = limiter or SharedRateLimiter(LIMITS, limits_file(), window=SPACING)
        self._cache = cache or Cache()
        self._sleep = sleep
        self._now = now
        self._inflight = threading.Lock()  # one request at a time

    # ------------------------------------------------------------------

    def _turn(self) -> float:
        """Wait for our turn; return 0, or the seconds we've been told to back off."""
        waited = 0.0
        while True:
            wait = self._limiter.try_acquire("omiss")
            if wait <= 0:
                return 0.0
            if wait > MAX_SPACING_WAIT or waited + wait > MAX_SPACING_WAIT * 3:
                return wait
            self._sleep(wait)
            waited += wait

    def _page(self, kind: str, path: str, params: dict[str, str], build: Callable[[str], Any]) -> tuple[Any, dict[str, Any]]:
        """Fetch a page (or use the cache); the value and its freshness, with the
        time of the answer (as_of_utc)."""
        value, info = self._fetch_page(kind, path, params, build)
        return value, {"as_of_utc": self._now().strftime("%Y-%m-%dT%H:%M:%SZ"), **info}

    def _fetch_page(self, kind: str, path: str, params: dict[str, str], build: Callable[[str], Any]) -> tuple[Any, dict[str, Any]]:
        """Fetch a page, parse it with ``build``, cache the result."""
        key = kind + ":" + path + "?" + urllib.parse.urlencode(sorted(params.items()))
        hit = self._cache.get(key)
        if hit is not None and hit[2]:
            return hit[0], {"cached": True, "age_seconds": round(hit[1]), "stale": False}

        with self._inflight:
            hit = self._cache.get(key)  # another caller may have just fetched it
            if hit is not None and hit[2]:
                return hit[0], {"cached": True, "age_seconds": round(hit[1]), "stale": False}

            wait = self._turn()
            if wait > MAX_SPACING_WAIT:
                return self._stale_or_raise(hit, RateLimited(wait))
            if wait > 0:
                return self._stale_or_raise(hit, OmissError(
                    f"other requests from this computer are ahead in line; try again in {max(1, round(wait))} s"))

            url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
            try:
                status, body, retry_after = self._fetch(url)
            except (OSError, ValueError) as e:
                log.warning("omiss.net %s failed: %s", path, e)
                return self._stale_or_raise(hit, OmissError("omiss.net couldn't be reached"))

            if status in (429, 503):
                self._limiter.block_all(_retry_after(retry_after))
                return self._stale_or_raise(hit, RateLimited(_retry_after(retry_after)))
            if status >= 500:
                return self._stale_or_raise(hit, OmissError(f"omiss.net answered HTTP {status}"))
            if status == 404:
                return self._stale_or_raise(hit, PageChanged(path))
            if status != 200:
                return self._stale_or_raise(hit, OmissError(f"omiss.net answered HTTP {status}"))
            if len(body) > MAX_BODY:
                return self._stale_or_raise(hit, OmissError("omiss.net's page was too large"))

            try:
                value = build(decode(body))
            except OmissError as e:
                return self._stale_or_raise(hit, e)
            self._cache.set(key, value, TTL[kind])
            return value, {"cached": False, "age_seconds": 0, "stale": False}

    @staticmethod
    def _stale_or_raise(hit: tuple[Any, float, bool] | None, error: OmissError) -> tuple[Any, dict[str, Any]]:
        if hit is None:
            raise error
        return hit[0], {"cached": True, "age_seconds": round(hit[1]), "stale": True, "note": str(error)}

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def net_schedule(self) -> dict[str, Any]:
        """The OMISS nets: band, time, frequency, days, coordinator, and the next
        time each runs; and holidays."""
        value, info = self._page("schedule", "index.php", {}, pages.net_schedule)
        now = self._now()
        holidays = {h["date"] for h in value.get("holidays", [])}
        nets = [dict(n, **season(n), **next_run(n, holidays, now)) for n in value["nets"]]
        return {"source": SOURCE, **value, "nets": nets, **info}

    def member_lookup(self, callsign: str | None = None, om_number_: str | int | None = None) -> dict[str, Any]:
        """One member, by callsign or OM number (not both)."""
        if bool(callsign) == bool(om_number_):
            raise OmissError("give either callsign or om_number")
        if callsign:
            call = normalize_callsign(callsign)
            params = {"criteria": "call", "searchText": call, "scope": "all"}
        else:
            num = om_number(om_number_)
            params = {"criteria": "omnum", "searchText": str(num), "scope": "all"}
        found, info = self._page("member", "searchResults.php", params, pages.members)
        # The site matches partial callsigns; keep only the exact member.
        if callsign:
            found = [m for m in found if m.get("callsign") == call]
        else:
            found = [m for m in found if m.get("om_number") == num]
        result: dict[str, Any] = {"source": SOURCE, "found": bool(found), "members": found, **info}
        if not found:
            result["message"] = "no OMISS member matches"
        return result

    def checkin_history(
        self,
        callsign: str | None = None,
        om_number_: str | int | None = None,
        band_: str | None = None,
        date_: str | None = None,
        net_control: str | None = None,
    ) -> dict[str, Any]:
        """Past OMISS nets, newest first (the site shows the last 100), optionally
        only those a member checked in to, on a band, on a date, or run by a net control."""
        params = {
            "Band": band(band_) if band_ else "",
            "NCS": normalize_callsign(net_control, "net_control") if net_control else "",
            "OMNum": str(om_number(om_number_)) if om_number_ not in (None, "") else "",
            "Call": normalize_callsign(callsign) if callsign else "",
            "State": "",
            "County": "",
            "Grid": "",
            "Date": history_date(date_) if date_ else "",
            "Max": "",
            "Submit": "Search",
        }
        value, info = self._page("history", "listCheckinHistory.php", params, pages.checkin_history)
        filters = {k: v for k, v in (
            ("callsign", params["Call"]), ("om_number", params["OMNum"]), ("band", params["Band"]),
            ("date", params["Date"]), ("net_control", params["NCS"])) if v}
        return {"source": SOURCE, "filters": filters, **value, **info}

    def net_checkins(self, net_id_: str | int) -> dict[str, Any]:
        """One past net: net control, relays, notes, and the check-in list."""
        nid = net_id(net_id_)
        value, info = self._page("net", "displayCheckinHistory.php", {"id": str(nid)}, pages.net_checkins)
        if value is None:
            return {"source": SOURCE, "net_id": nid, "found": False,
                    "message": "no OMISS net has that ID", **info}
        return {"source": SOURCE, "net_id": nid, "found": True, **value, **info}

    def statehood_schedule(self, today: date | None = None) -> dict[str, Any]:
        """The 40m net dates and their free-call states, and the next one."""
        rows, info = self._page("statehood", "statehoodSchedule.php", {}, pages.statehood_schedule)
        today = today or self._now().date()
        upcoming = [r for r in rows if r["date"] >= today.isoformat()]
        return {"source": SOURCE, "next": upcoming[0] if upcoming else None, "schedule": rows, **info}

    def officers(self) -> dict[str, Any]:
        """Officers, band coordinators, committees, appointees and other VIPs."""
        sections, info = self._page("officers", "vipListing.php", {}, pages.officers)
        return {"source": SOURCE, "sections": sections, **info}

    def awards(self) -> dict[str, Any]:
        """Every award with recipients on record, with its award ID."""
        items, info = self._page("awards", "awardRecipients.php", {}, pages.awards)
        return {"source": SOURCE, "total": len(items), "awards": items, **info}

    def _award_id(self, value: str | None) -> str:
        """The site's own ID for an award, from its award list (never free text)."""
        text = (value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9]{1,32}", text):
            raise OmissError("award_id must be an ID from omiss_awards (e.g. ALPHABETSOUP)")
        listed = {a["award_id"].upper(): a["award_id"] for a in self.awards()["awards"]}
        if text.upper() not in listed:
            raise OmissError(f"no OMISS award has the ID {text}; omiss_awards lists them")
        return listed[text.upper()]

    def award_rules(self, award_id: str | None = None) -> dict[str, Any]:
        """One award's rules, or (no award_id) every award's name, ID and summary."""
        value, info = self._page("rules", "awardRules.php", {}, pages.award_rules)
        if not award_id:
            brief = [{k: a[k] for k in ("award_id", "name", "summary") if k in a} for a in value["awards"]]
            return {"source": SOURCE, "note": value.get("note"), "total": len(brief), "awards": brief, **info}
        wanted = (award_id or "").strip().upper()
        match = [a for a in value["awards"] if a["award_id"].upper() == wanted]
        if not match:
            if not re.fullmatch(r"[A-Za-z0-9]{1,32}", wanted):
                raise OmissError("award_id must be an ID from omiss_awards (e.g. ALPHABETSOUP)")
            raise OmissError(f"no OMISS award has the ID {award_id}; omiss_award_rules with no ID lists them")
        return {"source": SOURCE, "note": value.get("note"), **match[0],
                "rules_url": BASE + "awardRules.php", **info}

    def award_recipients(
        self,
        award_id: str,
        callsign: str | None = None,
        om_number_: str | int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Who holds an award, newest certificates first, optionally one member."""
        aid = self._award_id(award_id)
        call = normalize_callsign(callsign) if callsign else None
        num = om_number(om_number_) if om_number_ not in (None, "") else None
        try:
            limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            raise OmissError("limit must be a whole number") from None
        value, info = self._page("recipients", "GenAwardReport.php", {"AwardID": aid}, pages.award_recipients)
        rows = value["recipients"]
        if call:
            rows = [r for r in rows if r.get("callsign") == call]
        if num:
            rows = [r for r in rows if r.get("om_number") == num]
        rows = list(reversed(rows))  # the site lists oldest first
        return {"source": SOURCE, "award_id": aid, "name": value.get("name"),
                "total": len(rows), "returned": min(len(rows), limit), "recipients": rows[:limit], **info}

    def net_statistics(self, state_: str | None = None, top: int = 10) -> dict[str, Any]:
        """Nets per band, last net per band, leaderboards, and (for a state) its
        last check-in on each band."""
        st = state(state_) if state_ else None
        try:
            top = max(1, min(int(top), 50))
        except (TypeError, ValueError):
            raise OmissError("top must be a whole number") from None
        value, info = self._page("statistics", "statistics.php", {}, pages.net_statistics)
        out = {k: v for k, v in value.items() if k not in ("leaderboards", "last_checkin_by_state")}
        out["leaderboards"] = {
            k: {"title": b["title"], "entries": b["entries"][:top]} for k, b in value["leaderboards"].items()
        }
        if st:
            out["state"] = st
            out["last_checkin_by_band"] = value["last_checkin_by_state"].get(st, {})
        return {"source": SOURCE, **out, **info}
