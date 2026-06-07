# ADR-0005: Public Deep Dive Trigger via HMAC-Signed, Non-Expiring Links

**Date**: 2026-06-07
**Status**: accepted
**Deciders**: itsmeyaw

## Context

Before the Deep Dive feature, the system had **no public HTTP endpoint** — the IACR Lambda was invoked only by EventBridge. An email client can only issue an HTTP GET when a link is clicked, so requesting a Deep Dive from inside the Digest requires a public, internet-facing entry point.

That endpoint triggers expensive work: a multi-GB container Lambda, a docling parse, and a full-paper LLM call. An unauthenticated, unconstrained endpoint would let anyone burn the budget and — worse — could be coerced into fetching arbitrary URLs (SSRF) or spamming the recipient.

## Decision

Each Deep Dive Link is served by a **Lambda Function URL** (`AuthType: NONE`) on a small, fast, zip-based **trigger** Lambda — kept separate from the heavy container worker so the public surface has a sub-second cold start and a minimal attack surface. The trigger validates an **HMAC-signed token** embedded in the link, then async-invokes the worker and returns an instant HTML acknowledgement.

The token signs only `{source, paper_id}`. The trigger recomputes the HMAC with a secret held in SSM (`SecureString`, created out-of-band) and rejects any link it did not sign. The paper to parse is taken **only** from the signed token, from which the PDF URL is derived deterministically (`eprint.iacr.org/YYYY/NNN.pdf`) — so the fetch is locked to the Source domain and no caller-supplied URL is ever trusted.

Links **do not expire**. Revocation is achieved by rotating the SSM signing secret, which invalidates every previously issued link at once.

The trigger's Function URL is resolved by CloudFormation and injected into the batch handler as an environment variable, so the batch handler (which *generates* signed links) and the trigger (which *verifies* them) share one signing module.

## Alternatives Considered

### API Gateway instead of a Function URL
- **Why not**: custom domains, throttling, and WAF are unneeded for a single endpoint serving a personal digest; a Function URL is native to the existing Lambda-only stack with no extra service.

### Expiring tokens
- **Pros**: an old forwarded digest cannot be replayed forever
- **Cons**: a freshly-signed expiry must be baked into a permanent link; adds clock handling
- **Why not**: chosen against deliberately — the recipient is fixed (a Deep Dive email always goes to the configured recipient, never the clicker), so the blast radius of a leaked link is bounded to "someone could spend our budget," and secret rotation is an adequate kill-switch.

### Rate limiting / dedup state for v1
- **Why not**: signed + domain-locked links already bound abuse to people the recipient forwarded the email to. Adding a dedup or rate-limit table would introduce the first persistent state in an otherwise stateless system, for a low-stakes annoyance. Duplicates are accepted for v1.

## Consequences

### Positive
- The public endpoint is tiny and fast; the heavy image is never exposed to the internet
- Self-validating tokens need no database — the signature *is* the authorization
- SSRF is structurally prevented: the worker only ever fetches a URL derived from a signed paper ID on the known Source domain

### Negative
- A leaked or forwarded digest can trigger Deep Dives indefinitely (bounded: only signed papers, only to the fixed recipient)
- The only revocation lever is rotating the secret, which invalidates **all** outstanding links at once
- Repeated clicks produce duplicate Deep Dive emails and duplicate cost (accepted for v1)

### Risks
- If a future Source serves papers from a domain whose URL is not derivable from the signed ID, the domain-lock guarantee must be re-examined per Source
