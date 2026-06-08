BUCKET        ?= $(error Set BUCKET=your-s3-bucket)
STACK_NAME    ?= llm-rss-iacr
REGION        ?= eu-central-1
SES_IDENTITY  ?= $(error Set SES_IDENTITY=verified@example.com)

ECR_REPO      ?= llm-rss-deep-dive-worker
AWS_ACCOUNT_ID ?= $(shell aws sts get-caller-identity --query Account --output text)

LAMBDA_ZIP    = dist/iacr-lambda.zip
LAYER_ZIP     = dist/iacr-layer.zip
TRIGGER_ZIP   = dist/trigger-lambda.zip
LAYER_DIR     = dist/layer/python

# Content hashes of each artifact's build inputs. Embedding the hash in the S3
# key makes every code change produce a new key, so CloudFormation sees a
# changed S3Key property and actually rolls the Lambda to the new code.
# (A static key + in-place S3 overwrite leaves CFN thinking the resource is
# unchanged, silently pinning the old code — same content-addressing trick the
# worker image uses via WORKER_HASH.)
hash = $(shell find $(1) -type f | sort | xargs shasum -a 256 | shasum -a 256 | cut -c1-12)

LAMBDA_HASH   = $(call hash,functions/iacr)
LAYER_HASH    = $(call hash,requirements.txt)
TRIGGER_HASH  = $(call hash,functions/trigger functions/iacr/signing.py)

LAMBDA_ZIP_KEY  = llm-rss/iacr-lambda-$(LAMBDA_HASH).zip
LAYER_ZIP_KEY   = llm-rss/iacr-layer-$(LAYER_HASH).zip
TRIGGER_ZIP_KEY = llm-rss/trigger-lambda-$(TRIGGER_HASH).zip

ECR_REGISTRY  = $(AWS_ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com
ECR_IMAGE     = $(ECR_REGISTRY)/$(ECR_REPO)

# Content hash of all worker build inputs — changes trigger a new image build
WORKER_HASH = $(shell find functions/iacr functions/worker/Dockerfile requirements-worker.txt \
    -type f | sort | xargs shasum -a 256 | shasum -a 256 | cut -c1-12)

DEEP_DIVE_IMAGE_URI = $(ECR_IMAGE):$(WORKER_HASH)

.PHONY: build layer lambda trigger ensure-ecr ensure-image upload deploy test clean

test:
	@echo "==> Running tests"
	pytest

build: layer lambda trigger

layer:
	@echo "==> Building Lambda layer"
	rm -rf $(LAYER_DIR) $(LAYER_ZIP)
	mkdir -p $(LAYER_DIR)
	pip install -r requirements.txt --target $(LAYER_DIR) --quiet
	cd dist/layer && zip -r ../iacr-layer.zip python/ --quiet
	@echo "    $(LAYER_ZIP) ready"

lambda:
	@echo "==> Building Lambda zip"
	mkdir -p dist
	cd functions/iacr && zip -r ../../$(LAMBDA_ZIP) . --quiet
	@echo "    $(LAMBDA_ZIP) ready"

trigger:
	@echo "==> Building Trigger Lambda zip"
	mkdir -p dist
	cd functions/trigger && zip -r ../../$(TRIGGER_ZIP) . --quiet
	cd functions/iacr && zip -j ../../$(TRIGGER_ZIP) signing.py --quiet
	@echo "    $(TRIGGER_ZIP) ready"

ensure-ecr:
	@echo "==> Ensuring ECR repository $(ECR_REPO) exists (out-of-band)"
	aws ecr describe-repositories --region $(REGION) \
		--repository-names $(ECR_REPO) > /dev/null 2>&1 || \
	aws ecr create-repository --region $(REGION) \
		--repository-name $(ECR_REPO) \
		--image-scanning-configuration scanOnPush=true \
		--image-tag-mutability IMMUTABLE
	@echo "    ECR repo ready: $(ECR_REGISTRY)/$(ECR_REPO)"

ensure-image: ensure-ecr
	@echo "==> Checking for image tag $(WORKER_HASH)"
	@if aws ecr describe-images --region $(REGION) \
		--repository-name $(ECR_REPO) \
		--image-ids imageTag=$(WORKER_HASH) > /dev/null 2>&1; then \
		echo "    Image $(WORKER_HASH) already present — skipping build"; \
	else \
		set -e; \
		echo "==> Building worker image"; \
		docker build \
			--platform linux/amd64 \
			-f functions/worker/Dockerfile \
			-t $(DEEP_DIVE_IMAGE_URI) \
			.; \
		echo "==> Pushing $(DEEP_DIVE_IMAGE_URI)"; \
		aws ecr get-login-password --region $(REGION) | \
			docker login --username AWS --password-stdin $(ECR_REGISTRY); \
		docker push $(DEEP_DIVE_IMAGE_URI); \
		echo "    Image pushed: $(DEEP_DIVE_IMAGE_URI)"; \
	fi

upload: build
	@echo "==> Uploading artifacts to s3://$(BUCKET)"
	aws s3 cp $(LAMBDA_ZIP)   s3://$(BUCKET)/$(LAMBDA_ZIP_KEY)
	aws s3 cp $(LAYER_ZIP)    s3://$(BUCKET)/$(LAYER_ZIP_KEY)
	aws s3 cp $(TRIGGER_ZIP)  s3://$(BUCKET)/$(TRIGGER_ZIP_KEY)

deploy: ensure-image upload
	@echo "==> Deploying stack $(STACK_NAME)"
	aws cloudformation deploy \
		--region $(REGION) \
		--stack-name $(STACK_NAME) \
		--template-file infra/template.yaml \
		--capabilities CAPABILITY_NAMED_IAM \
		--parameter-overrides \
			DeploymentBucket=$(BUCKET) \
			LambdaZipKey=$(LAMBDA_ZIP_KEY) \
			LayerZipKey=$(LAYER_ZIP_KEY) \
			TriggerZipKey=$(TRIGGER_ZIP_KEY) \
			DeepDiveImageUri=$(DEEP_DIVE_IMAGE_URI) \
			SesVerifiedIdentity=$(SES_IDENTITY)
	@echo "==> Deploy complete"

clean:
	rm -rf dist/
