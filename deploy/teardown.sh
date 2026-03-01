#!/usr/bin/env bash
# teardown.sh — Destroy all Code Autonomy AWS infrastructure.
#
# Usage:
#   ./deploy/teardown.sh

set -euo pipefail

REGION=$(aws configure get region || echo "us-east-1")
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
APP_NAME="code-autonomy"

echo "========================================"
echo "  Code Autonomy — Teardown"
echo "========================================"
echo ""
echo "This will PERMANENTLY DELETE all Code Autonomy AWS resources:"
echo "  - ECS service, task definitions, cluster"
echo "  - ALB, target group, listeners"
echo "  - EFS filesystem (ALL DATA WILL BE LOST)"
echo "  - Security groups"
echo "  - Secrets Manager secrets"
echo "  - IAM roles and policies"
echo "  - ECR repository and images"
echo "  - CloudWatch log group"
echo ""
read -r -p "Type 'destroy' to confirm: " CONFIRM

if [ "$CONFIRM" != "destroy" ]; then
    echo "Aborted."
    exit 0
fi

echo ""

# ---------------------------------------------------------------------------
# 1. ECS Service
# ---------------------------------------------------------------------------
echo "--- [1/10] Deleting ECS service ---"
aws ecs update-service --cluster "$APP_NAME" --service "${APP_NAME}-service" --desired-count 0 2>/dev/null || true
aws ecs delete-service --cluster "$APP_NAME" --service "${APP_NAME}-service" --force 2>/dev/null || true

# Wait for tasks to drain
echo "Waiting for tasks to stop..."
sleep 10

# ---------------------------------------------------------------------------
# 2. Task Definitions
# ---------------------------------------------------------------------------
echo "--- [2/10] Deregistering task definitions ---"
TASK_DEFS=$(aws ecs list-task-definitions \
    --family-prefix "${APP_NAME}-web" \
    --query 'taskDefinitionArns[]' --output text 2>/dev/null || echo "")

for TD in $TASK_DEFS; do
    aws ecs deregister-task-definition --task-definition "$TD" >/dev/null 2>&1 || true
done

# ---------------------------------------------------------------------------
# 3. ECS Cluster
# ---------------------------------------------------------------------------
echo "--- [3/10] Deleting ECS cluster ---"
aws ecs delete-cluster --cluster "$APP_NAME" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 4. ALB + Listeners + Target Group
# ---------------------------------------------------------------------------
echo "--- [4/10] Deleting ALB and target group ---"
ALB_ARN=$(aws elbv2 describe-load-balancers --names "${APP_NAME}-alb" \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "None")

