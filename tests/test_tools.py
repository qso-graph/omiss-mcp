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
    "omiss_award_recipients", "omiss_net_statistics",
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
    assert r["service_name"] == "omiss-mcp" and r["contract_version"] == "0.2"


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
    assert "error" in call("omiss_checkin_history", {"date": "2026-13"})


def test_statehood_officers_awards():
    valid(call("omiss_statehood_schedule"), "statehood_schedule")
    valid(call("omiss_officers"), "officers")
    a = valid(call("omiss_awards"), "awards")
    assert a["total"] == 3
    valid(call("omiss_award_rules"), "award_rules")
    r = valid(call("omiss_award_rules", {"award_id": "100gold"}), "award_rules")
    assert r["award_id"] == "100GOLD" and r["rules_url"].startswith("https://")
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
    assert r["nets"] and all("OMISS" in n["name"] for n in r["nets"])


def test_errors_carry_as_of():
    for r in (call("omiss_member_lookup", {}), call("omiss_checkin_history", {"band": "6m"}),
              call("omiss_nets_on_air")):
        assert "error" in r and r["as_of_utc"].endswith("Z")


def test_help_and_version_exit_without_serving(capsys, monkeypatch):
    for arg, expect in (("--help", "usage: omiss-mcp"), ("-h", "usage: omiss-mcp"), ("--version", "omiss-mcp ")):
        monkeypatch.setattr("sys.argv", ["omiss-mcp", arg])
        server.main()  # returns instead of serving
        assert expect in capsys.readouterr().out
