# ADR-0003: Use CloudFormation Instead of CDK

**Date**: 2026-06-02
**Status**: accepted
**Deciders**: itsmeyaw

## Context

The README describes the deployment tooling as "AWS CDK from the Github Action pipeline." CDK is a higher-level abstraction that synthesizes to CloudFormation. For a single-Lambda project with a small, stable infrastructure surface (one Lambda, one Layer, one EventBridge rule, one IAM role, SSM reads, SES send), the CDK abstraction layer adds dependency overhead without meaningful benefit.

## Decision

We use CloudFormation templates directly (`infra/template.yaml`). A `Makefile` handles build and deploy steps. GitHub Actions can invoke `make deploy` without requiring the CDK CLI or Node.js toolchain.

## Alternatives Considered

### AWS CDK
- **Pros**: higher-level constructs, type-safe infrastructure, programmatic loops for multi-source stacks
- **Cons**: requires Node.js + CDK CLI in CI; adds a synthesis step; for a small fixed topology the YAML is shorter and more readable than the equivalent CDK code
- **Why not**: infrastructure surface is small and stable; direct CloudFormation is simpler to audit and deploy

## Consequences

### Positive
- No Node.js dependency in CI or locally — only AWS CLI required
- Template is the authoritative artifact; no synthesis step to debug
- CloudFormation YAML is directly readable by any AWS practitioner

### Negative
- Adding a second source Lambda requires manually duplicating CloudFormation resources (no CDK `for` loops)
- No type safety on resource properties — errors surface at deploy time

### Risks
- If the infrastructure grows significantly (many sources, complex routing), migrating to CDK later will require rewriting the template as CDK code
