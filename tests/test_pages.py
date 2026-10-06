"""The page parsers, on the bundled synthetic samples (omiss.net's markup)."""

from __future__ import annotations

from importlib.resources import files

import pytest

from omiss_mcp import pages
from omiss_mcp.html import PageChanged, tables


def sample(name: str) -> str:
    return files("omiss_mcp.samples").joinpath(name).read_text(encoding="utf-8")


def test_net_schedule():
    s = pages.net_schedule(sample("index.html"))
    first = s["nets"][0]
    assert first == {
        "band": "10m", "time_utc": "18:00", "frequency_mhz": "28.525", "frequency_window": "28.500-28.695",
        "window_low_mhz": "28.500", "window_high_mhz": "28.695",
        "weekdays_utc": ["Sat", "Sun"], "seasonal_utc": [{"weekdays": ["Wed"], "months": [4, 5, 6]}],
        "days": ["Sat & Sun", "Wed: April-June"], "footnotes": [1],
        "coordinator": {"callsign": "W1XAA", "name": "ALICE", "om_number": 1001},
    }
    twelve = s["nets"][1]
    assert twelve["holiday_time_utc"] == "16:30"
    assert twelve["days"] == ["Sat, Sun", "Wed: July-September"]  # a footnote mark with no space
    assert s["nets"][3]["footnotes"] == [1, 2, 3]
    assert "footnotes" not in s["nets"][2]  # "Daily", no marks
    assert set(s["footnotes"]) == {"1", "2", "3"}
    assert s["notes"] == ["Days and times are in UTC. Nets that are Friday night local are displayed as Sat UTC."]
    assert s["holidays"][1] == {
        "date": "2026-02-16", "name": "Washington's Birthday (observed)",
        "note": "Washington's Birthday is also Presidents Day (observed)",
    }


def test_members_and_no_match():
    found = pages.members(sample("searchResults.html"))
    assert [m["callsign"] for m in found] == ["W1OMS", "W1OMSX"]
    assert found[0]["first_responder"] == ["Firefighter"]
    # The roster prints US Eastern time: EDT (UTC-4) in September, EST (UTC-5) in March.
    assert found[0]["last_checkin"] == "2026-09-26T23:30:02Z"
    assert found[1]["silent_key"] is True and found[1]["last_checkin"] == "2019-03-07T07:05:00Z"
    assert pages.members(sample("searchResults_none.html")) == []


def test_checkin_history():
    h = pages.checkin_history(sample("listCheckinHistory.html"))
    assert h["matches"] == 3 and h["site_limit"] == 100
    assert h["nets"][1] == {"net_id": 30000, "name": "OMISS 40m SSB Late Net",
                            "time": "2026-09-26T04:55:23Z", "checkin_count": 1}
    assert h["nets"][2]["time"] == "2026-09-05T03:56:35Z"


def test_net_checkins():
    n = pages.net_checkins(sample("displayCheckinHistory.html"))
    assert n["net_control"] == "W3XCC" and n["relays"] == ["W2XBB", "W4XDD"]
    assert n["archived_by"] == "W3XCC" and n["closed_at_utc"] == "19:28"
    assert n["checkin_count"] == 3 and n["log_notes"] == ["NET CLOSED:19:28"]
    assert n["checkins"][0]["member_id"] == "1003" and n["checkins"][0]["remarks"] == "2 CALLS"
    assert n["checkins"][1]["om_number"] == 999 and n["checkins"][1]["remarks"] == "1"
    visitor = n["checkins"][2]  # not a member: no ID, and the note is a remark
    assert "om_number" not in visitor and "member_id" not in visitor
    assert visitor["remarks"] == "FAM needs #'s"
    assert "[email removed]" in n["notes"] and "@" not in n["notes"]
    assert pages.net_checkins(sample("displayCheckinHistory_none.html")) is None


