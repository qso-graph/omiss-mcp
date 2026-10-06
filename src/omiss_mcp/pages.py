"""Parsers for each omiss.net page. Each takes the page's HTML and returns records.

Only the fields listed here are returned. Anything else a page prints (postal
addresses, emails, the SQL a page echoes in a comment) is never read.
"""

from __future__ import annotations

import html as _html
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

from .html import PageChanged, clean, find_table, main_content, one_line, prepare, tables, text_of

BANDS = ("10m", "12m", "15m", "17m", "20m", "40m", "80m", "160m")

MEMBER_STATUS = {
    "Curr": "Current",
    "SK": "Silent Key",
    "EXP": "Expired License",
    "NID": "Not in Directory; could not find on call servers",
    "CR": "Call Reissued; vanity program",
    "RFDB": "Removed From (FCC) Database",
    "NI": "Never Issued",
    "REV": "Revoked",
    "RBQ": "Removed by Request",
}

FIRST_RESPONDER = {
    "D": "Dispatcher",
    "E": "EMT or Paramedic",
    "F": "Firefighter",
    "P": "Police",
    "R": "Civilian volunteer supporting first responders",
}

_DT_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})")


def utc_time(value: str) -> str | None:
    """'2026-04-5 05:45:12' (UTC) -> '2026-04-05T05:45:12Z'."""
    m = _DT_RE.search(value or "")
    if not m:
        return None
    y, mo, d, h, mi, s = (int(g) for g in m.groups())
    try:
        return datetime(y, mo, d, h, mi, s).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


# The member roster's "Date Last Checkin" is US Eastern time, not UTC: the same
# net shows 4 hours later in the (UTC) check-in history in summer, 5 in winter.
EASTERN = ZoneInfo("America/New_York")


def eastern_to_utc(value: str) -> str | None:
    """'2026-09-27 16:59:10' (US Eastern) -> '2026-09-27T20:59:10Z'."""
    m = _DT_RE.search(value or "")
    if not m:
        return None
    y, mo, d, h, mi, s = (int(g) for g in m.groups())
    try:
        local = datetime(y, mo, d, h, mi, s, tzinfo=EASTERN)
    except ValueError:
        return None
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int(value: str) -> int | None:
    value = (value or "").strip().lstrip("#")
    return int(value) if value.isdigit() else None


def _drop_empty(rec: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in rec.items() if v not in (None, "", [])}


def _silent_key(call: str) -> tuple[str, bool]:
    """'WA7HYD_(SK)' -> ('WA7HYD', True). Other marks ('_(REV)') are dropped
    from the callsign; the member search's status says what they mean."""
    m = re.fullmatch(r"(.*?)_\(([A-Z]+)\)", call.strip())
    if m:
        return m.group(1), m.group(2) == "SK"
    return call.strip(), False


def _band_label(header: str) -> str:
    """'Late 40 meters' -> '40m Late'."""
    m = re.search(r"(Late\s+)?(\d+)\s*meters", header, re.I)
    if not m:
        return one_line(header)
    return f"{m.group(2)}m" + (" Late" if m.group(1) else "")


# ---------------------------------------------------------------------------
# index.php: the net schedule and holidays
# ---------------------------------------------------------------------------

_SLOT_RE = re.compile(r"(\d{4})z\s*-*>\s*([\d.]+)\s*MHz\s*\(([^)]*)\)", re.I)
_HOLIDAY_TIME_RE = re.compile(r"\((\d{4})z\s+on\s+holidays\)", re.I)
_FOOTNOTE_REF_RE = re.compile(r"\s*\[fn:([\d,\s]+)\]")
_HOLIDAY_RE = re.compile(r"^([A-Z][a-z]+ \d{1,2}, \d{4})\s*\([A-Za-z]+\):\s*(.+)$")


WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_WEEKDAY_RE = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\b", re.I)
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")
_MONTH_RANGE_RE = re.compile(r"^(.*?):\s*([A-Za-z]+)\s*-\s*([A-Za-z]+)$")
_WINDOW_RANGE_RE = re.compile(r"^([\d.]+)\s*-\s*([\d.]+)$")
_WINDOW_OFFSET_RE = re.compile(r"^\+/-\s*([\d.]+)\s*kHz$", re.I)


