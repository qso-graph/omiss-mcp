"""The MCP tools, in mock mode (bundled synthetic samples, no network)."""

from __future__ import annotations

import os

os.environ["OMISS_MCP_MOCK"] = "1"
os.environ["NETLOGGER_MCP_MOCK"] = "1"

import asyncio  # noqa: E402
import json  # noqa: E402
from importlib.resources import files  # noqa: E402

import jsonschema  # noqa: E402
import pytest  # noqa: E402
from fastmcp import Client  # noqa: E402

from omiss_mcp import server  # noqa: E402

TOOLS = {
    "get_version_info", "omiss_net_schedule", "omiss_nets_on_air", "omiss_set_callsign",
    "omiss_member_lookup", "omiss_checkin_history", "omiss_net_checkins",
    "omiss_statehood_schedule", "omiss_officers", "omiss_awards", "omiss_award_rules",
    "omiss_award_recipients", "omiss_net_statistics", "omiss_eligibility",
}

SCHEMA = json.loads(files("omiss_mcp.schema").joinpath("contract.schema.json").read_text())


@pytest.fixture(autouse=True)
def fresh():
    server._source = None
    server._netlogger = None
    yield
    server._source = None
    server._netlogger = None


def call(name: str, args: dict | None = None) -> dict:
    async def go():
        async with Client(server.mcp) as c:
            return (await c.call_tool(name, args or {})).data
    return asyncio.run(go())


def valid(result: dict, record: str) -> dict:
    assert "error" not in result, result
    jsonschema.validate(result, {"$ref": f"#/$defs/{record}", "$defs": SCHEMA["$defs"]})
    return result


def test_tool_list():
    async def go():
        async with Client(server.mcp) as c:
            return {t.name for t in await c.list_tools()}
    assert asyncio.run(go()) == TOOLS


def test_version_info():
    r = call("get_version_info")
    assert r["service_name"] == "omiss-mcp" and r["contract_version"] == "0.3"


def test_schedule():
    valid(call("omiss_net_schedule"), "net_schedule")


def test_member_lookup():
    r = valid(call("omiss_member_lookup", {"callsign": "w1oms"}), "member_lookup")
    assert [m["callsign"] for m in r["members"]] == ["W1OMS"]  # not W1OMSX, which the site also matched
    r = valid(call("omiss_member_lookup", {"om_number": 999}), "member_lookup")
    assert r["found"] and r["members"][0]["om_number"] == 999
    r = valid(call("omiss_member_lookup", {"callsign": "K9ZZZ"}), "member_lookup")
    assert r["found"] is False
    assert "error" in call("omiss_member_lookup", {})
    assert "error" in call("omiss_member_lookup", {"callsign": "W1OMS", "om_number": 999})


def test_history_and_net():
    r = valid(call("omiss_checkin_history", {"callsign": "W1OMS", "band": "20m", "date": "2026-09"}), "checkin_history")
    assert r["filters"] == {"callsign": "W1OMS", "band": "20m", "date": "2026-09"}
    net_id = r["nets"][0]["net_id"]
    n = valid(call("omiss_net_checkins", {"net_id": net_id}), "net_checkins")
    assert n["found"] and n["checkin_count"] == 3
    n = valid(call("omiss_net_checkins", {"net_id": 5}), "net_checkins")
    assert n["found"] is False
    assert "error" in call("omiss_checkin_history", {"band": "6m"})
    assert "real date" in call("omiss_checkin_history", {"date": "2026-13"})["error"]
    assert "YYYY" in call("omiss_checkin_history", {"date": "Sept 2026"})["error"]


