#!/usr/bin/env bash
# deploy.sh — Build, push, and deploy Code Autonomy to ECS Fargate.
#
# Usage:
#   ./deploy/deploy.sh [TAG]
#
# TAG defaults to git short hash. Always also tags as 'latest'.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

REGION=$(aws configure get region || echo "us-east-1")
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
APP_NAME="code-autonomy"
ECR_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$APP_NAME"
TAG="${1:-$(git -C "$PROJECT_ROOT" rev-parse --short HEAD)}"
CLUSTER="$APP_NAME"
SERVICE="${APP_NAME}-service"
TASK_FAMILY="${APP_NAME}-web"

echo "========================================"
echo "  Code Autonomy — Deploy"
echo "========================================"
echo "Region:   $REGION"
echo "Account:  $ACCOUNT_ID"
echo "Tag:      $TAG"
echo ""

# ---------------------------------------------------------------------------
# 1. ECR Docker login
# ---------------------------------------------------------------------------
echo "--- [1/5] Logging in to ECR ---"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

# ---------------------------------------------------------------------------
# 2. Build Docker image
# ---------------------------------------------------------------------------
echo "--- [2/5] Building Docker image ---"
docker build -t "$APP_NAME:$TAG" "$PROJECT_ROOT"

# ---------------------------------------------------------------------------
# 3. Tag and push to ECR
# ---------------------------------------------------------------------------
echo "--- [3/5] Pushing to ECR ---"
docker tag "$APP_NAME:$TAG" "$ECR_URI:$TAG"
docker tag "$APP_NAME:$TAG" "$ECR_URI:latest"
docker push "$ECR_URI:$TAG"
docker push "$ECR_URI:latest"

# ---------------------------------------------------------------------------
# 4. Register new task definition
# ---------------------------------------------------------------------------
echo "--- [4/5] Registering task definition ---"
TASK_DEF=$(sed \
    -e "s/ACCOUNT_ID/$ACCOUNT_ID/g" \
    -e "s/REGION/$REGION/g" \
    "$SCRIPT_DIR/ecs-task-definition.json")

# Update image tag to specific version
TASK_DEF=$(echo "$TASK_DEF" | sed "s|$ECR_URI:latest|$ECR_URI:$TAG|g")

TASK_DEF_ARN=$(echo "$TASK_DEF" | aws ecs register-task-definition \
    --cli-input-json file:///dev/stdin \
    --query 'taskDefinition.taskDefinitionArn' --output text)

echo "Task definition: $TASK_DEF_ARN"

# ---------------------------------------------------------------------------
# 5. Create or update ECS service
# ---------------------------------------------------------------------------
echo "--- [5/5] Updating ECS service ---"

# Get required infrastructure info
TG_ARN=$(aws elbv2 describe-target-groups \
    --names "${APP_NAME}-tg" \
    --query 'TargetGroups[0].TargetGroupArn' --output text)

ECS_SG=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${APP_NAME}-ecs-sg" \
    --query 'SecurityGroups[0].GroupId' --output text)

# Get private subnets from EFS mount targets (they share the same subnets)
EFS_ID=$(aws efs describe-file-systems \
    --query "FileSystems[?Tags[?Key=='Name'&&Value=='${APP_NAME}-efs']].FileSystemId | [0]" \
    --output text)

SUBNETS=$(aws efs describe-mount-targets --file-system-id "$EFS_ID" \
    --query 'MountTargets[*].SubnetId' --output text | tr '\t' ',')

SERVICE_EXISTS=$(aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
    --query 'services[?status==`ACTIVE`].serviceName | [0]' --output text 2>/dev/null || echo "None")

if [ "$SERVICE_EXISTS" = "None" ] || [ -z "$SERVICE_EXISTS" ]; then
    echo "Creating new ECS service..."
    aws ecs create-service \
        --cluster "$CLUSTER" \
        --service-name "$SERVICE" \
        --task-definition "$TASK_DEF_ARN" \
        --desired-count 1 \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$ECS_SG],assignPublicIp=DISABLED}" \
        --load-balancers "targetGroupArn=$TG_ARN,containerName=${APP_NAME}-web,containerPort=8000" \
        --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true},maximumPercent=200,minimumHealthyPercent=100" \
        --enable-execute-command
else
    echo "Updating existing ECS service..."
    aws ecs update-service \
        --cluster "$CLUSTER" \
        --service "$SERVICE" \
        --task-definition "$TASK_DEF_ARN" \
        --force-new-deployment
fi

echo ""
echo "========================================"
echo "  Deployment Complete"
echo "========================================"
echo ""
echo "Image:   $ECR_URI:$TAG"
echo "Task:    $TASK_DEF_ARN"
echo "Service: $SERVICE"
echo ""
echo "Monitor deployment:"
echo "  aws ecs describe-services --cluster $CLUSTER --services $SERVICE --query 'services[0].{status:status,running:runningCount,desired:desiredCount,deployments:deployments[*].{status:status,running:runningCount,desired:desiredCount}}'"
echo ""
echo "Tail logs:"
echo "  aws logs tail /ecs/$APP_NAME --follow"
echo ""
echo "ALB DNS:"
ALB_DNS=$(aws elbv2 describe-load-balancers --names "${APP_NAME}-alb" --query 'LoadBalancers[0].DNSName' --output text 2>/dev/null || echo "(not found)")
echo "  http://$ALB_DNS"