def _month(name: str) -> int | None:
    name = name.strip().casefold()
    for i, m in enumerate(_MONTHS, 1):
        if m.casefold() == name or m[:3].casefold() == name:
            return i
    return None


def _weekdays(text: str) -> list[str] | None:
    """'Sat & Sun' -> ['Sat', 'Sun']; 'Daily' -> all seven; None if unreadable."""
    if text.strip().casefold() == "daily":
        return list(WEEKDAYS)
    found = [d.title()[:3] for d in _WEEKDAY_RE.findall(text)]
    rest = _WEEKDAY_RE.sub("", text)
    if not found or re.sub(r"[\s&,]|and", "", rest, flags=re.I):
        return None
    return [d for d in WEEKDAYS if d in found]


def parse_days(lines: list[str]) -> tuple[list[str], list[dict[str, Any]]] | None:
    """The schedule's day lines as (weekdays, seasonal extras), or None if any
    line can't be read. 'Wed: April-June' is Wednesdays in months 4-6."""
    weekdays: list[str] = []
    seasonal: list[dict[str, Any]] = []
    for line in lines:
        m = _MONTH_RANGE_RE.match(line)
        if m:
            days, first, last = _weekdays(m.group(1)), _month(m.group(2)), _month(m.group(3))
            if not days or not first or not last:
                return None
            months = list(range(first, last + 1)) if first <= last else list(range(first, 13)) + list(range(1, last + 1))
            seasonal.append({"weekdays": days, "months": months})
            continue
        days = _weekdays(line)
        if days is None:
            return None
        weekdays += [d for d in days if d not in weekdays]
    return [d for d in WEEKDAYS if d in weekdays], seasonal


def frequency_window(center: str, window: str) -> tuple[str, str] | None:
    """'28.500-28.695' or '+/- 7 kHz' (around the net frequency) as (low, high) MHz."""
    m = _WINDOW_RANGE_RE.match(window.strip())
    if m:
        return m.group(1), m.group(2)
    m = _WINDOW_OFFSET_RE.match(window.strip())
    if m:
        try:
            f, off = float(center), float(m.group(1)) / 1000
        except ValueError:
            return None
        places = max(3, len(center.partition(".")[2]))
        return f"{f - off:.{places}f}", f"{f + off:.{places}f}"
    return None


def net_schedule(page: str) -> dict[str, Any]:
    # Footnote marks (<sup>1,2</sup>) become "[fn:1,2]" so they survive as text.
    content = re.sub(r"<sup>\s*([\d,\s]+?)\s*</sup>", r" [fn:\1]", main_content(page), flags=re.I)
    rows = find_table(content, ["Band", "Net Time & Frequency", "Day", "Band Coordinator"], "the net schedule")
    nets = []
    for row in rows:
        if len(row) < 4:
            continue
        band, slot, days, coord = row[:4]
        m = _SLOT_RE.search(slot)
        if not m:
            raise PageChanged("the net schedule")
        hol = _HOLIDAY_TIME_RE.search(slot)
        day_lines, refs = [], []
        for line in days.split("\n"):
            for r in _FOOTNOTE_REF_RE.findall(line):
                refs += [int(x) for x in re.findall(r"\d", r)]
            line = _FOOTNOTE_REF_RE.sub("", line)
            line = re.sub(r"\s*-+>\s*", ": ", line).strip()
            if line:
                day_lines.append(line)
        parts = [p.strip() for p in coord.split(",")]
        coordinator = {}
        if parts and parts[0]:
            coordinator["callsign"] = parts[0].upper()
        if len(parts) > 1 and parts[1]:
            coordinator["name"] = parts[1]
        if len(parts) > 2 and _int(parts[2]) is not None:
            coordinator["om_number"] = _int(parts[2])
        parsed = parse_days(day_lines)
        window = frequency_window(m.group(2), m.group(3))
        nets.append(_drop_empty({
            "band": band,
            "time_utc": f"{m.group(1)[:2]}:{m.group(1)[2:]}",
            "frequency_mhz": m.group(2),
            "frequency_window": m.group(3).strip(),
            "window_low_mhz": window[0] if window else None,
            "window_high_mhz": window[1] if window else None,
            "weekdays_utc": parsed[0] if parsed else None,
            "seasonal_utc": parsed[1] if parsed else None,
            "holiday_time_utc": f"{hol.group(1)[:2]}:{hol.group(1)[2:]}" if hol else None,
            "days": day_lines,
            "footnotes": sorted(set(refs)),
            "coordinator": coordinator or None,
        }))
    if not nets:
        raise PageChanged("the net schedule")

    footnotes = {
        int(n): text_of(t)
        for n, t in re.findall(r"<p>\s*\[fn:(\d)\](.*?)</p>", content, re.S | re.I)
    }
    notes = [text_of(t) for t in re.findall(r"<p>\s*<em>\s*<strong>(.*?)</p>", content, re.S | re.I)]

    holidays = []
    for table in tables(content):
        if not table or "Federal Holidays" not in table[0][0]:
            continue
        for row in table[1:]:
            lines = row[0].split("\n")
            m = _HOLIDAY_RE.match(lines[0].strip())
            if not m:
                continue
            try:
                day = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
            except ValueError:
                continue
            note = " ".join(line.strip() for line in lines[1:]).removeprefix("Note:").strip()
            holidays.append(_drop_empty({"date": day, "name": m.group(2).strip(), "note": note}))

    return {
        "nets": nets,
        "footnotes": {str(k): v for k, v in sorted(footnotes.items())},
        "notes": notes,
        "holidays": holidays,
    }


