# Changelog

All notable changes to `omiss-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2] — 2026-10-26

### Changed

- `--transport streamable-http` now says where it bound, and the help text says
  it too. It binds `127.0.0.1`, and FastMCP takes no host option, so it was
  never reachable from another machine or from outside a container — and nothing
  said so. The bind address is unchanged: loopback-only is deliberate for a
  server that holds credentials and has no authentication of its own.

## [0.2.1] — 2026-10-26

- A release should appear on the Releases page
- Declare Semantic Versioning, like the other 20 do
- Move every Node 20 action to its first Node 24 major
- The locked-dependency audit blocked every release
- Four upgrades arrived as 57 pull requests
- Nothing was auditing the lockfile
- Close every open security advisory in the lockfile
- A release is a workflow, not a merge

## 0.2.0 (2026-10-19)

The minor version moves because two things a caller may have relied on now behave
differently.

**Upgrading:** a tool that fails now returns `isError: true` instead of a successful result whose
payload carried an `error` key. Anything reading `result["error"]` should read the error flag.

**The one that will be noticed:** needing a callsign used to be a *successful* result carrying
`needs_callsign: true` and a `next_step`. It is now a flagged error whose message is the whole of
that instruction — it still names `omiss_set_callsign` and still says exactly what to do.

### Release gate

- **The `http://` check in `publish.yml` now tests its output rather than its exit status.**
  `grep -v` given empty input exits **0** on macOS `/usr/bin/grep` and **1** on GNU grep, so the
  old `if grep … | grep -v …; then FAIL` form reported a failure on a *clean* tree for anyone
  running the gate locally on a Mac. It passed in CI only because the runner is ubuntu.
- Noticed the way these things are: it failed during this release's own pre-release walk with
  nothing wrong in `src/`. A gate that cannot be trusted off the runner is a gate nobody runs
  before pushing.
- Falsified three ways on macOS: a clean tree passes, a planted `http://www.omiss.net/…` fails
  with the line printed, and the loopback exemption still holds.
- The same construction is in 22 other repos' `publish.yml` plus `qrz-mcp`'s two-stage variant.
  It is a false *positive* — it never lets a bad URL through — so no release has shipped wrong
  because of it.

### MCP specification 2026-07-28 (#37)

- **Tool errors are flagged `isError`.** Seven error returns in `src/` arrived on the wire as
  successful results, so a client could not tell "the tool answered" from "the tool refused". The
  specification says of `CallToolResult.isError` that otherwise "the LLM would not be able to see
  that an error occurred and self-correct" — we were relying on the model reading the word *error*
  in prose where the protocol has a flag. They now raise `ToolError`, which FastMCP flags with the
  message intact.
- The catch-all branches deliberately do **not** pass `str(e)` through. They exist for what was not
  foreseen, and an unforeseen exception's text is not known to be safe to show; the branches above
  them carry the messages that were written to be read.
- **All 14 tools declare the four annotation hints.** Omitting them is not neutral: the defaults
  advertise a tool as `destructiveHint: true`, `idempotentHint: false` and `openWorldHint: true`,
  and the specification tells a client it may keep a human in the loop for an operation like that.
- **`omiss_set_callsign` is `readOnlyHint: false`.** Issue #37 says "every tool in this repo is
  read-only" and that is not so — this one writes the operator's callsign, and writes it into
  **netlogger-mcp's settings file**, which the two servers deliberately share. It is
  `destructiveHint: false` (it replaces one value the operator set themselves) and
  `idempotentHint: true` (the same callsign twice leaves the same state), with
  `openWorldHint: false` because it writes locally and tells NetLogger nothing until the next
  lookup. The module docstring no longer claims the server is read-only either.
- `get_version_info` is `openWorldHint: false`; the twelve tools that reach omiss.net or NetLogger
  are `true`.
- **A `ToolError` passthrough in `omiss_nets_on_air`, which is a fix and not a declaration.** The
  callsign refusal is raised from inside a `try` whose `except Exception` turns anything unforeseen
  into "omiss-mcp hit an unexpected problem". A `ToolError` *is* an `Exception`, so without the
  passthrough the catch-all would swallow the refusal and replace a precise instruction with a
  shrug. Two tests hold the line from both sides: the refusal must keep its instruction, and a
  genuinely unforeseen fault must still arrive as the generic message — so the passthrough cannot
  be "fixed" by deleting the catch-all it sits in front of.
