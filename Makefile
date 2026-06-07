BUCKET        ?= $(error Set BUCKET=your-s3-bucket)
STACK_NAME    ?= llm-rss-iacr
REGION        ?= eu-central-1
SES_IDENTITY  ?= $(error Set SES_IDENTITY=verified@example.com)

LAMBDA_ZIP    = dist/iacr-lambda.zip
LAYER_ZIP     = dist/iacr-layer.zip
LAYER_DIR     = dist/layer/python

LAMBDA_ZIP_KEY = llm-rss/iacr-lambda.zip
LAYER_ZIP_KEY  = llm-rss/iacr-layer.zip

.PHONY: build layer lambda upload deploy test clean

test:
	@echo "==> Running tests"
	pytest

build: layer lambda

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

upload: build
	@echo "==> Uploading artifacts to s3://$(BUCKET)"
	aws s3 cp $(LAMBDA_ZIP) s3://$(BUCKET)/$(LAMBDA_ZIP_KEY)
	aws s3 cp $(LAYER_ZIP)  s3://$(BUCKET)/$(LAYER_ZIP_KEY)

deploy: upload
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
			SesVerifiedIdentity=$(SES_IDENTITY)
	@echo "==> Deploy complete"

clean:
	rm -rf dist/
