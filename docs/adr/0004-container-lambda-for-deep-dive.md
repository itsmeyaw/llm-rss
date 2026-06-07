# ADR-0004: Container-Image Lambda for the Deep Dive Worker

**Date**: 2026-06-07
**Status**: accepted
**Deciders**: itsmeyaw

## Context

The Deep Dive feature parses a paper's full PDF with [docling](https://github.com/docling-project/docling) and analyzes it with an LLM. Docling depends on PyTorch and downloads layout / table-structure model weights. PyTorch CPU wheels alone are ~1–2 GB installed; with docling's models the deployment package is well past Lambda's **250 MB unzipped zip+layer limit**.

The rest of the system (the IACR batch handler and the new public trigger) are small and fit the existing zip + layer packaging comfortably. Only the Deep Dive worker has the heavy dependency footprint.

## Decision

The Deep Dive worker runs as a **container-image Lambda** (Lambda supports images up to 10 GB). The image bakes in docling, CPU-only torch, and the model weights **at build time** so nothing is downloaded at cold start (Lambda's filesystem is read-only outside `/tmp`). OCR is disabled in the docling pipeline (`do_ocr=False`); layout and table-structure models are kept. The worker is sized at **3008 MB memory / 900 s timeout**, and cold starts are accepted (results arrive asynchronously by email, so latency is invisible to the user).

This bifurcates the toolchain: the batch handler and trigger stay **zip + layer**; the Deep Dive worker is **Docker → ECR → image**. Both share code under `functions/iacr/` — the image simply `COPY`s the same tree.

The ECR repository lives **outside** the CloudFormation stack. An idempotent `ensure-ecr` step (`describe-repositories || create-repository`) creates it once; the image is tagged by a **content hash** of its build inputs (deep-dive sources + `requirements.txt` + `Dockerfile`); an idempotent `ensure-image` step builds+pushes only when that tag is absent; and `DeepDiveImageUri=<repo>:<hash>` is passed to the stack as a parameter.

## Alternatives Considered

### Zip + EFS-mounted models
- **Pros**: avoids a 10 GB image; keeps zip packaging
- **Cons**: requires a VPC, EFS, mount targets, and NAT — far more infrastructure than a container; slower cold reads
- **Why not**: contradicts the project's minimal-infra stance for no benefit over a container

### Fargate / AWS Batch instead of Lambda
- **Pros**: no 15-min ceiling, more memory headroom
- **Cons**: a whole new compute model and orchestration surface
- **Why not**: a single-paper docling+LLM run is comfortably under Lambda's limits; not warranted

### ECR repository inside the CloudFormation stack
- **Pros**: one stack owns everything
- **Cons**: an image must be pushed before the image-Lambda can be created, and `DependsOn` orders *resources*, not the external `docker push` — so a fresh `create-stack` fails. CloudFormation also cannot delete a non-empty ECR repo, so stack teardown breaks. The community convention is to treat the ECR repo as a one-time concern separate from the application stack.
- **Why not**: matches neither the create nor the delete path cleanly; out-of-band repo mirrors how the SES identity and signing secret are already handled here.

### `:latest` image tag
- **Why not**: CloudFormation does not detect ECR image changes during stack updates, so a constant URI would never update the function. Content-hash tags make a new image a new URI, which CFN does act on — and double as path-filtering (the image rebuilds only when its inputs change).

## Consequences

### Positive
- Docling runs on Lambda at all; models are warm-on-disk at cold start, no runtime downloads
- Content-hash tagging gives reliable CFN-detected updates *and* skips rebuilds when deep-dive code is untouched
- Out-of-band ECR avoids the non-empty-repo teardown trap and matches existing out-of-band prerequisites (SES identity, signing secret)

### Negative
- The deploy toolchain now has two packaging paths (zip and container) to maintain
- CI gains a Docker build + ECR push; the multi-GB image build is slow on the commits that do touch deep-dive inputs
- Cold starts on the worker can be tens of seconds (accepted — delivery is asynchronous)

### Risks
- A docling/torch upgrade can materially change image size and cold-start time; the content hash will force a rebuild, which is the intended signal
