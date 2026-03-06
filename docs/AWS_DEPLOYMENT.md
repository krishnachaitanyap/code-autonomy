# AWS Deployment & Scaling Architecture

## Quick Start — Single Instance

```bash
# 1. Build and push to ECR
aws ecr create-repository --repository-name code-autonomy
aws ecr get-login-password | docker login --username AWS --password-stdin <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com

docker build -t code-autonomy .
docker tag code-autonomy:latest <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/code-autonomy:latest
docker push <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/code-autonomy:latest

# 2. Run on ECS Fargate (simplest)
# See ecs-task-definition.json below
```

---

## Architecture Tiers

### Tier 1: Single Container (1-5 stories/day)

```
┌─────────────────────────────────────────────┐
│  ECS Fargate Task                           │
│  ┌───────────────────────────────────────┐  │
│  │  code-autonomy container              │  │
│  │  main.py --jira --config config.ini   │  │
│  └───────────────┬───────────────────────┘  │
│                  │                           │
│  Mounts: EFS (/data, /workspace)            │
└──────────────────┼──────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    ▼              ▼              ▼
 Secrets       CloudWatch     EventBridge
 Manager       Logs           (cron trigger)
```

**Services used:**
| Service | Purpose |
|---------|---------|
| ECS Fargate | Run container without managing servers |
| ECR | Docker image registry |
| EFS | Persistent `/data` and `/workspace` volumes |
| Secrets Manager | `GITHUB_TOKEN`, `OPENAI_API_KEY`, `JIRA_PASSWORD` |
| CloudWatch Logs | Container stdout/stderr |
| EventBridge | Cron schedule: poll JIRA every 15 min |

**Estimated cost:** ~$30-80/month (Fargate spot + EFS)

---

### Tier 2: Queue-Driven Workers (5-50 stories/day)

```
                    ┌──────────────┐
                    │  EventBridge │
                    │  (cron/JIRA  │
                    │   webhook)   │
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │   Lambda     │
                    │  (Dispatcher)│
                    │  fetch JIRA  │
                    │  stories →   │
                    │  enqueue     │
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │   SQS Queue  │
                    │  (story jobs)│
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌───────────┐┌───────────┐┌───────────┐
        │ ECS Task  ││ ECS Task  ││ ECS Task  │
        │ Worker 1  ││ Worker 2  ││ Worker N  │
        │ (Fargate) ││ (Fargate) ││ (Fargate) │
        └─────┬─────┘└─────┬─────┘└─────┬─────┘
              │            │            │
              └────────────┼────────────┘
                           ▼
              ┌─────────────────────────┐
              │  Shared Services        │
              │  ┌─────┐ ┌───────────┐  │
              │  │ EFS │ │ OpenSearch│  │
              │  └─────┘ └───────────┘  │
              │  ┌─────────┐ ┌───────┐  │
              │  │ DynamoDB│ │  S3   │  │
              │  └─────────┘ └───────┘  │
              └─────────────────────────┘
```

**Key changes from Tier 1:**

| Component | Role |
|-----------|------|
| **SQS** | Decouple story dispatch from processing. Each message = 1 JIRA story. Visibility timeout = 30 min (agent max run time). |
| **Lambda Dispatcher** | Runs every 15 min. Calls `fetch_agent_stories()`, enqueues each as an SQS message. |
| **ECS Auto Scaling** | Scale workers 0→N based on `ApproximateNumberOfMessages`. Scale to zero when idle. |
| **DynamoDB** | Replace file-based JIRA session (`src/jira/session.py`) for distributed locking + state. |
| **OpenSearch** | Shared consciousness + knowledge backend across all workers (already supported via config). |
| **S3** | Store traces, generated artifacts, PR diffs for audit. |

**Estimated cost:** ~$100-400/month (depends on concurrency)

---