- **`tests/test_mcp_conformance.py` asserts all of it**, through a real `fastmcp.Client` where the
  claim is about the wire. Each check was falsified once — the check removed, the suite watched to
  fail — eight in all, every one caught, including the two behavioural cases above.
- The write hints are backed by behaviour rather than trust: the tool really does write, the file
  it writes is asked of `netlogger_mcp.settings` rather than spelled out here (so the sharing
  breaking would fail the test rather than quietly pass), and a **refused** callsign leaves no file.
- `as_of_utc` was on the error payloads as well as the successful ones. It is unchanged for a
  successful answer, which gets it from the source layer, and a test says so.

### TLS (#35, qso-graph-devel#73)

- **`certifi` is carried, and the fetch verifies against it.** The one `urlopen` in `omiss.py`
  passed no context, so it trusted whichever root store the running Python was built against. On
  macOS that is `/etc/ssl/cert.pem`, a deliberately *reduced* OpenSSL-compatibility file: current,
  not stale, but it omits roots the OS itself trusts, so a certificate chaining to one of them
  fails for Python while `curl` to the same URL succeeds.
- **Measured, not assumed:** `www.omiss.net` chains through Let's Encrypt's `YR2` to ISRG
  `Root YR` and verifies against Apple's file and against `certifi` alike today. So this was
  latent rather than an outage.
- **`certifi` is declared directly, and this repo is the one where that needed an argument.**
  Everywhere else in the fleet `certifi` is not transitive, so an undeclared import is an outright
  ImportError. Here it *is* transitive — `netlogger-mcp` has carried it since 0.2.0 and this server
  depends on netlogger-mcp. That makes the declaration easier to skip and no safer to skip:
  measured 2026-10-18, `netlogger-mcp==0.1.10` — a resolution the floor `>=0.1.2` permits — pulls
  no `certifi` at all. Without a direct declaration, whether this server verifies against a current
  root set depends on which version of a sibling a user happens to resolve.
- This server holds no credential — the one thing it stores is a callsign, which is public — so a
  trust failure costs an answer rather than a secret. But it would cost it invisibly: the user is
  told only that omiss.net couldn't be read, with nothing pointing at trust. Verification is never
  disabled; `ssl.CERT_NONE` would make a call "work" by accepting any certificate from anyone.
- Four static checks in `tests/test_security.py` (verification never disabled, the root set carried
  not borrowed, `certifi` declared rather than inherited, every outbound call verifying) and **one
  behavioural check** in `tests/test_source.py`. The behavioural one matters here more than
  elsewhere: every other test in that file injects a `fetch` callable, so `_urllib_fetch` — the
  only code that opens a socket — was never exercised at all. It now watches the context arrive at
  `urlopen` and asks what it will do, because a grep cannot tell a verifying context from one built
  with verification switched off. Falsified exactly that way, and it caught it.
- Six falsifications in all, every one caught, including a second fetch path added with no context
  — the shape lotw-mcp, qrz-mcp and eqsl-mcp each turned out to have.

### Lint (#36, qso-graph-devel#70)

- **`E501` is adopted.** It reported **112 lines** — the most of any repo in this sweep — and
  **not one of them was a defect**, which is the finding rather than an argument against
  enforcing it. A consistent width is worth having; it just was never the thing holding the
  quality, which is why the rules that do find defects (`F`, `I`, mypy strict) went in first.
- **No line is exempt, and that was not the expectation.** The deferral note predicted that
  publisher-field lines would need a `noqa`. In this repo none did: omiss.net's own strings — its
  `GenAwardReport.php?AwardID=` links, its `<h3>` section titles (`King of the Hill`,
  `NCS Total Nets`), its form field names (`Band`, `NCS`, `OMNum`, `Call`, …) and its table
  headers (`Net Time & Frequency`, `40m Net Date`, `Certificate Number`) — all survive a reflow
  **whole**, because the break goes at a concatenation boundary or a list comma rather than
  through the literal. There is no `# noqa: E501` anywhere in the repo, and a check confirms it.
- **Nothing moved on the wire.** Every tool's description and `inputSchema` was dumped through a
  real client before and after: byte-identical. `--help` likewise, same SHA-256. (netlogger-mcp's
  pass did change two parameter descriptions, because an `Args:` line was reflowed there; no
  `Args:` line needed reflowing here.)