# ---------------------------------------------------------------------------
# searchResults.php: members
# ---------------------------------------------------------------------------

_MEMBER_HEADER = ["OM #", "Call", "First Name", "Status", "Grid", "State", "County",
                  "#Env in Bureau", "Military", "First Resp", "Date Last Checkin"]


def members(page: str) -> list[dict[str, Any]]:
    rows = find_table(main_content(page), _MEMBER_HEADER, "the member search")
    out = []
    for row in rows:
        if len(row) < len(_MEMBER_HEADER):
            continue  # "No data matched your search"
        om, call, first, status, grid, state, county, env, military, first_resp, last = row[:11]
        om_number = _int(om)
        if om_number is None:
            continue
        call, sk = _silent_key(call)
        responder = [FIRST_RESPONDER.get(c, c) for c in re.findall(r"[A-Z]", first_resp)]
        out.append(_drop_empty({
            "om_number": om_number,
            "callsign": call.upper(),
            "first_name": first,
            "status": status,
            "status_meaning": MEMBER_STATUS.get(status),
            "silent_key": True if sk or status == "SK" else None,
            "grid": grid,
            "state": state,
            "county": county,
            "qsl_bureau_envelopes": _int(env),
            "military": one_line(military),
            "first_responder": responder,
            "last_checkin": eastern_to_utc(last),
        }))
    return out


# ---------------------------------------------------------------------------
# listCheckinHistory.php: past nets
# ---------------------------------------------------------------------------

_HISTORY_COUNT_RE = re.compile(r"Search returned (\d+) match(?:es)?(?: \(showing last (\d+)\))?", re.I)
_HISTORY_NET_RE = re.compile(
    r'<input type="radio" name="id" value="(\d+)"\s*/?>\s*(.*?)\s+--\s+'
    r"(\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{2}:\d{2})\s*UTC\s*<i>\((\d+) Check-?ins?\)</i>",
    re.I,
)


def checkin_history(page: str) -> dict[str, Any]:
    content = prepare(main_content(page))
    m = _HISTORY_COUNT_RE.search(content)
    if not m:
        raise PageChanged("the check-in history")
    nets = [
        {
            "net_id": int(nid),
            "name": one_line(_html.unescape(name)),
            "time": utc_time(when),
            "checkin_count": int(count),
        }
        for nid, name, when, count in _HISTORY_NET_RE.findall(content)
    ]
    return {
        "matches": int(m.group(1)),
        "showing": len(nets),
        "site_limit": int(m.group(2)) if m.group(2) else None,
        "nets": nets,
    }


# ---------------------------------------------------------------------------
# displayCheckinHistory.php: one past net
# ---------------------------------------------------------------------------

_ARCHIVED_RE = re.compile(r"Archived by\s*(\S*)\s+on\s+(.*?)\s*UTC", re.I)
_CHECKIN_HEADER = ["#", "Callsign", "City/ Country", "State", "Name", "OMISS#", "QSL Info",
                   "County", "Grid", "Status"]
