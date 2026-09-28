# Changelog

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
