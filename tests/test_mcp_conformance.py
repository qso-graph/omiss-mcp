"""Conformance with the Model Context Protocol, revision 2026-07-28.

Nothing in this project's documents required this until 2026-10-11 — not CLAUDE.md,
not .claude/rules/security.md, not MCP-SECURITY-FRAMEWORK.md. We documented how to
*publish* an MCP server in detail and never wrote down what makes one *valid*, which is
how a missing ``isError`` and missing annotations reached every server in the fleet.

So these are asserted rather than trusted.

What is particular to this server, beyond the fleet-wide fixes:

* **Not every tool reads**, and issue #37 says otherwise. ``omiss_set_callsign`` writes
  the operator's callsign — and writes it into **netlogger-mcp's** settings file, which
  the two servers share. ``TestTheOneToolThatWrites`` covers that.
* **The callsign refusal has to survive the catch-all.** ``omiss_nets_on_air`` raises
  ``ToolError`` for a missing callsign from *inside* a ``try`` whose ``except Exception``
  turns anything unforeseen into "omiss-mcp hit an unexpected problem". Without a
  ``ToolError`` passthrough the instruction is swallowed and the caller is told nothing
  useful. ``TestTheRefusalSurvivesTheCatchAll`` is the test for that, and it is the one
  test here that would have caught a real bug rather than a missing declaration.

There is no ``test_release_gate.py`` here, deliberately: this repo's gate installs the
package (``pip install -e ".[test]"``), so ``test_security.py`` may import ``omiss_mcp``
and already does. A guard forbidding that would assert a constraint which does not apply.

Test IDs: OM-C01 onward.
"""

from __future__ import annotations

import asyncio
import os

os.environ["OMISS_MCP_MOCK"] = "1"
os.environ["NETLOGGER_MCP_MOCK"] = "1"

import pytest  # noqa: E402
from fastmcp import Client  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402
from netlogger_mcp import settings as netlogger_settings  # noqa: E402

from omiss_mcp import server  # noqa: E402

ANNOTATION_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

READS_OMISS = {
    "omiss_net_schedule", "omiss_nets_on_air", "omiss_member_lookup",
    "omiss_checkin_history", "omiss_net_checkins", "omiss_eligibility",
    "omiss_statehood_schedule", "omiss_officers", "omiss_awards", "omiss_award_rules",
    "omiss_award_recipients", "omiss_net_statistics",
}
WRITES_LOCALLY = {"omiss_set_callsign"}
ANSWERS_FROM_THE_PACKAGE = {"get_version_info"}


@pytest.fixture(autouse=True)
def fresh():
    """Each test starts with no memoised source and no saved callsign.

    conftest.py already points both config dirs at a per-test directory, so the path is
    *asked for* rather than assumed — a test that wrote to the operator's real settings
    file would be a defect of its own.
    """
    server._source = None
    server._netlogger = None
    yield
    server._source = None
    server._netlogger = None


def _tools() -> dict[str, object]:
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def _wire(tool: object) -> dict[str, object]:
    """The serialised annotations, which is what a client reads."""
    annotations = getattr(tool, "annotations", None)
    assert annotations is not None, "tool declares no annotations"
    return annotations.model_dump(by_alias=True, exclude_none=True)


def call(name: str, args: dict | None = None):
    """Through a real client, because that is where isError lives."""
    async def go():
        async with Client(server.mcp) as c:
            return (await c.call_tool(name, args or {})).data
    return asyncio.run(go())


def fails(name: str, args: dict | None = None) -> str:
    with pytest.raises(ToolError) as caught:
        call(name, args)
    return str(caught.value)


class TestToolAnnotations:
    def test_every_tool_declares_all_four_hints(self) -> None:
        """OM-C01: the defaults are pessimistic, so silence is the wrong answer."""
        for name, tool in _tools().items():
            wire = _wire(tool)
            for hint in ANNOTATION_HINTS:
                assert hint in wire, f"{name} omits {hint} on the wire; got {sorted(wire)}"

    def test_the_thirteen_that_read_say_so(self) -> None:
        """OM-C02: read-only, non-destructive, idempotent — for everything but the writer."""
        tools = _tools()
        for name in READS_OMISS | ANSWERS_FROM_THE_PACKAGE:
            wire = _wire(tools[name])
            assert wire["readOnlyHint"] is True, name
            assert wire["destructiveHint"] is False, name
            assert wire["idempotentHint"] is True, name

    def test_open_world_is_read_per_tool(self) -> None:
        """OM-C03: twelve reach omiss.net or NetLogger; two do not."""
        tools = _tools()
        assert set(tools) == READS_OMISS | WRITES_LOCALLY | ANSWERS_FROM_THE_PACKAGE
        for name in READS_OMISS:
            assert _wire(tools[name])["openWorldHint"] is True, name
        for name in WRITES_LOCALLY | ANSWERS_FROM_THE_PACKAGE:
            assert _wire(tools[name])["openWorldHint"] is False, name


