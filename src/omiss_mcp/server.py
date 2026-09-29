"""omiss-mcp: OMISS nets, members, check-in history, Statehood, officers and awards. Read-only."""

from __future__ import annotations

import os
import sys
import urllib.parse
from datetime import datetime, timezone
from importlib.resources import files
from typing import Any

from fastmcp import FastMCP
from netlogger_mcp import settings as netlogger_settings
from netlogger_mcp.limiter import Cache, RateLimiter
from netlogger_mcp.netlogger import LIMITS as NETLOGGER_LIMITS
from netlogger_mcp.netlogger import NetLoggerError, NetLoggerSource

from . import __contract_version__, __spec_version__, __version__
from .html import OmissError
from .omiss import LIMITS, OmissSource

mcp = FastMCP(
    "omiss-mcp",
    version=__version__,
    instructions=(
        "OMISS (Old Man International Sideband Society): the net schedule and holidays, "
        "OMISS nets on the air now, member lookup by callsign or OM number, past nets and "
        "who checked in, the 40m Statehood schedule, officers, awards and their rules and "
        "recipients, and net statistics. Read-only, from omiss.net's public pages, which "
        "are read slowly and cached (see age_seconds). Past nets come from "
        "omiss_checkin_history, which gives the net_id omiss_net_checkins needs; award IDs "
        "come from omiss_awards. omiss_nets_on_air asks NetLogger, which needs the user's "
        "callsign once: if it says so, ask the user and call omiss_set_callsign."
    ),
)


def _mock() -> bool:
    return os.getenv("OMISS_MCP_MOCK") == "1"


# Sample page per path, for OMISS_MCP_MOCK=1. Synthetic data, never the network.
_SAMPLES = {
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
}


def _mock_fetch(url: str) -> tuple[int, bytes, str | None]:
    parts = urllib.parse.urlparse(url)
    page = parts.path.rsplit("/", 1)[-1]
    query = urllib.parse.parse_qs(parts.query)
    name = _SAMPLES[page]
    # The samples hold one member and one net; anything else isn't found.
    if page == "searchResults.php" and query.get("searchText", [""])[0] not in ("W1OMS", "999"):
        name = "searchResults_none.html"
    if page == "displayCheckinHistory.php" and query.get("id", [""])[0] != "30001":
        name = "displayCheckinHistory_none.html"
    return 200, files("omiss_mcp.samples").joinpath(name).read_bytes(), None


def _mock_netlogger_fetch(url: str) -> tuple[int, bytes, str | None]:
    routine = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1].removesuffix(".php")
    return 200, files("netlogger_mcp.samples").joinpath(f"{routine}.xml").read_bytes(), None


_source: OmissSource | None = None
_netlogger: NetLoggerSource | None = None


def _get_source() -> OmissSource:
    """One source per process, so the request spacing covers every tool call."""
    global _source
    if _source is None:
        if _mock():
            # No spacing: samples aren't a server to be polite to.
            _source = OmissSource(fetch=_mock_fetch, limiter=RateLimiter(LIMITS, window=0.0))
        else:
            _source = OmissSource()
    return _source


def _as_of() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(method: str, *args) -> dict[str, Any]:
    try:
        return getattr(_get_source(), method)(*args)
    except OmissError as e:
        return {"error": str(e), "as_of_utc": _as_of()}
    except Exception:
        return {"error": "omiss-mcp hit an unexpected problem", "as_of_utc": _as_of()}


NEEDS_CALLSIGN = {
    "error": "OMISS nets on the air come from NetLogger, which needs to know which station "
             "is asking.",
    "needs_callsign": True,
    "next_step": "Ask the user for their amateur radio callsign, then call omiss_set_callsign "
                 "with it. It is asked only once.",
}


def _version_info_payload() -> dict[str, Any]:
    return {
        "service_name": "omiss-mcp",
        "service_version": __version__,
        "spec_version": __spec_version__,
        "contract_version": __contract_version__,
    }


