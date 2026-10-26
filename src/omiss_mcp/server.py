"""omiss-mcp: OMISS nets, members, check-in history, Statehood, officers and awards.

Read-only apart from omiss_set_callsign, which saves the operator's callsign to
netlogger-mcp's settings file so NetLogger can be told which station is asking.
"""

from __future__ import annotations

import os
import sys
import urllib.parse
from datetime import datetime, timezone
from importlib.resources import files
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from netlogger_mcp import settings as netlogger_settings
from netlogger_mcp.limiter import Cache, RateLimiter
from netlogger_mcp.netlogger import LIMITS as NETLOGGER_LIMITS
from netlogger_mcp.netlogger import NetLoggerError, NetLoggerSource

from . import __contract_version__, __spec_version__, __version__
from .html import OmissError
from .omiss import LIMITS, OmissSource, match_schedule

mcp = FastMCP(
    "omiss-mcp",
    version=__version__,
    instructions=(
        "OMISS (Old Man International Sideband Society): the net schedule and holidays, "
        "OMISS nets on the air now, member lookup by callsign or OM number, past nets and "
        "who checked in, the 40m Statehood schedule, officers, awards and their rules and "
        "recipients, net statistics, and award eligibility for a list of callsigns. "
        "Read-only, from omiss.net's public pages, which "
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
    "rosterXML.php": "rosterXML.xml",
    "militaryRoster.php": "militaryRoster.html",
    "firstResponderRoster.php": "firstResponderRoster.html",
    "stateCapitalRoster.php": "stateCapitalRoster.html",
    "SKRoster.php": "SKRoster.html",
}


def _mock_fetch(url: str) -> tuple[int, bytes, str | None]:
    parts = urllib.parse.urlparse(url)
    page = parts.path.rsplit("/", 1)[-1]
    query = urllib.parse.parse_qs(parts.query)
    name = _SAMPLES[page]
    # The samples hold one member and one net; anything else isn't found.
    searching = query.get("searchText", [""])[0]
    if page == "searchResults.php" and searching not in ("W1OMS", "999"):
        name = "searchResults_none.html"
    if page == "displayCheckinHistory.php" and query.get("id", [""])[0] != "30001":
        name = "displayCheckinHistory_none.html"
    return 200, files("omiss_mcp.samples").joinpath(name).read_bytes(), None


def _mock_netlogger_fetch(url: str) -> tuple[int, bytes, str | None]:
    # omiss-mcp's own NetLogger sample, so mock mode doesn't depend on what
    # netlogger-mcp happens to bundle (its samples changed in 0.1.6).
    routine = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1].removesuffix(".php")
    sample = files("omiss_mcp.samples").joinpath(f"netlogger_{routine}.xml")
    return 200, sample.read_bytes(), None


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


def _run(method: str, *args: Any) -> dict[str, Any]:
    try:
        answer: dict[str, Any] = getattr(_get_source(), method)(*args)
        return answer
    except OmissError as e:
        raise ToolError(str(e)) from e
    except Exception as e:
        # Deliberately not str(e): this branch catches what was not foreseen, and an
        # unforeseen exception's text is not known to be safe to show.
        raise ToolError("omiss-mcp hit an unexpected problem") from e


# Needing a callsign was a *successful* result carrying needs_callsign and next_step,
# which left the model to notice from the payload that nothing had happened. The
# specification is explicit that without the flag "the LLM would not be able to see that
# an error occurred and self-correct". The whole instruction is now the message, so the
# caller is told it failed and told exactly how to fix it.
NEEDS_CALLSIGN_MESSAGE = (
    "OMISS nets on the air come from NetLogger, which needs to know which station is "
    "asking. Ask the user for their amateur radio callsign, then call omiss_set_callsign "
    "with it. It is asked only once."
)

# MCP 2026-07-28 tool annotations. The defaults are pessimistic — a tool that declares
# nothing is advertised as destructive, non-idempotent and open-world, and the
# specification tells a client it may keep a human in the loop for an operation like that.
#
# Issue #37 says "every tool in this repo is read-only". That is not so, and the hints are
# set out per group rather than once so a reader cannot come away believing it.
_READS_OMISS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    # Reaches omiss.net, or NetLogger, which are outside this host.
    "openWorldHint": True,
}
_ANSWERS_FROM_THE_PACKAGE = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    # Reports versions carried in the wheel. It opens no connection.
    "openWorldHint": False,
}
_SAVES_THE_CALLSIGN = {
    # The one tool here that writes. It saves the operator's callsign to netlogger-mcp's
    # settings file, so readOnlyHint is false and saying otherwise would be a plain
    # untruth about what the tool does.
    "readOnlyHint": False,
    # It replaces one value the operator set themselves. The specification reserves
    # destructive for updates that destroy — this overwrites a single setting with the
    # caller's own new value, and nothing else is lost.
    "destructiveHint": False,
    # Saving the same callsign twice leaves the same state, so a client may safely retry.
    "idempotentHint": True,
    # It writes locally and opens no connection; NetLogger is not told anything until the
    # next lookup.
    "openWorldHint": False,
}


