# Detail page improvements (2026-06-14)

## Goals
- Ticker detail: breadcrumb, larger sparkline with tooltip, pre-fill thesis note.
- Segment detail: RESOLVING hard-guard banner, See-on-map link, sortable tickers table, recent-signals count.
- Map: auto-select a node from `?node=<slug>`.
- Thesis: pre-fill from query params, inline editing of existing notes.

## New public interface: `PUT /api/v1/thesis/{thesis_id}`
- Input: same JSON body as `POST /thesis` (`segment`, optional `ticker`, optional `side`, `body_md`).
- Behavior: updates the existing row, refreshes `updated_at`, returns `ThesisRow` (200).
- Errors: 404 if id missing; 422 if validation fails.
- What it does NOT do: change `created_at`, merge partial updates (full replacement only), or support non-owner edits (no auth yet).
- Testable: PUT changes body/side and `GET /thesis` reflects it; PUT to unknown id returns 404.

## UX contract
- Ticker page `/tickers/[ticker]` links to `/thesis?ticker=<ticker>`.
- Thesis page reads `ticker` and `segment` query params and opens the editor pre-filled.
- Segment page links to `/map?node=<slug>`; map auto-selects the node once nodes load.
- Inline edit on a thesis card opens the same editor pre-filled with that note and calls PUT on save.

## Sortable tickers table
- Columns: Ticker, Name, Exposure %, Market Cap, Currency Hedge.
- Sortable by all five columns; default ticker ascending.
- Market-cap sort uses numeric `mcap_usd` when available, else bucket string.