@mcp.tool()
def get_version_info() -> dict[str, Any]:
    """Get omiss-mcp's version, the omiss.net layout it reads, and the version of
    the records it returns.

    Returns:
        service_name, service_version (PyPI), spec_version (omiss.net layout), contract_version.
    """
    return _version_info_payload()


@mcp.tool()
def omiss_net_schedule() -> dict[str, Any]:
    """Get the OMISS net schedule: every net's band, UTC time, frequency and window,
    days, holiday time and band coordinator, and the next time it runs; the
    schedule's footnotes (holidays, winter schedule); and the federal holiday
    dates the holiday schedule follows. Days and times are UTC, so an evening
    net in the Americas falls on the previous local day; use next_utc and
    as_of_utc to work out "today" in the user's time zone.

    Returns:
        as_of_utc; nets with weekdays_utc, seasonal_utc, next_utc (or next_utc_note
        when it can't be worked out, e.g. winter-only nets); footnotes; notes; holidays.
    """
    return _run("net_schedule")


@mcp.tool()
def omiss_nets_on_air() -> dict[str, Any]:
    """List OMISS nets on the air now, from NetLogger.

    Returns:
        as_of_utc, and nets with server, name, frequency, band, mode, net control,
        when opened and how many are monitoring.
    """
    global _netlogger
    try:
        if _netlogger is None:
            callsign = netlogger_settings.load_callsign()
            if callsign is None:
                return {**NEEDS_CALLSIGN, "as_of_utc": _as_of()}
            if _mock():
                _netlogger = NetLoggerSource(callsign, "omiss-mcp", __version__,
                                             fetch=_mock_netlogger_fetch,
                                             limiter=RateLimiter(NETLOGGER_LIMITS), cache=Cache())
            else:
                _netlogger = NetLoggerSource(callsign, "omiss-mcp", __version__)
        return {"as_of_utc": _as_of(), **_netlogger.active_nets(name_like="OMISS")}
    except NetLoggerError as e:
        return {"error": str(e), "as_of_utc": _as_of()}
    except Exception:
        return {"error": "omiss-mcp hit an unexpected problem", "as_of_utc": _as_of()}


@mcp.tool()
def omiss_set_callsign(callsign: str) -> dict[str, Any]:
    """Save the user's amateur radio callsign, for omiss_nets_on_air. Needed once.

    NetLogger is told which station is asking. The callsign is shared with
    netlogger-mcp, if it's installed. Ask the user for their own callsign; don't guess it.

    Args:
        callsign: The user's callsign (e.g. KI7MT).

    Returns:
        The saved callsign.
    """
    global _netlogger
    try:
        saved = netlogger_settings.save_callsign(callsign)
    except NetLoggerError as e:
        return {"error": str(e), "as_of_utc": _as_of()}
    except OSError:
        return {"error": "the callsign couldn't be saved to the settings file", "as_of_utc": _as_of()}
    _netlogger = None
    return {"callsign": saved, "saved": True}


@mcp.tool()
def omiss_member_lookup(callsign: str | None = "", om_number: int | None = None) -> dict[str, Any]:
    """Look up one OMISS member by callsign or by OM number (give one).

    Args:
        callsign: The member's callsign (e.g. KI7MT).
        om_number: The member's OMISS number (e.g. 7212).

    Returns:
        found, and the member: OM number, callsign, first name, status (Current, Silent
        Key, ...), grid, state, county, QSL bureau envelopes on file, military service,
        first responder, last check-in.
    """
    return _run("member_lookup", callsign or None, om_number)