def _version_info_payload() -> dict[str, Any]:
    return {
        "service_name": "omiss-mcp",
        "service_version": __version__,
        "spec_version": __spec_version__,
        "contract_version": __contract_version__,
    }


@mcp.tool(annotations=_ANSWERS_FROM_THE_PACKAGE)
def get_version_info() -> dict[str, Any]:
    """Get omiss-mcp's version, the omiss.net layout it reads, and the version of
    the records it returns.

    Returns:
        service_name, service_version (PyPI), spec_version (omiss.net layout),
        contract_version.
    """
    return _version_info_payload()


@mcp.tool(annotations=_READS_OMISS)
def omiss_net_schedule() -> dict[str, Any]:
    """Get the OMISS net schedule: every net's band, UTC time, frequency and window,
    days, holiday time and band coordinator, and the next time it runs; the
    schedule's footnotes (holidays, winter schedule); and the federal holiday
    dates the holiday schedule follows. Days and times are UTC, so an evening
    net in the Americas falls on the previous local day; use next_utc and
    as_of_utc to work out "today" in the user's time zone. next_utc is the
    listed start: nets often open early for check-ins, and a net on the air now
    shows next_utc as its next run, so ask omiss_nets_on_air whether one is open.

    Returns:
        as_of_utc; nets with weekdays_utc, seasonal_utc, next_utc (or next_utc_note
        when it can't be worked out, e.g. winter-only nets); footnotes; notes; holidays.
    """
    return _run("net_schedule")


@mcp.tool(annotations=_READS_OMISS)
def omiss_nets_on_air() -> dict[str, Any]:
    """List OMISS nets on the air now, from NetLogger, each matched to OMISS's own net
    schedule.

    A net on NetLogger is an OMISS net when it matches a scheduled one (its frequency
    is in that net's window, on a day it runs, near its start time) or its name says
    OMISS. Each says which scheduled net it is.

    Returns:
        as_of_utc, and nets with server, name, frequency, band, mode, net control,
        when opened, how many are monitoring, matched_by (schedule, name) and
        omiss_net (the scheduled net: band, time, frequency, coordinator). servers
        counts every net NetLogger listed on each server, before the OMISS filter.
    """
    global _netlogger
    try:
        if _netlogger is None:
            callsign = netlogger_settings.load_callsign()
            if callsign is None:
                raise ToolError(NEEDS_CALLSIGN_MESSAGE)
            if _mock():
                _netlogger = NetLoggerSource(
                    callsign, "omiss-mcp", __version__,
                    fetch=_mock_netlogger_fetch,
                    limiter=RateLimiter(NETLOGGER_LIMITS), cache=Cache(),
                )
            else:
                _netlogger = NetLoggerSource(callsign, "omiss-mcp", __version__)
        live = _netlogger.active_nets(name_like="")
        note = None
        try:
            schedule = _get_source().net_schedule()["nets"]
        except OmissError:
            schedule, note = [], "OMISS's schedule couldn't be read; matched by name only"
        nets = []
        for net in live.get("nets", []):
            by = []
            scheduled = match_schedule(net, schedule)
            if scheduled:
                by.append("schedule")
            names = f"{net.get('name', '')} {net.get('current_name', '')}".upper()
            if "OMISS" in names:
                by.append("name")
            if by:
                nets.append({**net, "matched_by": by,
                             **({"omiss_net": scheduled} if scheduled else {})})
        result = {"as_of_utc": _as_of(), **live, "total": len(nets), "nets": nets}
        if note:
            result["note"] = note
        return result
    except ToolError:
        # The callsign refusal above is already the right shape; re-flagging it as an
        # unforeseen problem would discard the instruction the caller needs.
        raise
    except NetLoggerError as e:
        raise ToolError(str(e)) from e
    except Exception as e:
        raise ToolError("omiss-mcp hit an unexpected problem") from e


