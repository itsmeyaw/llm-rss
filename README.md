# LLM RSS

This project is a lambda script project that mine data from a
blog or openly available archive regulary, analyze each input based on 
specified interest using LLM, summarizes the content into brief excerpt, 
and send the user an HTML email as defined.

## Architecture

This software is hosted on AWS infrastructure, mainly operates in serverless
architecture. The main programs are executed inside the AWS Lambda Function.
The pipeline are developed using langgraph and langchain.

## Deployment

Deployment is automated via GitHub Actions on every push to `main`. The workflow
authenticates to AWS using OIDC (no long-lived credentials stored in GitHub).

### Prerequisites

1. An S3 bucket to hold Lambda artifacts (in `us-east-1`)
2. An SES-verified email address (sender and recipient)
3. An AWS IAM OIDC identity provider and deployment role (see setup below)

### AWS setup (one-time)

#### 1. Add the GitHub OIDC provider

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

Skip this step if the provider already exists in your account.

#### 2. Create the deployment IAM role

Create a file `trust-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:itsmeyaw/llm-rss:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

Replace `<ACCOUNT_ID>` with your 12-digit AWS account ID, then create the role:

```bash
aws iam create-role \
  --role-name llm-rss-github-deploy \
  --assume-role-policy-document file://trust-policy.json
```

Attach the permissions the deployment workflow needs:

```bash
aws iam attach-role-policy \
  --role-name llm-rss-github-deploy \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

aws iam attach-role-policy \
  --role-name llm-rss-github-deploy \
  --policy-arn arn:aws:iam::aws:policy/AWSCloudFormationFullAccess

aws iam attach-role-policy \
  --role-name llm-rss-github-deploy \
  --policy-arn arn:aws:iam::aws:policy/AWSLambda_FullAccess

aws iam attach-role-policy \
  --role-name llm-rss-github-deploy \
  --policy-arn arn:aws:iam::aws:policy/IAMFullAccess

aws iam attach-role-policy \
  --role-name llm-rss-github-deploy \
  --policy-arn arn:aws:iam::aws:policy/AmazonEventBridgeFullAccess

aws iam attach-role-policy \
  --role-name llm-rss-github-deploy \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMFullAccess
```

#### 3. Configure GitHub repository settings

Go to **Settings → Secrets and variables → Actions** and add:

| Kind | Name | Value |
|------|------|-------|
| Variable | `AWS_ROLE_ARN` | `arn:aws:iam::<ACCOUNT_ID>:role/llm-rss-github-deploy` |
| Variable | `AWS_REGION` | `us-east-1` |
| Variable | `DEPLOY_BUCKET` | `your-s3-bucket` |
| Secret | `SES_IDENTITY` | `you@example.com` |

#### 4. Provision SSM parameters

The Lambda reads its runtime configuration from SSM. Run once in the target region:

```bash
aws ssm put-parameter --region us-east-1 \
  --name /llm-rss/iacr/interest \
  --value "zero-knowledge proofs, MPC, post-quantum cryptography" \
  --type String

aws ssm put-parameter --region us-east-1 \
  --name /llm-rss/iacr/threshold \
  --value "7" --type String

aws ssm put-parameter --region us-east-1 \
  --name /llm-rss/iacr/bedrock-model-id \
  --value "us.anthropic.claude-haiku-4-5-20251001-v1:0" --type String

aws ssm put-parameter --region us-east-1 \
  --name /llm-rss/recipient-email \
  --value "you@example.com" --type String
```

#### 5. Provision Deep Dive prerequisites (out-of-band, one-time)

These resources live outside the CloudFormation stack and must exist before the
first `make deploy`:

**a. Signing secret** — an HMAC key protecting Deep Dive links:

```bash
aws ssm put-parameter --region us-east-1 \
  --name /llm-rss/deep-dive/signing-secret \
  --value "$(openssl rand -hex 32)" \
  --type SecureString
```

**b. Deep Dive model ID** — the CloudFormation stack creates `/llm-rss/iacr/deep-dive-model-id`
with a default value of `us.anthropic.claude-sonnet-4-6`. Override after first deploy if
you want a different model:

```bash
aws ssm put-parameter --region us-east-1 \
  --name /llm-rss/iacr/deep-dive-model-id \
  --value "us.anthropic.claude-opus-4-8" \
  --type String --overwrite
```

**c. ECR repository + worker image** — run once before deploying, then re-run whenever
deep-dive sources change (the content hash handles idempotency):

```bash
make ensure-image REGION=us-east-1
```

`ensure-image` calls `ensure-ecr` automatically. It creates the ECR repository if absent,
computes a content hash of `functions/iacr/`, `functions/worker/Dockerfile`, and
`requirements-worker.txt`, and builds+pushes only when that hash tag is not already in ECR.

### Deploying

Push to `main` — the GitHub Actions workflow builds the Lambda artifacts, uploads
them to S3, and runs `cloudformation deploy` automatically.

The Lambda runs automatically every Monday at 07:30 UTC (08:30 CET). To trigger it manually:

```bash
aws lambda invoke --function-name llm-rss-iacr /dev/stdout
```

### Local deployment (without GitHub Actions)

```bash
make deploy BUCKET=your-s3-bucket SES_IDENTITY=you@example.com REGION=us-east-1
```

`make deploy` runs `ensure-image` (idempotent), builds and uploads the zip artifacts,
then calls `cloudformation deploy` passing `DeepDiveImageUri` automatically.

## Testing

```bash
pip install -r requirements-dev.txt
make test
```

`pytest` is the project's test harness. Dev tooling lives in `requirements-dev.txt`
and is **not** bundled into the deployed Lambda layer. Tests live in `tests/` at
the repo root, so they are excluded from the Lambda zip.
