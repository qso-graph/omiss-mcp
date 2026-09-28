# Changelog

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