def test_statehood():
    rows = pages.statehood_schedule(sample("statehoodSchedule.html"))
    assert rows[0] == {"date": "2025-03-13", "free_call_states": ["Delaware"]}
    assert rows[2] == {"date": "2026-01-01", "free_call_states": ["Washington", "Idaho"]}


def test_officers():
    by = {s["section"]: s for s in pages.officers(sample("vipListing.html"))}
    assert by["Officers of the Society"]["people"][0] == {
        "role": "President", "callsign": "W1XAA", "name": "ALICE", "om_number": 1001}
    assert by["Band Coordinators"]["people"][1]["role"] == "40m-Early-Band Coord"
    assert by["Ethics Committee"]["people"][0]["note"] == "Chair"
    assert by["Appointees"]["people"] == [
        {"role": "Awards Manager", "callsign": "W3XCC", "name": "CAROL", "om_number": 1003},
        {"role": "Chaplain", "vacant": True},
    ]
    assert by["Charter Members"]["text"] == ["OM #01-110"]
    assert by["Past Presidents"]["people"][0] == {
        "term": "1982-1983", "callsign": "K1XFF", "name": "FRANK", "om_number": 16, "silent_key": True}
    assert by["OM Of The Year"]["people"][1] == {"year": 1996, "vacant": True}
    assert by["OM Of The Year"]["people"][2] == {"year": 2015, "callsign": "K7XII", "name": "IVY", "om_number": 1007}


def test_awards_and_rules():
    assert [a["award_id"] for a in pages.awards(sample("awardRecipients.html"))] == ["100GOLD", "ALPHABETSOUP", "5x325"]
    r = pages.award_rules(sample("awardRules.html"))
    gold = r["awards"][0]
    assert gold["award_id"] == "100GOLD" and gold["summary"].startswith("Work 100 OM members")
    assert gold["rules"]["Contacts Start Date"] == "You may use contacts starting from January 1, 2004."
    assert "Application and Submission" not in gold["rules"]  # printed with a postal address
    assert gold["how_to_apply"]
    assert "how_to_apply" not in r["awards"][1]


def test_award_recipients():
    r = pages.award_recipients(sample("GenAwardReport.html"))
    assert r["name"] == "Alphabet Soup"
    assert r["recipients"][0] == {"certificate": "1", "callsign": "K1XFF", "om_number": 16,
                                  "issued": "2006-07-20", "silent_key": True}
    assert r["recipients"][2]["issued"] == "2026-08-01" and r["recipients"][2]["notes"] == "Electronic"


def test_statistics():
    s = pages.net_statistics(sample("statistics.html"))
    assert s["nets_total"] == 1000 and s["nets_per_band"]["40m Late"] == 100
    assert s["last_net_per_band"]["80m Late"] == "2026-04-05T05:45:12Z"
    assert s["leaderboards"]["king_of_the_hill_total_checkins_current_month"]["entries"][0] == {
        "rank": 1, "callsign": "W1OMS", "count": 42}
    assert s["leaderboards"]["ncs_total_nets_last_90_days"]["entries"][1]["callsign"] == "W4XDD"
    assert s["last_checkin_by_state"]["CT"]["160m"] == {"callsign": "W1OMS", "time": "2026-09-10T19:30:02Z"}
    assert s["last_checkin_by_state"]["PA"] == {"10m": {"callsign": "W3XCC", "time": "2026-08-16T18:44:20Z"}}


@pytest.mark.parametrize("parser", [
    pages.net_schedule, pages.members, pages.checkin_history, pages.net_checkins,
    pages.statehood_schedule, pages.officers, pages.awards, pages.award_rules,
    pages.award_recipients, pages.net_statistics,
])
def test_a_changed_page_is_reported_not_guessed(parser):
    with pytest.raises(PageChanged):
        parser("<html><body><h1>Down for maintenance</h1></body></html>")


def test_nested_tables_are_separate():
    t = tables("<table><tr><td>a</td><td><table><tr><td>b</td></tr></table></td></tr></table>")
    assert t == [[["b"]], [["a", ""]]]