_HEADER_FIELDS = {
    "subject": "name",
    "ncs was": "net_control",
    "relays were": "relays",
    "frequency was": "frequency",
    "net closed at": "closed_at_utc",
}


def net_checkins(page: str) -> dict[str, Any] | None:
    """One past net, or None if there is no net with that ID."""
    content = main_content(page)
    m = _ARCHIVED_RE.search(text_of(content))
    if not m:
        raise PageChanged("the net check-in list")
    if not m.group(1):
        return None  # the page is served, but empty: no such net

    # The net's header lines and net control's notes, before the check-in table.
    start = content.find("</h5>")
    end = content.find("<table", start)
    head = text_of(content[start + 5: end if end > 0 else len(content)])
    net: dict[str, Any] = {"archived_by": m.group(1).upper(), "archived": utc_time(m.group(2))}
    notes = []
    for line in head.split("\n"):
        key, sep, value = line.partition(":")
        field = _HEADER_FIELDS.get(key.strip().casefold()) if sep else None
        if field:
            value = value.strip()
            if field == "relays":
                net[field] = [c.strip().upper() for c in value.split(",") if c.strip()]
            elif field == "net_control":
                net[field] = value.upper()
            else:
                net[field] = value
        else:
            notes.append(line)
    net["notes"] = "\n".join(notes)

    rows = find_table(content, _CHECKIN_HEADER, "the net check-in list")
    checkins, log_lines = [], []
    for row in rows:
        if len(row) < len(_CHECKIN_HEADER):
            continue
        serial, call, city, state, name, member, qsl, county, grid, status = row[:10]
        if not call:
            # The logger's own lines ("# # NET OPENED: 20:30Z"), not a station.
            line = member.lstrip("# ").strip()
            if line:
                log_lines.append(line)
            continue
        # The archive joins NetLogger's member ID and remarks in one cell:
        # "#11055# 1 CALL", "# # FAM needs #'s", "#15719# formerly KJ5RPM".
        cell = re.match(r"^#\s*(\d*)\s*#\s*(.*)$", member)
        member_id, remarks = (cell.group(1), cell.group(2).strip()) if cell else (member, "")
        checkins.append(_drop_empty({
            "serial": _int(serial.rstrip(".")),
            "callsign": call.upper(),
            "name": name,
            "city": city,
            "state": state,
            "county": county,
            "grid": grid,
            "status": status,
            "qsl_info": qsl,
            "member_id": member_id,
            "om_number": int(member_id) if member_id.isdigit() else None,
            "remarks": remarks,
        }))
    net["log_notes"] = log_lines
    return _drop_empty(net) | {"checkin_count": len(checkins), "checkins": checkins}


# ---------------------------------------------------------------------------
# statehoodSchedule.php
# ---------------------------------------------------------------------------


def statehood_schedule(page: str) -> list[dict[str, Any]]:
    rows = find_table(main_content(page), ["40m Net Date", "Free Call States"], "the Statehood schedule")
    out = []
    for row in rows:
        if len(row) < 2:
            continue
        try:
            day = datetime.strptime(row[0].strip(), "%m/%d/%Y").date().isoformat()
        except ValueError:
            continue
        states = [s for s in (c.strip() for c in row[1:]) if s and s.casefold() != "n/a"]
        out.append({"date": day, "free_call_states": states})
    if not out:
        raise PageChanged("the Statehood schedule")
    return out


# ---------------------------------------------------------------------------
# vipListing.php: officers and other VIPs
# ---------------------------------------------------------------------------

_VIP_RE = re.compile(
    r"^(?P<role>.*?)\s*(?<![A-Za-z0-9-])"
    r"(?P<call>(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])[A-Z0-9]{3,}(?:_\([A-Z]+\))?)"
    r"\s+(?P<name>\S.*?)\s+#(?P<om>\d+)\b\s*(?P<note>.*)$"
)


