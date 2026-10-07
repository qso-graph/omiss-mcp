# Changelog

## [Unreleased]

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