def test_schedule_days_and_windows_are_structured():
    b = {n["band"]: n for n in pages.net_schedule(sample("index.html"))["nets"]}
    assert b["10m"]["weekdays_utc"] == ["Sat", "Sun"]
    assert b["10m"]["seasonal_utc"] == [{"weekdays": ["Wed"], "months": [4, 5, 6]}]
    assert b["12m"]["weekdays_utc"] == ["Sat", "Sun"]  # "Sat, Sun"
    assert b["20m"]["weekdays_utc"] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]  # "Daily"
    assert b["160m"]["weekdays_utc"] == ["Mon", "Sat", "Sun"]  # "Sat & Sun & Mon"
    assert (b["10m"]["window_low_mhz"], b["10m"]["window_high_mhz"]) == ("28.500", "28.695")
    assert (b["12m"]["window_low_mhz"], b["12m"]["window_high_mhz"]) == ("24.973", "24.987")  # +/- 7 kHz
    assert (b["160m"]["window_low_mhz"], b["160m"]["window_high_mhz"]) == ("1.920", "1.940")


def test_parse_days_refuses_what_it_cant_read():
    assert pages.parse_days(["Sat & Sun"]) == (["Sat", "Sun"], [])
    assert pages.parse_days(["Wed: October-December"]) == ([], [{"weekdays": ["Wed"], "months": [10, 11, 12]}])
    assert pages.parse_days(["Wed: November-February"])[1][0]["months"] == [11, 12, 1, 2]
    assert pages.parse_days(["Sat & Sun", "second Tuesday"]) is None
    assert pages.parse_days(["Wed: Spring-Fall"]) is None


def test_hyphenated_award_ids_are_kept_whole():
    """WAS-KN4OM read as WAS, colliding with the basic WAS award; Patriot-NCSQTR and PATRIOT-TOPOP read as
    Patriot and PATRIOT, and the case-insensitive de-duplication then dropped one of them."""
    links = sample("awardRecipients.html").replace(
        '<a href="GenAwardReport.php?AwardID=ALPHABETSOUP">Alphabet Soup</a>',
        '<a href="GenAwardReport.php?AwardID=ALPHABETSOUP">Alphabet Soup</a>'
        '<a href="GenAwardReport.php?AwardID=WAS-KN4OM">KN4OM in all States</a>'
        '<a href="GenAwardReport.php?AwardID=Patriot-NCSQTR">Patriot NCS</a>'
        '<a href="GenAwardReport.php?AwardID=PATRIOT-TOPOP">Patriot Top Op</a>')
    ids = [a["award_id"] for a in pages.awards(links)]
    assert {"WAS-KN4OM", "Patriot-NCSQTR", "PATRIOT-TOPOP"} <= set(ids)
    assert not {"WAS", "Patriot", "PATRIOT"} & set(ids)

    rules = sample("awardRules.html")
    start = rules.index('<div class="sidebarbox">')
    end = rules.index('<div class="sidebarbox">', start + 1)
    box = rules[start:end].replace("100GOLD", "WAS-KN4OM")
    r = pages.award_rules(rules[:start] + box + rules[start:])
    kn4om = r["awards"][0]
    assert kn4om["award_id"] == "WAS-KN4OM" and kn4om["rules"]  # the detail div (WAS-KN4OMx) was found


def test_award_id_naming_two_awards_fails_loudly():
    page = sample("awardRecipients.html").replace(
        '<a href="GenAwardReport.php?AwardID=ALPHABETSOUP">Alphabet Soup</a>',
        '<a href="GenAwardReport.php?AwardID=ALPHABETSOUP">Alphabet Soup</a>'
        '<a href="GenAwardReport.php?AwardID=ALPHABETSOUP">Alphabet Soup</a>'  # the same award twice: kept once
        '<a href="GenAwardReport.php?AwardID=alphabetsoup">Something Else</a>')  # a different award: an error
    with pytest.raises(pages.PageChanged):
        pages.awards(page)