def test_statehood_officers_awards():
    valid(call("omiss_statehood_schedule"), "statehood_schedule")
    valid(call("omiss_officers"), "officers")
    a = valid(call("omiss_awards"), "awards")
    assert a["total"] == 3
    valid(call("omiss_award_rules"), "award_rules")
    r = valid(call("omiss_award_rules", {"award_id": "100gold"}), "award_rules")
    assert r["award_id"] == "100GOLD" and r["rules_url"].endswith("awardRules.php#100GOLD")
    r = valid(call("omiss_award_recipients", {"award_id": "alphabetsoup", "limit": 2}), "award_recipients")
    assert r["total"] == 3 and r["returned"] == 2 and r["recipients"][0]["certificate"] == "3"
    r = valid(call("omiss_award_recipients", {"award_id": "ALPHABETSOUP", "om_number": 999}), "award_recipients")
    assert [x["callsign"] for x in r["recipients"]] == ["W1OMS"]
    assert "error" in call("omiss_award_recipients", {"award_id": "NOPE"})


def test_statistics():
    r = valid(call("omiss_net_statistics", {"state": "ct", "top": 1}), "net_statistics")
    assert r["state"] == "CT" and "160m" in r["last_checkin_by_band"]
    assert all(len(b["entries"]) == 1 for b in r["leaderboards"].values())
    r = valid(call("omiss_net_statistics"), "net_statistics")
    assert "last_checkin_by_band" not in r


def test_nets_on_air_needs_a_callsign_once():
    r = call("omiss_nets_on_air")
    assert r["needs_callsign"] is True
    assert "error" in call("omiss_set_callsign", {"callsign": "not a call"})
    assert call("omiss_set_callsign", {"callsign": "ki7mt"}) == {"callsign": "KI7MT", "saved": True}
    r = call("omiss_nets_on_air")
    nets = {n["name"]: n for n in r["nets"]}
    assert set(nets) == {"OMISS 20m SSB Net", "Sideband Saturday", "OMISS Informal Net"}
    assert r["total"] == 3
    assert nets["OMISS 20m SSB Net"]["matched_by"] == ["schedule", "name"]
    assert nets["OMISS 20m SSB Net"]["omiss_net"]["band"] == "20m"
    # an OMISS net logged under a name without "OMISS", found by the schedule (#11)
    assert nets["Sideband Saturday"]["matched_by"] == ["schedule"]
    assert nets["Sideband Saturday"]["omiss_net"]["band"] == "80m Late"
    assert nets["OMISS Informal Net"]["matched_by"] == ["name"]
    assert "omiss_net" not in nets["OMISS Informal Net"]


def test_eligibility():
    r = valid(call("omiss_eligibility", {"callsigns": ["w1oms", "W2XBB", "W3XCC", "KX0AA", "N0NE", "W1OMS"]}),
              "eligibility")
    by = {c["callsign"]: c for c in r["callsigns"]}
    assert list(by) == ["W1OMS", "W2XBB", "W3XCC", "KX0AA", "N0NE"]  # in order, once each
    w1 = by["W1OMS"]
    assert w1["member"] and w1["om_number"] == 999
    assert [m["branch"] for m in w1["military"]] == ["USN", "USNR"]
    assert {x["code"] for x in w1["first_responder"]["roles"]} == {"E", "F"}
    assert by["W2XBB"]["state_capital"] == {"state": "RI"}
    assert by["W3XCC"]["om_number"] == 1003  # the roster's "W3XCC." still matches
    assert by["KX0AA"]["silent_key"] is True
    assert by["N0NE"] == {"callsign": "N0NE", "member": False}
    for bad in ([], ["not a call"], ["W1OMS"] * 0 + [f"W{i}AA" for i in range(201)]):
        assert "error" in call("omiss_eligibility", {"callsigns": bad})
    out = json.dumps(r)
    assert "FN31" not in out and "HARTFORD" not in out  # grid and county are not returned



def test_errors_carry_as_of():
    for r in (call("omiss_member_lookup", {}), call("omiss_checkin_history", {"band": "6m"}),
              call("omiss_nets_on_air")):
        assert "error" in r and r["as_of_utc"].endswith("Z")


def test_help_and_version_exit_without_serving(capsys, monkeypatch):
    for arg, expect in (("--help", "usage: omiss-mcp"), ("-h", "usage: omiss-mcp"), ("--version", "omiss-mcp ")):
        monkeypatch.setattr("sys.argv", ["omiss-mcp", arg])
        server.main()  # returns instead of serving
        assert expect in capsys.readouterr().out