class TestTheOneToolThatWrites:
    """Issue #37 says "every tool in this repo is read-only". It is not true.

    ``omiss_set_callsign`` writes the operator's callsign, and writes it into
    *netlogger-mcp's* settings file — the two servers deliberately share one callsign, so
    this tool's write is visible to another package. Copying a blanket read-only block
    here would have published a plain untruth about it, and the specification lets a
    client put a confirmation prompt in front of a tool whose hints say it changes
    something, so the hint has to be right in both directions.
    """

    def test_it_does_not_claim_to_be_read_only(self) -> None:
        """OM-C10: the assertion that would have caught a copied block."""
        assert _wire(_tools()["omiss_set_callsign"])["readOnlyHint"] is False

    def test_it_is_idempotent_and_not_destructive(self) -> None:
        """OM-C11: it replaces one value the operator set themselves.

        The specification reserves ``destructive`` for updates that destroy; this
        overwrites a single setting with the caller's own new value and loses nothing
        else. The same callsign twice leaves the same state, so a client may retry.
        """
        wire = _wire(_tools()["omiss_set_callsign"])
        assert wire["destructiveHint"] is False
        assert wire["idempotentHint"] is True

    def test_it_really_does_write_and_where(self) -> None:
        """OM-C12: the control — ``readOnlyHint: False`` has to be true of it.

        Asserted against netlogger-mcp's own settings path rather than a path spelled out
        here, because the sharing is the point: if that location ever stopped being
        shared, this test should fail rather than quietly pass against a stale guess.
        """
        assert not netlogger_settings.settings_file().exists()
        call("omiss_set_callsign", {"callsign": "ki7mt"})
        assert netlogger_settings.settings_file().exists(), "it claims to write and did not"
        assert netlogger_settings.load_callsign() == "KI7MT"

    def test_a_refused_callsign_writes_nothing(self) -> None:
        """OM-C13: refusing has to mean the file is untouched, not just a no."""
        fails("omiss_set_callsign", {"callsign": "not a call"})
        assert not netlogger_settings.settings_file().exists()


class TestTheRefusalSurvivesTheCatchAll:
    """The one test here that guards behaviour rather than a declaration.

    ``omiss_nets_on_air`` raises ``ToolError`` for a missing callsign from inside a
    ``try`` whose ``except Exception`` converts anything unforeseen into "omiss-mcp hit
    an unexpected problem". A ``ToolError`` is an ``Exception``, so without an explicit
    passthrough the catch-all eats the refusal and replaces a precise instruction with a
    shrug. The caller would be told something went wrong and not what to do about it.
    """

    def test_the_refusal_is_flagged(self) -> None:
        """OM-C20: a failure, not an answer."""
        fails("omiss_nets_on_air")

    def test_the_instruction_is_not_swallowed(self) -> None:
        """OM-C21: the message is the callsign instruction, not the generic one."""
        message = fails("omiss_nets_on_air")
        assert "omiss_set_callsign" in message, (
            "the catch-all swallowed the refusal and replaced its instruction"
        )
        assert "Ask the user" in message
        assert "unexpected problem" not in message

    def test_the_generic_message_is_still_reachable(self) -> None:
        """OM-C22: the passthrough must not disarm the catch-all it sits in front of.

        A test that only proves the refusal survives would also pass if the catch-all had
        been deleted outright. This plants a fault that is genuinely unforeseen and
        asserts it still arrives as the generic message.
        """
        netlogger_settings.save_callsign("KI7MT")
        server._netlogger = None

        class Broken:
            def active_nets(self, **_kwargs):
                raise ValueError("something nobody anticipated")

        server._netlogger = Broken()
        assert "unexpected problem" in fails("omiss_nets_on_air")


class TestUpstreamFailuresAreFlagged:
    def test_an_omiss_error_reaches_the_caller_intact(self) -> None:
        """OM-C30: the message is what was written to be read, not a replacement."""
        assert "real date" in fails("omiss_checkin_history", {"date": "2026-13"})

    def test_bad_input_is_flagged_rather_than_answered(self) -> None:
        """OM-C31: a rejection is a failure, across several shapes of bad input."""
        for name, args in (
            ("omiss_member_lookup", {}),
            ("omiss_member_lookup", {"callsign": "W1OMS", "om_number": 999}),
            ("omiss_checkin_history", {"band": "6m"}),
            ("omiss_award_recipients", {"award_id": "NOPE"}),
            ("omiss_eligibility", {"callsigns": []}),
        ):
            fails(name, args)


class TestAnAnswerIsNotAnError:
    def test_normal_lookups_are_successful_calls(self) -> None:
        """OM-C40: the control."""
        for name in ("omiss_net_schedule", "omiss_officers", "omiss_awards"):
            answer = call(name)
            assert isinstance(answer, dict)

    def test_successful_answers_still_carry_as_of_utc(self) -> None:
        """OM-C41: ``as_of_utc`` was on the error payloads too, and is not lost.

        It comes from the source layer (omiss.py), not from the error branches that were
        removed, so a successful answer still says when it was true.
        """
        for name in ("omiss_net_schedule", "omiss_officers", "omiss_awards"):
            assert call(name)["as_of_utc"].endswith("Z")


class TestVersionInfoShape:
    def test_it_matches_the_shape_the_fleet_returns(self) -> None:
        """OM-C50: the convention that drifted because nobody asserted it."""
        info = call("get_version_info")
        assert info["service_name"] == "omiss-mcp"
        assert info["service_version"]
        assert info["spec_version"]


class TestRegistration:
    def test_the_fourteen_tools_a_client_sees(self) -> None:
        """OM-C60: calling a function directly is not proof a client can."""
        assert set(_tools()) == READS_OMISS | WRITES_LOCALLY | ANSWERS_FROM_THE_PACKAGE
