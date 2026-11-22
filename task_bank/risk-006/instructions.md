Ledger events lose their milliseconds when they are parsed. `parse_event_timestamp("2026-11-20T15:04:05.100Z")`
should give 15:04:05.100 UTC, but it gives 15:04:05.000100, so the event looks almost 100
milliseconds earlier than it happened.