### Tier 3: Full Platform (50+ stories/day, multi-team)

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway                              │
│              /submit    /status    /webhook                     │
└────────┬──────────────────┬──────────────────┬─────────────────┘
         ▼                  ▼                  ▼
   ┌───────────┐    ┌──────────────┐    ┌──────────────┐
   │  Lambda   │    │   Lambda     │    │   Lambda     │
   │ submit-job│    │ get-status   │    │ jira-webhook │
   └─────┬─────┘    └──────┬───────┘    └──────┬───────┘
         │                 │                   │
         ▼                 ▼                   ▼
   ┌──────────┐     ┌───────────┐       ┌──────────┐
   │   SQS    │     │ DynamoDB  │       │   SQS    │
   │ priority │     │ job-state │       │ priority │
   │ queues   │     │           │       │ queues   │
   └────┬─────┘     └───────────┘       └────┬─────┘
        │                                    │
        └──────────────┬─────────────────────┘
                       ▼
        ┌──────────────────────────────┐
        │     ECS Cluster (Fargate)    │
        │  ┌────────┐ ┌────────┐      │
        │  │Worker 1│ │Worker N│ ...  │
        │  └────────┘ └────────┘      │
        │                              │
        │  Step Functions orchestrator │
        │  (clone → analyze → test →  │
        │   PR → notify)              │
        └──────────────┬───────────────┘
                       │
    ┌──────────────────┼──────────────────────┐
    ▼          ▼       ▼        ▼             ▼
  ┌─────┐  ┌──────┐ ┌──────┐ ┌──────────┐ ┌─────┐
  │ EFS │  │  S3  │ │OpenSr│ │ DynamoDB │ │ SNS │
  │     │  │artic.│ │      │ │ sessions │ │notif│
  └─────┘  └──────┘ └──────┘ └──────────┘ └─────┘
```

**Additional services at this tier:**

| Service | Purpose |
|---------|---------|
| **API Gateway** | REST API for programmatic job submission (beyond JIRA) |
| **Step Functions** | Orchestrate multi-step workflow: clone → build consciousness → run agent → test → PR → notify |
| **SQS Priority Queues** | Separate queues for P1 hotfixes vs P3 tech debt |
| **SNS** | Notifications: Slack/Teams on PR creation, failure alerts |
| **S3** | Artifact store: generated code, diffs, traces, audit logs |
| **CloudWatch Dashboards** | Success rate, avg turns, LLM token spend, time-to-PR |

---

## Required Code Changes for Scaling

### 1. Externalize Session State (Critical for multi-worker)

Currently `src/jira/session.py` stores state in local JSON files. For distributed workers:

```
src/jira/session.py  →  Add DynamoDB backend

class DynamoDBSessionStore:
    """Replace file-based session with DynamoDB for distributed locking."""

    Table schema:
      PK: repo_id (str)
      SK: story_key (str)
      status: pending | in_progress | success | failed
      worker_id: str (for distributed lock)
      lock_ttl: int (epoch seconds)
      working_memory: Map
```

**Why:** Two workers must never process the same story. DynamoDB conditional writes provide distributed locking.

### 2. Add SQS Worker Entry Point

```python
# New file: worker.py
"""SQS-driven worker — pulls one story at a time from the queue."""

def poll_and_process():
    while True:
        msg = sqs.receive_message(QueueUrl=QUEUE_URL, WaitTimeSeconds=20)
        if not msg.get("Messages"):
            continue
        story = json.loads(msg["Messages"][0]["Body"])
        receipt = msg["Messages"][0]["ReceiptHandle"]
        try:
            process_single_story(story, config)
            sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=receipt)
        except Exception:
            # Message returns to queue after visibility timeout
            pass
```

**Changes needed:**
- Extract `_run_jira_mode`'s per-story logic into `process_single_story()`
- Accept story dict + config as input (instead of fetching from JIRA)
- Report results to DynamoDB instead of local session file

### 3. Externalize Caches to S3/EFS

| Current (local) | Scaled (shared) |
|-----------------|-----------------|
| `.consciousness/` (file JSON) | EFS mount or S3 + local cache |
| `.code-index/` (file JSON) | EFS mount or S3 + local cache |
| `~/.code-autonomy/knowledge/` | OpenSearch (already supported) or DynamoDB |
| `~/.code-autonomy/traces/` | S3 (write-only, cheap storage) |

**Recommended:** Use EFS for workspace + caches (simplest), OpenSearch for knowledge (already implemented).

### 4. Add Observability

```python
# Enhance src/agent/activity.py to emit CloudWatch metrics

import boto3
cw = boto3.client("cloudwatch")

def emit_metric(name, value, unit="Count"):
    cw.put_metric_data(
        Namespace="CodeAutonomy",
        MetricData=[{"MetricName": name, "Value": value, "Unit": unit}]
    )