@mcp.tool()
def omiss_checkin_history(
    callsign: str | None = "",
    om_number: int | None = None,
    band: str | None = "",
    date: str | None = "",
    net_control: str | None = "",
) -> dict[str, Any]:
    """List past OMISS nets, newest first: all of them, or only those a member
    checked in to, on a band, on a date, or run by a net control. omiss.net shows
    the latest 100 matches.

    Args:
        callsign: Only nets this station checked in to (e.g. KI7MT).
        om_number: Only nets this OMISS member checked in to (e.g. 7212).
        band: Only nets on this band: 10m, 12m, 15m, 17m, 20m, 40m, 80m or 160m.
        date: Only nets on this date: YYYY, YYYY-MM or YYYY-MM-DD (UTC).
        net_control: Only nets this station ran as net control.

    Returns:
        matches (the site's total), showing, and nets with net_id, name, time (UTC)
        and check-in count. Use net_id with omiss_net_checkins.
    """
    return _run("checkin_history", callsign or None, om_number, band or None, date or None, net_control or None)


@mcp.tool()
def omiss_net_checkins(net_id: int) -> dict[str, Any]:
    """Get one past OMISS net: its net control, relays, frequency, net control's
    notes, and the check-in list.

    Args:
        net_id: The net's ID, from omiss_checkin_history.

    Returns:
        The net, and its check-ins with callsign, name, city, state, county, grid,
        status, QSL info and OM number.
    """
    return _run("net_checkins", net_id)


@mcp.tool()
def omiss_statehood_schedule() -> dict[str, Any]:
    """Get the 40m Statehood schedule: each 40m net date and its free-call states,
    and the next one.

    Returns:
        next, and schedule with date and free_call_states.
    """
    return _run("statehood_schedule")


@mcp.tool()
def omiss_officers() -> dict[str, Any]:
    """List OMISS's officers, directors, band coordinators, committees, appointees,
    past presidents and other VIPs.

    Returns:
        sections, each with people (role, callsign, name, OM number).
    """
    return _run("officers")


@mcp.tool()
def omiss_awards() -> dict[str, Any]:
    """List the OMISS awards that have recipients, with the award IDs the other
    award tools take.

    Returns:
        awards with award_id and name.
    """
    return _run("awards")


@mcp.tool()
def omiss_award_rules(award_id: str | None = "") -> dict[str, Any]:
    """Get an OMISS award's rules, or (no award_id) every award's name, ID and summary.

    Args:
        award_id: The award's ID, from omiss_awards or this tool (e.g. ALPHABETSOUP).

    Returns:
        The award's qualifications, contact rules, enhancements and documentation.
        How to apply is on omiss.net (rules_url).
    """
    return _run("award_rules", award_id or None)


@mcp.tool()
def omiss_award_recipients(
    award_id: str,
    callsign: str | None = "",
    om_number: int | None = None,
    limit: int | None = 100,
) -> dict[str, Any]:
    """List who holds an OMISS award, newest certificates first, or check one member.

    Args:
        award_id: The award's ID, from omiss_awards (e.g. ALPHABETSOUP).
        callsign: Only this station's certificates.
        om_number: Only this member's certificates.
        limit: At most this many (default 100).

    Returns:
        total, and recipients with certificate, callsign, OM number, date issued,
        band info, endorsements and notes.
    """
    return _run("award_recipients", award_id, callsign or None, om_number, limit if limit is not None else 100)


@mcp.tool()
def omiss_net_statistics(state: str | None = "", top: int | None = 10) -> dict[str, Any]:
    """Get OMISS net statistics for the last 52 weeks: nets per band, the last net on
    each band, and the leaderboards (most check-ins, most nets as net control).

    Args:
        state: Also give this state's last check-in on each band (2 letters, e.g. ID).
        top: How many leaderboard entries (default 10, at most 50).

    Returns:
        nets_total, nets_per_band, last_net_per_band, leaderboards, and
        last_checkin_by_band if state was given.
    """
    return _run("net_statistics", state or None, top if top is not None else 10)


def main() -> None:
    """Run the omiss-mcp server."""
    transport = "stdio"
    port = 8015
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--transport" and i < len(sys.argv) - 1:
            transport = sys.argv[i + 1]
        if arg == "--port" and i < len(sys.argv) - 1:
            port = int(sys.argv[i + 1])

    if transport == "streamable-http":
        mcp.run(transport=transport, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
