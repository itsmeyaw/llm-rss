# ADR-0001: Use OAI-PMH for IACR Source, RSS as Fallback Protocol

**Date**: 2026-06-02
**Status**: accepted
**Deciders**: itsmeyaw

## Context

The pipeline runs on a schedule (Lambda) and needs to ingest new papers from IACR ePrint incrementally — fetching only what has been published since the last run. IACR ePrint exposes both an RSS feed and an OAI-PMH 2.0 endpoint. Future sources may only offer RSS.

## Decision

We use OAI-PMH for the IACR source. The Source abstraction supports multiple protocols; RSS is the fallback for sources that do not offer OAI-PMH.

## Alternatives Considered

### RSS for all sources
- **Pros**: uniform protocol, simpler parser, widely supported
- **Cons**: no built-in date-range filtering; requires client-side deduplication state to avoid reprocessing already-seen papers
- **Why not**: OAI-PMH's `ListRecords` with `from`/`until` parameters maps directly onto the scheduled Lambda invocation pattern, eliminating the need for seen-paper state management

## Consequences

### Positive
- Incremental ingestion is native — no deduplication state required for OAI-PMH sources
- OAI-PMH returns structured Dublin Core metadata, which maps cleanly to the canonical Record schema

### Negative
- Two protocol implementations to maintain (OAI-PMH + RSS)
- OAI-PMH is more complex to parse than RSS

### Risks
- Future sources that offer neither OAI-PMH nor RSS will require a third protocol adapter — the Source abstraction must remain open to extension