# Key metrics:
# - StoriesProcessed (Count)
# - StorySuccessRate (Percent)
# - AvgTurnsPerStory (Count)
# - LLMTokensUsed (Count)
# - TimeToCompletion (Seconds)
# - AgentFailures (Count)
```

### 5. Config via Environment Variables

For containerized deployment, config.ini values should be overridable via env vars:

```python
# In config_loader.py — add env var fallback for each key
def get(section, key, fallback=""):
    env_key = f"CA_{section.upper()}_{key.upper()}"  # e.g., CA_AI_PROVIDER
    return os.environ.get(env_key) or parser.get(section, key, fallback=fallback)
```

This lets you inject config via ECS task definition environment without mounting files.

---

## ECS Task Definition (Tier 1)

```json
{
  "family": "code-autonomy",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "2048",
  "memory": "4096",
  "executionRoleArn": "arn:aws:iam::ACCOUNT:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::ACCOUNT:role/codeAutonomyTaskRole",
  "containerDefinitions": [
    {
      "name": "agent",
      "image": "<ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/code-autonomy:latest",
      "essential": true,
      "command": ["--jira", "--config", "/app/config.ini"],
      "secrets": [
        {"name": "GITHUB_TOKEN", "valueFrom": "arn:aws:secretsmanager:<REGION>:<ACCOUNT>:secret:code-autonomy/github-token"},
        {"name": "OPENAI_API_KEY", "valueFrom": "arn:aws:secretsmanager:<REGION>:<ACCOUNT>:secret:code-autonomy/openai-key"},
        {"name": "JIRA_USERNAME", "valueFrom": "arn:aws:secretsmanager:<REGION>:<ACCOUNT>:secret:code-autonomy/jira-creds:username::"},
        {"name": "JIRA_PASSWORD", "valueFrom": "arn:aws:secretsmanager:<REGION>:<ACCOUNT>:secret:code-autonomy/jira-creds:password::"}
      ],
      "environment": [
        {"name": "CA_AI_PROVIDER", "value": "bedrock"},
        {"name": "CA_AI_MODEL", "value": "arn:aws:bedrock:us-east-1:ACCOUNT:application-inference-profile/PROFILE"},
        {"name": "AWS_DEFAULT_REGION", "value": "us-east-1"}
      ],
      "mountPoints": [
        {"sourceVolume": "efs-data", "containerPath": "/data"},
        {"sourceVolume": "efs-workspace", "containerPath": "/app/workspace"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/code-autonomy",
          "awslogs-region": "<REGION>",
          "awslogs-stream-prefix": "agent"
        }
      }
    }
  ],
  "volumes": [
    {
      "name": "efs-data",
      "efsVolumeConfiguration": {
        "fileSystemId": "fs-XXXXXXXXX",
        "rootDirectory": "/code-autonomy/data"
      }
    },
    {
      "name": "efs-workspace",
      "efsVolumeConfiguration": {
        "fileSystemId": "fs-XXXXXXXXX",
        "rootDirectory": "/code-autonomy/workspace"
      }
    }
  ]
}
```

---

## IAM Policy for Task Role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": "arn:aws:bedrock:*:*:*"
    },
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:*:*:secret:code-autonomy/*"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::code-autonomy-artifacts/*"
    },
    {
      "Effect": "Allow",
      "Action": ["es:ESHttp*"],
      "Resource": "arn:aws:es:*:*:domain/code-autonomy/*"
    },
    {
      "Effect": "Allow",
      "Action": ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
      "Resource": "arn:aws:sqs:*:*:code-autonomy-*"
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
      "Resource": "arn:aws:dynamodb:*:*:table/code-autonomy-*"
    },
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["cloudwatch:PutMetricData"],
      "Resource": "*"
    }
  ]
}
```

---

## Deployment Checklist

- [ ] Build Docker image, push to ECR
- [ ] Create EFS file system with mount targets in your VPC subnets
- [ ] Create Secrets Manager entries for API keys
- [ ] Create ECS cluster + register task definition
- [ ] Create CloudWatch log group `/ecs/code-autonomy`
- [ ] Create EventBridge rule (cron) → ECS RunTask
- [ ] (Tier 2+) Create SQS queue + Lambda dispatcher
- [ ] (Tier 2+) Create DynamoDB table for session state
- [ ] (Tier 3) Create API Gateway + Step Functions workflow
