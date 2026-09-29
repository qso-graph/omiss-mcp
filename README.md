<!-- mcp-name: io.github.qso-graph/omiss-mcp -->
# omiss-mcp

[![PyPI](https://img.shields.io/pypi/v/omiss-mcp?label=PyPI&color=blue)](https://pypi.org/project/omiss-mcp/)
[![MCP Registry](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fregistry.modelcontextprotocol.io%2Fv0%2Fservers%3Fsearch%3Dio.github.qso-graph%2Fomiss-mcp%26version%3Dlatest&query=%24.servers%5B0%5D.server.version&label=MCP%20Registry&color=blue)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.qso-graph/omiss-mcp&version=latest)

MCP server for [OMISS](https://www.omiss.net/), the Old Man International Sideband Society: the net schedule, OMISS nets on the air now, member lookup, past nets and who checked in, the Statehood schedule, officers, awards and net statistics, through any MCP-compatible AI assistant.

Data from omiss.net's public pages; nets on the air from NetLogger. Part of the [qso-graph](https://qso-graph.io/) project. **No login or API key needed.**

## Install

```bash
uvx omiss-mcp            # run it; nothing to install
pip install omiss-mcp    # or install it into your own environment
```

## Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `omiss_net_schedule` | Every net's band, UTC time, frequency, days, band coordinator and next run; holiday dates | — |
| `omiss_nets_on_air` | OMISS nets on the air now, from NetLogger | — |
| `omiss_member_lookup` | One member: OM number, call, name, status, grid, state, county, last check-in | callsign or om_number |
| `omiss_checkin_history` | Past nets, newest first, optionally only a member's, a band's or a date's | callsign, om_number, band, date, net_control |
| `omiss_net_checkins` | One past net: net control, relays, notes, and the check-in list | net_id |
| `omiss_statehood_schedule` | 40m net dates and their free-call states, and the next one | — |
| `omiss_officers` | Officers, band coordinators, committees, appointees, past presidents | — |
| `omiss_awards` | The awards, with the IDs the other award tools take | — |
| `omiss_award_rules` | An award's rules, or every award's summary | award_id |
| `omiss_award_recipients` | Who holds an award, newest first, or check one member | award_id, callsign, om_number |
| `omiss_net_statistics` | Nets per band, last net per band, top check-ins and net controls, last check-in by state | state, top |
| `omiss_set_callsign` | Save your callsign, for `omiss_nets_on_air` (asked once) | callsign |
| `get_version_info` | Service version + upstream spec version (fleet identity attestation) | — |

## What is OMISS?

OMISS is an amateur-radio society that runs SSB nets on HF, from 10 to 160 meters, every day of the week. Members exchange OM numbers on the nets and work toward the society's awards. Its website publishes the net schedule, the member roster, check-in history for every net, and the award rules and recipients.

## Nets Open Early

Net control often opens a net in NetLogger for check-ins well before its listed time (the 40m net has opened 35 minutes early). `omiss_net_schedule` gives the listed times; `omiss_nets_on_air` shows whether a net is open now.

## Your Callsign

Only `omiss_nets_on_air` needs it: it asks NetLogger, which is told which station is asking. On first use the assistant asks for your callsign and saves it. You're asked once. The other tools don't need it.

## Good Neighbour Policy

omiss.net is a volunteer-run club website, not an API. We read it gently:

| Measure | Detail |
|---------|--------|
| **One request at a time** | At most one request every 2 seconds, shared by every copy you run (Claude Desktop, Claude Code, a script) through a locked file in your settings folder. |
| **Response caching** | Schedule, officers, Statehood, members and award recipients 24 hours; awards and rules 7 days; history and statistics 1 hour. |
| **Stale answers over errors** | When the site is down or busy, the last answer comes back with its age rather than an error. |
| **Back-off** | A "too many requests" or "unavailable" answer stops all requests for at least a minute, longer if the site asks. |
| **Request timeout** | 20-second timeout. |
| **User-Agent header** | Every request names this project, so the site's operators can see who is asking. |
| **NetLogger** | `omiss_nets_on_air` keeps to NetLogger's call limits, shared with [netlogger-mcp](https://github.com/qso-graph/netlogger-mcp) if you run it too. |

## Security and Privacy

- **Every value is checked before it is sent**: callsigns, OM numbers, bands from a fixed list, `YYYY`, `YYYY-MM` or `YYYY-MM-DD` dates, numeric net IDs, and award IDs from the site's own list. Free text is never sent to omiss.net.
- **No postal addresses or email addresses are ever returned**, even where a page prints one.
- **Members are looked up one at a time**, by callsign or OM number. There's no search by state, county or grid, and no roster download.

## Quick Start

### Configure your MCP client

omiss-mcp works with any MCP-compatible client. Add the server config and restart. The tools appear automatically.

#### Claude Desktop

Add to `claude_desktop_config.json` (`~/Library/Application Support/Claude/` on macOS, `%APPDATA%\Claude\` on Windows):

```json
{
  "mcpServers": {
    "omiss": {
      "command": "uvx",
      "args": ["omiss-mcp"]
    }
  }
}
```

#### Claude Code

Add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "omiss": {
      "command": "uvx",
      "args": ["omiss-mcp"]
    }
  }
}
```

#### ChatGPT Desktop

```json
{
  "mcpServers": {
    "omiss": {
      "command": "uvx",
      "args": ["omiss-mcp"]
    }
  }
}
```

#### Cursor

Add to `.cursor/mcp.json` (project-level) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "omiss": {
      "command": "uvx",
      "args": ["omiss-mcp"]
    }
  }
}
```

#### VS Code / GitHub Copilot

Add to `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "omiss": {
      "command": "uvx",
      "args": ["omiss-mcp"]
    }
  }
}
```

#### Gemini CLI

Add to `~/.gemini/settings.json` (global) or `.gemini/settings.json` (project):

```json
{
  "mcpServers": {
    "omiss": {
      "command": "uvx",
      "args": ["omiss-mcp"]
    }
  }
}
```

Installed with pip instead? Use `"command": "omiss-mcp"` in any config above.

### Ask questions

> "When is the OMISS 40m net, and on what frequency?"

> "Is KI7MT an OMISS member? What's their OM number?"

> "Which OMISS nets are on the air right now?"

> "Which nets did OM 7212 check in to this year?"

> "Who checked in to last night's 80m net?"

> "What are the free-call states on the next 40m Statehood net?"

> "What does the Alphabet Soup award require, and have I earned it?"

> "Who ran the most OMISS nets as net control in the last 90 days?"

## As a Python Library

The same code works without an AI, with the same spacing and cache:

```python
from omiss_mcp.omiss import OmissSource

om = OmissSource()
me = om.member_lookup(callsign="KI7MT")["members"][0]
for net in om.checkin_history(om_number_=me["om_number"], date_="2026")["nets"]:
    print(net["time"], net["name"], net["checkin_count"])
```

Apps can name themselves, using ADIF's `PROGRAMID` and `PROGRAMVERSION`: `OmissSource(program_id="MyLogger", program_version="1.0")`.

## Testing Without Network

```bash
OMISS_MCP_MOCK=1 omiss-mcp
```

## MCP Inspector

```bash
omiss-mcp --transport streamable-http --port 8015
```

## Development

```bash
git clone https://github.com/qso-graph/omiss-mcp.git
cd omiss-mcp
uv sync --group dev
uv run pytest
```

## License

GPL-3.0-or-later
