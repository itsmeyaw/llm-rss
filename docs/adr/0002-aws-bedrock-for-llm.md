# ADR-0002: Use AWS Bedrock for LLM Inference

**Date**: 2026-06-02
**Status**: accepted
**Deciders**: itsmeyaw

## Context

The pipeline requires an LLM to score and summarize each ingested Record against the user's Interest. The Lambda is already hosted on AWS. The Anthropic API and OpenAI API are available as external alternatives.

## Decision

We use AWS Bedrock for LLM inference, accessed via LangChain's `langchain-aws` integration. The default model is Claude Haiku 4.5. The model ID is stored in SSM Parameter Store so it can be changed without redeployment.

## Alternatives Considered

### Anthropic API (direct)
- **Pros**: access to latest Claude models immediately at release
- **Cons**: requires managing an API key as a secret; data leaves AWS; separate billing
- **Why not**: Bedrock provides the same Claude models within the AWS trust boundary, with IAM-based auth instead of API key management

### OpenAI API
- **Pros**: mature ecosystem, wide model choice
- **Cons**: API key management, data egress, separate billing, no IAM integration
- **Why not**: no advantage over Bedrock given the AWS-native architecture

## Consequences

### Positive
- No API keys to manage — Lambda accesses Bedrock via IAM role, provisioned by CDK
- Data stays within AWS
- Unified billing via AWS account
- `langchain-aws` provides first-class LangChain/LangGraph integration

### Negative
- New Bedrock model releases lag behind direct Anthropic/OpenAI API availability
- Bedrock has per-region model availability constraints

### Risks
- Model availability varies by AWS region — deployment region must be verified to support the chosen Bedrock model