def officers(page: str) -> list[dict[str, Any]]:
    content = main_content(page)
    sections = []
    for title, body in re.findall(r"<h3>([^<]*)</h3>\s*<pre>(.*?)</pre>", content, re.S | re.I):
        title = text_of(title).rstrip(":").strip()
        people, pending_role, other = [], None, []
        for raw in _html.unescape(body).split("\n"):
            line = raw.strip()
            if not line:
                continue
            m = _VIP_RE.match(line)
            if m:
                call, sk = _silent_key(m.group("call"))
                note = m.group("note").strip()
                if note.upper() in ("(SK)", "SK"):
                    sk, note = True, ""
                role = m.group("role").strip() or pending_role
                pending_role = None
                person = {"callsign": call, "name": m.group("name").strip(), "om_number": int(m.group("om"))}
                if role and re.fullmatch(r"\d{4}-\d{4}", role):
                    person = {"term": role} | person
                elif role and re.fullmatch(r"\d{4}", role):
                    person = {"year": int(role)} | person
                elif role:
                    person = {"role": role} | person
                people.append(_drop_empty(person | {"silent_key": True if sk else None, "note": clean(note)}))
            elif "OPEN POSITION" in line.upper():
                when = re.match(r"^(\d{4})(?:-(\d{4}))?\s", line)
                vacant = {"role": pending_role, "vacant": True}
                if when and when.group(2):
                    vacant = {"term": f"{when.group(1)}-{when.group(2)}", "vacant": True}
                elif when:
                    vacant = {"year": int(when.group(1)), "vacant": True}
                people.append(_drop_empty(vacant))
                pending_role = None
            elif "#" not in line and not re.search(r"\d", line.split()[0] if line.split() else ""):
                pending_role = clean(line)  # a role heading; the person is on the next line
            else:
                other.append(clean(line))
        if pending_role:
            other.append(pending_role)
        sections.append(_drop_empty({"section": title, "people": people, "text": other}))
    if not sections:
        raise PageChanged("the VIP listing")
    return sections


# ---------------------------------------------------------------------------
# Awards
# ---------------------------------------------------------------------------

# Award IDs are letters and digits, and a few have hyphens (WAS-KN4OM, MIL-1ST-RESP, PATRIOT-TOPOP,
# Patriot-NCSQTR); cutting at the hyphen made WAS-KN4OM read as WAS.
_AWARD_ID = r"[A-Za-z0-9][A-Za-z0-9-]*"
_AWARD_LINK_RE = re.compile(r'<a href="GenAwardReport\.php\?AwardID=(' + _AWARD_ID + r')"\s*>(.*?)</a>', re.I)


def awards(page: str) -> list[dict[str, str]]:
    seen: dict[str, str] = {}
    out = []
    for award_id, name in _AWARD_LINK_RE.findall(main_content(page)):
        name = text_of(name)
        if award_id.upper() in seen:
            if seen[award_id.upper()] == name:
                continue  # the same award linked twice
            # Two different awards behind one ID: never drop one silently (WAS-KN4OM once read as WAS).
            raise PageChanged(f"the award list (ID {award_id} names two awards)")
        seen[award_id.upper()] = name
        out.append({"award_id": award_id, "name": name})
    if not out:
        raise PageChanged("the award list")
    return out


# Printed by the rules page with a postal address; never returned.
_RULES_DROPPED = {"application and submission"}


def award_rules(page: str) -> dict[str, Any]:
    content = main_content(page)
    note = re.search(r"<h3>\s*<center>(.*?)</center>\s*</h3>", content, re.S | re.I)
    rules = []
    for box in content.split('<div class="sidebarbox">')[1:]:
        h = re.search(r"<h3>(.*?)(?:<a [^>]*AwardID=(" + _AWARD_ID + r")[^>]*>.*?</a>)?\s*</h3>", box, re.S | re.I)
        if not h or not h.group(2):
            continue
        award_id = h.group(2)
        summary = re.search(r"<p>(.*?)</p>", box, re.S | re.I)
        detail = re.search(r'<div[^>]*id="' + re.escape(award_id) + r'x"[^>]*>(.*?)</div>', box, re.S | re.I)
        fields: dict[str, str] = {}
        last = None
        for line in text_of(detail.group(1)).split("\n") if detail else []:
            key, sep, value = line.partition(":")
            if sep and len(key) <= 40:
                last = key.strip()
                fields[last] = value.strip()
            elif last:
                fields[last] = f"{fields[last]} {line}".strip()
        dropped = [k for k in fields if k.casefold() in _RULES_DROPPED]
        for k in dropped:
            del fields[k]
        rules.append(_drop_empty({
            "award_id": award_id,
            "name": text_of(h.group(1)),
            "summary": text_of(summary.group(1)).replace("(more...)", "").strip() if summary else None,
            "rules": fields,
            "how_to_apply": "See the award's rules on omiss.net" if dropped else None,
        }))
    if not rules:
        raise PageChanged("the award rules")
    return {"note": text_of(note.group(1)) if note else None, "awards": rules}