if [ "$ALB_ARN" != "None" ] && [ -n "$ALB_ARN" ]; then
    # Delete listeners first
    LISTENERS=$(aws elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" \
        --query 'Listeners[*].ListenerArn' --output text 2>/dev/null || echo "")
    for LIS in $LISTENERS; do
        aws elbv2 delete-listener --listener-arn "$LIS" 2>/dev/null || true
    done

    aws elbv2 delete-load-balancer --load-balancer-arn "$ALB_ARN" 2>/dev/null || true
    echo "Waiting for ALB to delete..."
    sleep 15
fi

TG_ARN=$(aws elbv2 describe-target-groups --names "${APP_NAME}-tg" \
    --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || echo "None")
if [ "$TG_ARN" != "None" ] && [ -n "$TG_ARN" ]; then
    aws elbv2 delete-target-group --target-group-arn "$TG_ARN" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# 5. EFS Filesystem
# ---------------------------------------------------------------------------
echo "--- [5/10] Deleting EFS filesystem ---"
EFS_ID=$(aws efs describe-file-systems \
    --query "FileSystems[?Tags[?Key=='Name'&&Value=='${APP_NAME}-efs']].FileSystemId | [0]" \
    --output text 2>/dev/null || echo "None")

if [ "$EFS_ID" != "None" ] && [ -n "$EFS_ID" ]; then
    # Delete access points
    ACCESS_POINTS=$(aws efs describe-access-points --file-system-id "$EFS_ID" \
        --query 'AccessPoints[*].AccessPointId' --output text 2>/dev/null || echo "")
    for AP in $ACCESS_POINTS; do
        aws efs delete-access-point --access-point-id "$AP" 2>/dev/null || true
    done

    # Delete mount targets
    MOUNT_TARGETS=$(aws efs describe-mount-targets --file-system-id "$EFS_ID" \
        --query 'MountTargets[*].MountTargetId' --output text 2>/dev/null || echo "")
    for MT in $MOUNT_TARGETS; do
        aws efs delete-mount-target --mount-target-id "$MT" 2>/dev/null || true
    done

    echo "Waiting for mount targets to delete..."
    sleep 30

    aws efs delete-file-system --file-system-id "$EFS_ID" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# 6. Security Groups
# ---------------------------------------------------------------------------
echo "--- [6/10] Deleting security groups ---"
for SG_NAME in "${APP_NAME}-efs-sg" "${APP_NAME}-ecs-sg" "${APP_NAME}-alb-sg"; do
    SG_ID=$(aws ec2 describe-security-groups \
        --filters "Name=group-name,Values=$SG_NAME" \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")
    if [ "$SG_ID" != "None" ] && [ -n "$SG_ID" ]; then
        # Remove all ingress/egress rules to clear dependencies
        aws ec2 describe-security-groups --group-ids "$SG_ID" \
            --query 'SecurityGroups[0].IpPermissions' --output json 2>/dev/null | \
            aws ec2 revoke-security-group-ingress --group-id "$SG_ID" --ip-permissions file:///dev/stdin 2>/dev/null || true
        aws ec2 delete-security-group --group-id "$SG_ID" 2>/dev/null || true
    fi
done

# ---------------------------------------------------------------------------
# 7. Secrets Manager
# ---------------------------------------------------------------------------
echo "--- [7/10] Deleting secrets ---"
for SECRET_NAME in openai-key anthropic-key github-token jira-username jira-password bitbucket-http-access-token api-key; do
    aws secretsmanager delete-secret \
        --secret-id "${APP_NAME}/${SECRET_NAME}" \
        --force-delete-without-recovery 2>/dev/null || true
done

# ---------------------------------------------------------------------------
# 8. IAM Roles
# ---------------------------------------------------------------------------
echo "--- [8/10] Deleting IAM roles ---"
for ROLE_NAME in "${APP_NAME}-ecs-execution" "${APP_NAME}-ecs-task"; do
    # Detach managed policies
    POLICIES=$(aws iam list-attached-role-policies --role-name "$ROLE_NAME" \
        --query 'AttachedPolicies[*].PolicyArn' --output text 2>/dev/null || echo "")
    for POL in $POLICIES; do
        aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POL" 2>/dev/null || true
    done

    # Delete inline policies
    INLINE=$(aws iam list-role-policies --role-name "$ROLE_NAME" \
        --query 'PolicyNames[]' --output text 2>/dev/null || echo "")
    for POL in $INLINE; do
        aws iam delete-role-policy --role-name "$ROLE_NAME" --policy-name "$POL" 2>/dev/null || true
    done

    aws iam delete-role --role-name "$ROLE_NAME" 2>/dev/null || true
done

# ---------------------------------------------------------------------------
# 9. ECR Repository
# ---------------------------------------------------------------------------
echo "--- [9/10] Deleting ECR repository ---"
aws ecr delete-repository --repository-name "$APP_NAME" --force 2>/dev/null || true

# ---------------------------------------------------------------------------
# 10. CloudWatch Log Group
# ---------------------------------------------------------------------------
echo "--- [10/10] Deleting CloudWatch log group ---"
aws logs delete-log-group --log-group-name "/ecs/$APP_NAME" 2>/dev/null || true

echo ""
echo "========================================"
echo "  Teardown Complete"
echo "========================================"
echo "All Code Autonomy AWS resources have been deleted."
