# TODO

## Before WC Start

- Switch `DEFAULT_EVENT_CONFIG` back to `data/events/world_cup_2026.json`.
- Add API-FOOTBALL `league_id=1`, `season=2026`, and fixture IDs once verified.
- Keep TheSportsDB as fallback metadata only if API-FOOTBALL coverage is incomplete.
- Run a live dry-run of `python -m tippnation.results_cli --dry-run --force`.
- Decide where the 5-minute result poller runs and monitor its first match day.