- One reflow of mine produced `a or b if c else d`, which parses as `(a or b) if c else d` —
  correct, but only to a reader who knows the precedence. It is spelled out as an `if`/`else`
  instead, which is shorter as well as plainer.
- Ruff's own `I001` fired once on `test_source.py` after the previous commit's import; fixed with
  `--fix` rather than by hand.

## 0.1.10 (2026-10-11)

- **ruff and mypy run in CI** (qso-graph-devel#66), as a job the `ci-all-green` gate requires.
  Settings follow `adif-mcp`, the reference for every qso-graph Python repo, rather than a style of
  this repo's own. They run once rather than per Python version: both read the source, and neither
  answer changes with the interpreter.
- **`omiss_net_statistics` no longer raises on a page with an unclosed `<h5>`.** The window text was
  read as `re.search(...).group(1)` behind a `"<h5>" in content` guard, and that guard does not
  prove the pair matched: an opening tag with no closing one left the match `None` and the call
  raised `AttributeError` instead of the `PageChanged` these parsers exist to raise. Found by mypy.
- `_in_window` asks for both ends of a published frequency window before comparing against one. They
  are read separately, so neither being present is proof of the other.
- The table parser's two `HTMLParser` overrides name the attribute list they are handed, `_run`
  types its `*args`, and the parsers' dicts say they hold mixed values rather than being inferred
  from their first key.
- `E501` is deferred rather than adopted (qso-graph-devel#70): what it reports in these repos are
  widths, not defects, and some lines are long because they name a publisher's field exactly.
- `mcp.run` is given the literal fastmcp asks for rather than a `str` that happens to hold the
  right word.
- **`fastmcp` is bounded: `>=4.0,<5`** (qso-graph-devel#60). It was `>=3.0` with no upper bound, and
  these servers are run with `uvx`, which resolves fresh — so a `fastmcp` 5.0 would have reached
  every user automatically, before anything here had been run against it. The floor rises to 4.0
  because that is what is actually tested: every lock in the fleet held a 4.x, and nothing in CI
  has ever exercised 3.x. A claim of 3.x support that no test backs is not support.
- `fastmcp` is locked at 4.1.0, the current release, so CI runs against what a new install gets.
- **The published contact is `maintainers@qso-graph.io`** (qso-graph-devel#69). The `authors` field
  carried a personal address, and that field is what PyPI shows on the package page. Everything in
  qso-graph is open source and open to contribution, so the contact is the project's.

## 0.1.9 (2026-10-07)

- LICENSE: the full GPL-3.0 text. The file held only its opening and a link, so GitHub detected no licence.

## 0.1.8 (2026-10-06)

- PyPI: the Documentation link goes to this package's own page, https://qso-graph.io/servers/omiss-mcp/ (qso-graph/.github#15).

## 0.1.7 (2026-10-06)

- **Nets on air are matched to OMISS's own schedule** (#11). `omiss_nets_on_air` used to keep only
  nets with "OMISS" in their name, so an OMISS net logged under another name was missed. A net now
  counts when its frequency is inside a scheduled net's window, on a day that net runs, from an hour
  before to two hours after its start; or when its name says OMISS. Each net says how it matched
  (`matched_by`) and which scheduled net it is (`omiss_net`). If the schedule can't be read, it
  falls back to the name, with a note.
- **New tool `omiss_eligibility`** (#12). Give it a net's check-ins (from `netlogger_checkins` or
  `omiss_net_checkins`) and it says, per callsign, whether they are an OMISS member, their OM number
  and state, whether they are a silent key, and their entries on OMISS's military, first responder
  and state capital rosters, all from omiss.net's public rosters (read once a day). Up to 200
  callsigns per call. Grid and county are on the roster but not returned.
- `omiss_statehood_schedule` says why `next` is empty: omiss.net's published schedule has ended.
- Contract version 0.3.

- CI: the release flow (qso-graph/.github TEMPLATES.md). Work lands on `develop`; a release is a
  PR from `develop` into `main`, and merging it publishes to PyPI and the MCP Registry, verifies both
  and tags the release. CI runs on `develop` too, and PRs into `main` must come from `develop` or a
  `security/` branch.

## 0.1.6 (2026-10-06)

- **Hyphenated award IDs were cut short** (#17). omiss.net has eight: `WAS-KN4OM`, `MIL-1ST-RESP`,
  `PATRIOT-TOPOP`, `Patriot-NCSQTR`, and the retired `SLEEPY-RET`, `NCSMON-RET`, `NEALISMEMORIAL-RET` and
  `Y2K-RET`. They were read up to the hyphen, so `WAS-KN4OM` (Worked the Club Call KN4OM in all States)
  became `WAS` and collided with the basic WAS award. The award list now returns all 148 (it returned 140).
- **The award list never drops an award silently.** A repeated link to the same award is still skipped;
  an ID naming two different awards is now an error rather than a lost award (Watson).
- Schema: `frequency_window` (and `window_low_mhz`/`window_high_mhz`) described as what it is: the
  net's legal operating range for its sideband, not a range it moves around in (Watson and Patton,
  checked across four bands).

## 0.1.5 (2026-09-29)

From Patton's full acceptance run of 0.1.4:

- **`last_checkin` was 4 hours early.** omiss.net's member roster prints US Eastern time, not UTC
  (checked on two members against the UTC check-in history). It's now converted to UTC, EDT or
  EST as the date requires. Windows installs `tzdata` for the zone data.
- **`omiss_net_checkins` split the member cell.** The archive joins NetLogger's member ID and
  remarks ("#11055# 1 CALL"); `member_id` is now the ID and the rest is `remarks`, as NetLogger
  returns them.
- **Vacant officer rows keep their year** (OM of the Year 1996 was a vacancy with no year).
- **A date that's the right shape but not a real date** ("2026-13") now says so, rather than
  repeating the format.
- **`rules_url`** points at the award's own entry on the rules page.

## 0.1.4 (2026-09-29)

- `--help` and `--version` print and exit (the server used to start and wait for a client, which
  looked like a hang).

## 0.1.3 (2026-09-29)

From Patton's run on a live net:

- `omiss_net_schedule` says that `next_utc` is the listed start: nets often open early for
  check-ins, and a net on the air shows its next run, so `omiss_nets_on_air` is the check for
  "is it on now". README section "Nets Open Early".

## 0.1.2 (2026-09-29)

From Patton's cold test of 0.1.1:

- Requires netlogger-mcp 0.1.2, which shares answers between copies as well as the call budget.
  When netlogger-mcp has just fetched the active nets, `omiss_nets_on_air` gets that answer
  instead of a "try again" error.
- `as_of_utc` on error responses too.
- Winter-schedule nets carry `season: "winter"`, so `weekdays_utc` isn't read as year-round.

## 0.1.1 (2026-09-28)

From Patton's cold-seat test (#4, #5):

- Every response has `as_of_utc`, the time of the answer, so "on the air now" and "today" can be
  checked against the schedule.
- `omiss_net_schedule` gives each net `weekdays_utc`, `seasonal_utc` (e.g. Wednesdays in April-June)
  and `next_utc`, the next time it runs. Nets citing footnote 1 also run on the page's holiday
  dates, at their holiday time. Winter-schedule nets (footnotes 2 and 3) get `next_utc_note`
  instead of a guess, because the page says when the winter schedule runs but not what it changes.
- `window_low_mhz` / `window_high_mhz` beside `frequency_window`, which mixes ranges and
  "+/- 7 kHz".
- omiss.net's own text (`days`, `frequency_window`, footnotes) is unchanged.
- Records contract 0.2.

## 0.1.0 (2026-09-28)

- Tools for OMISS's public pages: the net schedule and holidays, member lookup, check-in history,
  one past net's check-ins, the Statehood schedule, officers, awards, award rules, award recipients
  and net statistics; OMISS nets on the air from NetLogger; plus `get_version_info`.
- Records follow `schema/contract.schema.json` (0.1); check-in fields share netlogger-mcp's names.
- omiss.net is read one request at a time, at most one every 2 seconds, shared by every copy for
  the user account (a locked state file). Answers cached; a stale answer stands in when the site is
  down; a 429 or 503 stops all requests for the back-off.
- Every value is checked before it is sent; award IDs must come from the site's list. No free text
  ever reaches omiss.net.
- Postal addresses and email addresses are never returned. Members are looked up one at a time.
- A page whose layout has changed is reported as changed, not guessed at.
- `OmissSource` usable as a plain Python library.