@mcp.tool(annotations=_SAVES_THE_CALLSIGN)
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
        raise ToolError(str(e)) from e
    except OSError as e:
        raise ToolError("the callsign couldn't be saved to the settings file") from e
    _netlogger = None
    return {"callsign": saved, "saved": True}


@mcp.tool(annotations=_READS_OMISS)
def omiss_member_lookup(
    callsign: str | None = "", om_number: int | None = None,
) -> dict[str, Any]:
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


@mcp.tool(annotations=_READS_OMISS)
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
    return _run("checkin_history", callsign or None, om_number, band or None,
                date or None, net_control or None)


@mcp.tool(annotations=_READS_OMISS)
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


@mcp.tool(annotations=_READS_OMISS)
def omiss_eligibility(callsigns: list[str]) -> dict[str, Any]:
    """For stations on a net: is each an OMISS member, and which award categories
    does it count for? From omiss.net's own rosters.

    Use it with a net's check-ins (netlogger-mcp's netlogger_checkins for a live
    net, or omiss_net_checkins for a past one) to see who you still need. Only the
    callsigns asked about are answered.

    Args:
        callsigns: Up to 200 callsigns (e.g. ["KI7MT", "W4DWS"]).

    Returns:
        callsigns, each with member (true/false), om_number, first_name, state,
        silent_key, military (branch, dates, award_code for each period of service),
        first_responder (roles with codes D/E/F/P/R, status) and state_capital
        (state), each only when the rosters list it.
    """
    return _run("eligibility", callsigns)


@mcp.tool(annotations=_READS_OMISS)
def omiss_statehood_schedule() -> dict[str, Any]:
    """Get the 40m Statehood schedule: each 40m net date and its free-call states,
    and the next one.

    Returns:
        next, and schedule with date and free_call_states.
    """
    return _run("statehood_schedule")


@mcp.tool(annotations=_READS_OMISS)
def omiss_officers() -> dict[str, Any]:
    """List OMISS's officers, directors, band coordinators, committees, appointees,
    past presidents and other VIPs.

    Returns:
        sections, each with people (role, callsign, name, OM number).
    """
    return _run("officers")


@mcp.tool(annotations=_READS_OMISS)
def omiss_awards() -> dict[str, Any]:
    """List the OMISS awards that have recipients, with the award IDs the other
    award tools take.

    Returns:
        awards with award_id and name.
    """
    return _run("awards")


@mcp.tool(annotations=_READS_OMISS)
def omiss_award_rules(award_id: str | None = "") -> dict[str, Any]:
    """Get an OMISS award's rules, or (no award_id) every award's name, ID and summary.

    Args:
        award_id: The award's ID, from omiss_awards or this tool (e.g. ALPHABETSOUP).

    Returns:
        The award's qualifications, contact rules, enhancements and documentation.
        How to apply is on omiss.net (rules_url).
    """
    return _run("award_rules", award_id or None)


@mcp.tool(annotations=_READS_OMISS)
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
    return _run("award_recipients", award_id, callsign or None, om_number,
                limit if limit is not None else 100)


@mcp.tool(annotations=_READS_OMISS)
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


USAGE = """usage: omiss-mcp [--transport stdio|streamable-http] [--port N] [--version] [--help]

An MCP server: an AI app (Claude Desktop, Claude Code, ...) starts it and talks
to it over stdio. Run on its own it waits for that app; press Ctrl-C to stop.
Set up a client: https://github.com/qso-graph/omiss-mcp#quick-start

streamable-http binds 127.0.0.1 only: not another machine,
not a container.
"""


def main() -> None:
    """Run the omiss-mcp server."""
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(USAGE, end="")
        return
    if "--version" in sys.argv[1:]:
        print(f"omiss-mcp {__version__}")
        return
    transport = "stdio"
    port = 8015
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--transport" and i < len(sys.argv) - 1:
            transport = sys.argv[i + 1]
        if arg == "--port" and i < len(sys.argv) - 1:
            port = int(sys.argv[i + 1])

    # Written out rather than passed through: fastmcp takes a literal, and a
    # str that happens to hold the right word is not the same thing.
    if transport == "streamable-http":
        # Where it bound, said out loud. FastMCP binds 127.0.0.1 and takes
        # no host option, so this is never reachable from another machine
        # or from outside a container. Silent before this line.
        print(
            f"omiss-mcp on http://127.0.0.1:{port}/mcp - loopback only",
            file=sys.stderr,
        )
        mcp.run(transport="streamable-http", port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