def _short_date(value: str) -> str | None:
    """'07/20/06' -> '2006-07-20'. Two-digit years after this year are 19xx."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", value.strip())
    if not m:
        return None
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000 if y <= date.today().year % 100 else 1900
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


_RECIPIENT_HEADER = ["Certificate Number", "Current Callsign", "OM #", "Date Issued", "Band Info",
                     "Endorsements", "Notes"]


def award_recipients(page: str) -> dict[str, Any]:
    content = main_content(page)
    title = re.search(r"<h3>(.*?)</h3>", content, re.S | re.I)
    rows = find_table(content, _RECIPIENT_HEADER, "the award recipient report")
    out = []
    for row in rows:
        if len(row) < len(_RECIPIENT_HEADER):
            continue
        cert, call, om, issued, band, endorse, notes = row[:7]
        call, sk = _silent_key(call)
        out.append(_drop_empty({
            "certificate": cert,
            "callsign": call.upper(),
            "om_number": _int(om),
            "issued": _short_date(issued) or issued,
            "band_info": band,
            "endorsements": endorse,
            "notes": notes,
            "silent_key": True if sk else None,
        }))
    return {"name": text_of(title.group(1)) if title else None, "recipients": out}


# ---------------------------------------------------------------------------
# statistics.php
# ---------------------------------------------------------------------------


def net_statistics(page: str) -> dict[str, Any]:
    content = main_content(page)
    all_tables = tables(content)

    def band_row(first: str) -> tuple[list[str], list[str]] | None:
        for t in all_tables:
            if len(t) >= 2 and t[0] and one_line(t[0][0]).casefold() == first.casefold():
                return [_band_label(h) for h in t[0][1:]], t[1]
        return None

    counts = band_row("# Nets")
    last = band_row("Last Net")
    if counts is None or last is None:
        raise PageChanged("the net statistics")
    window = text_of(re.search(r"<h5>(.*?)</h5>", content, re.S | re.I).group(1)) if "<h5>" in content else ""
    oldest = re.search(r"oldest entry date is:\s*(\S+ \S+)", window)
    newest = re.search(r"newest entry date is:\s*(\S+ \S+)", window)

    by_state: dict[str, dict[str, Any]] = {}
    for t in all_tables:
        if not t or not one_line(t[0][0]).casefold().startswith("last checkin"):
            continue
        bands = [_band_label(h) for h in t[0][1:]]
        for row in t[1:]:
            if not row or not re.fullmatch(r"[A-Z]{2}", row[0].strip()):
                continue
            entry = {}
            for band, cell in zip(bands, row[1:]):
                parts = cell.split("\n")
                if len(parts) >= 3:
                    entry[band] = {"callsign": parts[0].strip().upper(), "time": utc_time(f"{parts[1]} {parts[2]}")}
            by_state[row[0].strip()] = entry

    boards = {}
    for title, body in re.findall(r"<h3>((?:King of the Hill|NCS Total Nets)[^<]*)</h3>(.*?</table>)", content, re.S | re.I):
        entries = []
        for t in tables(body):
            for row in t:
                if len(row) >= 3 and _int(row[2]) is not None:
                    entries.append({"rank": _int(row[0].rstrip(".")), "callsign": row[1].upper(), "count": _int(row[2])})
        key = re.sub(r"[^a-z0-9]+", "_", one_line(title).casefold()).strip("_")
        boards[key] = {"title": one_line(title), "entries": entries}

    labels, values = counts
    return {
        "period_start": utc_time(oldest.group(1)) if oldest else None,
        "period_end": utc_time(newest.group(1)) if newest else None,
        "nets_total": _int(values[0]) if values else None,
        "nets_per_band": {b: _int(v) for b, v in zip(labels, values[1:])},
        "last_net_per_band": {b: utc_time(v) for b, v in zip(last[0], last[1][1:]) if utc_time(v)},
        "leaderboards": boards,
        "last_checkin_by_state": by_state,
    }
