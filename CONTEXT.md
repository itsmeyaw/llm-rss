# Context

Domain glossary for the LLM RSS project. Implementation details do not belong here.

## Terms

### Source
An external data provider that the pipeline ingests. Each Source is backed by a specific protocol (OAI-PMH, RSS). IACR ePrint is the first Source. Sources are abstracted behind a common interface so the rest of the pipeline is protocol-agnostic.

### Record
The canonical unit produced by a Source. A Record carries: title, abstract, subjects, published date, authors, and URL. All Sources normalize their protocol-specific format into a Record before handing off to the analysis stage.

### Interest
A free-text description of the user's areas of interest, stored in SSM Parameter Store. The LLM reads the Interest when judging the relevance of each Record.

### Relevance Score
A numeric score (1–10) assigned by the LLM to each Record, expressing how well the Record matches the Interest. Records below the configured threshold (stored in SSM) are discarded and never appear in the Digest.

### Summary
A 2–3 sentence excerpt produced by the LLM alongside the Relevance Score, in a single LLM call. Appears in the Digest to help the reader decide whether to click through to the full paper.

### Digest
The HTML email sent to the recipient after each pipeline run. Contains Records that cleared the Relevance Score threshold, sorted by score descending. Each entry shows: title (linked), authors, date, score, summary, and subjects. The subject line is dynamic and includes the Source name, paper count, and run date. If no Records clear the threshold, no email is sent — a log entry is written instead.

### Threshold
The minimum Relevance Score a Record must achieve to be included in a Digest. Stored in SSM Parameter Store alongside the Interest so it can be tuned without redeployment.

### Configuration
All runtime-tunable parameters stored in SSM Parameter Store: Interest (free-text), Threshold (1–10), recipient email address, and Bedrock model ID (default: Claude Haiku 4.5). No redeployment required to change any of these.

### Lookback Window
The fixed date range a Source queries on each run — 8 days (7-day week plus 1 day overlap). No run state is persisted. If a run fails, the next run's window covers the missed period. A paper may appear in two consecutive Digests in the overlap day; this is acceptable.

### Schedule
Each Source has one EventBridge scheduled rule that triggers its Lambda independently. The IACR source runs weekly on Monday at 07:30 UTC (08:30 CET). Cron expressions are hardcoded in CDK.
