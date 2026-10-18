# 22. UI text in English

Date: 2026-10-18

## Status

Proposed. Changes the UI language from [frontend/README.md](../../app/frontend/README.md) and the German flag messages of [ADR 0019](0019-review-flag-decisions-in-the-domain-service.md).

## Context

The web UI was German, because the pitch audience is German.
The pitch deck uses screenshots of the UI, and the code and documentation of the repository are English.
A German UI in an English deck and an English code base mixes two languages for the jury.

## Decision

- All UI text is English: labels, status texts, toasts, empty states, error recovery hints, and fixture data.
- The web backend returns English messages and recovery hints (`ServiceError`, review flag messages).
- Numbers, times, and amounts use one locale constant, `LOCALE = "en-US"` in `app/frontend/src/lib/format.ts`.
  Amounts stay in euros.
- The CSV export of the measurements uses English column names.

## Consequences

- Screenshots for the pitch show English text. Older screenshots in `docs/pitch/ui-history/` stay German.
- Run records, notes, and agent reports keep the language in which they were written.
- A German UI would need a translation layer. The demo has no such layer.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| Keep German | Mixes languages in the deck and in the repository |
| i18n library with German and English | More code and a second component layer for a one-day demo |
