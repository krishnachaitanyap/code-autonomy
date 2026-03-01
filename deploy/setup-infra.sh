#!/usr/bin/env bash
# setup-infra.sh — One-time AWS infrastructure setup for Code Autonomy on ECS Fargate.
#
# Prerequisites:
#   - AWS CLI v2 configured with appropriate credentials
#   - Environment variables: VPC_ID, PUBLIC_SUBNET_1, PUBLIC_SUBNET_2, PRIVATE_SUBNET_1, PRIVATE_SUBNET_2
#
# Usage:
#   export VPC_ID=vpc-xxx PUBLIC_SUBNET_1=subnet-xxx PUBLIC_SUBNET_2=subnet-xxx \
#          PRIVATE_SUBNET_1=subnet-xxx PRIVATE_SUBNET_2=subnet-xxx
#   ./deploy/setup-infra.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# Validate required env vars
# ---------------------------------------------------------------------------
for var in VPC_ID PUBLIC_SUBNET_1 PUBLIC_SUBNET_2 PRIVATE_SUBNET_1 PRIVATE_SUBNET_2; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: $var is not set. Export it before running this script."
        exit 1
    fi
done

REGION=$(aws configure get region || echo "us-east-1")
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
APP_NAME="code-autonomy"

echo "========================================"
echo "  Code Autonomy — Infrastructure Setup"
echo "========================================"
echo "Region:     $REGION"
echo "Account:    $ACCOUNT_ID"
echo "VPC:        $VPC_ID"
echo ""

# ---------------------------------------------------------------------------
# 1. ECR Repository
# ---------------------------------------------------------------------------
echo "--- [1/9] Creating ECR repository ---"
aws ecr describe-repositories --repository-names "$APP_NAME" 2>/dev/null || \
    aws ecr create-repository \
        --repository-name "$APP_NAME" \
        --image-scanning-configuration scanOnPush=true \
        --encryption-configuration encryptionType=AES256

ECR_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$APP_NAME"
echo "ECR: $ECR_URI"

# ---------------------------------------------------------------------------
# 2. CloudWatch Log Group
# ---------------------------------------------------------------------------
echo "--- [2/9] Creating CloudWatch log group ---"
aws logs describe-log-groups --log-group-name-prefix "/ecs/$APP_NAME" --query 'logGroups[0].logGroupName' --output text 2>/dev/null | grep -q "/ecs/$APP_NAME" || \
    aws logs create-log-group --log-group-name "/ecs/$APP_NAME"

aws logs put-retention-policy --log-group-name "/ecs/$APP_NAME" --retention-in-days 30

# ---------------------------------------------------------------------------
# 3. Security Groups
# ---------------------------------------------------------------------------
echo "--- [3/9] Creating security groups ---"

# ALB security group
ALB_SG=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${APP_NAME}-alb-sg" "Name=vpc-id,Values=$VPC_ID" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")

if [ "$ALB_SG" = "None" ] || [ -z "$ALB_SG" ]; then
    ALB_SG=$(aws ec2 create-security-group \
        --group-name "${APP_NAME}-alb-sg" \
        --description "ALB security group for $APP_NAME" \
        --vpc-id "$VPC_ID" \
        --query 'GroupId' --output text)
    aws ec2 authorize-security-group-ingress --group-id "$ALB_SG" --protocol tcp --port 80 --cidr 0.0.0.0/0
    aws ec2 authorize-security-group-ingress --group-id "$ALB_SG" --protocol tcp --port 443 --cidr 0.0.0.0/0
fi
echo "ALB SG: $ALB_SG"

# ECS security group
ECS_SG=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${APP_NAME}-ecs-sg" "Name=vpc-id,Values=$VPC_ID" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")

if [ "$ECS_SG" = "None" ] || [ -z "$ECS_SG" ]; then
    ECS_SG=$(aws ec2 create-security-group \
        --group-name "${APP_NAME}-ecs-sg" \
        --description "ECS tasks security group for $APP_NAME" \
        --vpc-id "$VPC_ID" \
        --query 'GroupId' --output text)
    aws ec2 authorize-security-group-ingress --group-id "$ECS_SG" --protocol tcp --port 8000 --source-group "$ALB_SG"
fi
echo "ECS SG: $ECS_SG"

# EFS security group
EFS_SG=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${APP_NAME}-efs-sg" "Name=vpc-id,Values=$VPC_ID" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")

if [ "$EFS_SG" = "None" ] || [ -z "$EFS_SG" ]; then
    EFS_SG=$(aws ec2 create-security-group \
        --group-name "${APP_NAME}-efs-sg" \
        --description "EFS security group for $APP_NAME" \
        --vpc-id "$VPC_ID" \
        --query 'GroupId' --output text)
    aws ec2 authorize-security-group-ingress --group-id "$EFS_SG" --protocol tcp --port 2049 --source-group "$ECS_SG"
fi
echo "EFS SG: $EFS_SG"

# ---------------------------------------------------------------------------
# 4. EFS Filesystem + Mount Targets + Access Points
# ---------------------------------------------------------------------------
echo "--- [4/9] Creating EFS filesystem ---"

EFS_ID=$(aws efs describe-file-systems \
    --query "FileSystems[?Tags[?Key=='Name'&&Value=='${APP_NAME}-efs']].FileSystemId | [0]" \
    --output text 2>/dev/null || echo "None")

if [ "$EFS_ID" = "None" ] || [ -z "$EFS_ID" ]; then
    EFS_ID=$(aws efs create-file-system \
        --encrypted \
        --throughput-mode bursting \
        --tags "Key=Name,Value=${APP_NAME}-efs" \
        --query 'FileSystemId' --output text)

    echo "Waiting for EFS to become available..."
    aws efs describe-file-systems --file-system-id "$EFS_ID" --query 'FileSystems[0].LifeCycleState' --output text
    sleep 10
fi
echo "EFS: $EFS_ID"

# Mount targets in private subnets
for SUBNET in $PRIVATE_SUBNET_1 $PRIVATE_SUBNET_2; do
    EXISTING=$(aws efs describe-mount-targets --file-system-id "$EFS_ID" \
        --query "MountTargets[?SubnetId=='$SUBNET'].MountTargetId | [0]" --output text 2>/dev/null || echo "None")
    if [ "$EXISTING" = "None" ] || [ -z "$EXISTING" ]; then
        aws efs create-mount-target \
            --file-system-id "$EFS_ID" \
            --subnet-id "$SUBNET" \
            --security-groups "$EFS_SG" || true
    fi
done

# Access point for /data (SQLite DB, caches)
DATA_AP=$(aws efs describe-access-points \
    --file-system-id "$EFS_ID" \
    --query "AccessPoints[?RootDirectory.Path=='/data'].AccessPointId | [0]" \
    --output text 2>/dev/null || echo "None")

if [ "$DATA_AP" = "None" ] || [ -z "$DATA_AP" ]; then
    DATA_AP=$(aws efs create-access-point \
        --file-system-id "$EFS_ID" \
        --root-directory "Path=/data,CreationInfo={OwnerUid=1000,OwnerGid=1000,Permissions=755}" \
        --posix-user "Uid=1000,Gid=1000" \
        --tags "Key=Name,Value=${APP_NAME}-data" \
        --query 'AccessPointId' --output text)
fi
echo "EFS Data Access Point: $DATA_AP"

# Access point for /workspace (cloned repos)
WORKSPACE_AP=$(aws efs describe-access-points \
    --file-system-id "$EFS_ID" \
    --query "AccessPoints[?RootDirectory.Path=='/workspace'].AccessPointId | [0]" \
    --output text 2>/dev/null || echo "None")

if [ "$WORKSPACE_AP" = "None" ] || [ -z "$WORKSPACE_AP" ]; then
    WORKSPACE_AP=$(aws efs create-access-point \
        --file-system-id "$EFS_ID" \
        --root-directory "Path=/workspace,CreationInfo={OwnerUid=1000,OwnerGid=1000,Permissions=755}" \
        --posix-user "Uid=1000,Gid=1000" \
        --tags "Key=Name,Value=${APP_NAME}-workspace" \
        --query 'AccessPointId' --output text)
fi
echo "EFS Workspace Access Point: $WORKSPACE_AP"

# ---------------------------------------------------------------------------
# 5. IAM Roles
# ---------------------------------------------------------------------------
echo "--- [5/9] Creating IAM roles ---"

# ECS execution role (pulls images, reads secrets, writes logs)
EXEC_ROLE_NAME="${APP_NAME}-ecs-execution"
aws iam get-role --role-name "$EXEC_ROLE_NAME" 2>/dev/null || \
    aws iam create-role \
        --role-name "$EXEC_ROLE_NAME" \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }'

aws iam attach-role-policy --role-name "$EXEC_ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy 2>/dev/null || true

# Inline policy for Secrets Manager access
aws iam put-role-policy --role-name "$EXEC_ROLE_NAME" \
    --policy-name "${APP_NAME}-secrets-access" \
    --policy-document "{
        \"Version\": \"2012-10-17\",
        \"Statement\": [{
            \"Effect\": \"Allow\",
            \"Action\": [
                \"secretsmanager:GetSecretValue\"
            ],
            \"Resource\": \"arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:${APP_NAME}/*\"
        }]
    }"

# ECS task role (EFS access, CloudWatch metrics)
TASK_ROLE_NAME="${APP_NAME}-ecs-task"
aws iam get-role --role-name "$TASK_ROLE_NAME" 2>/dev/null || \
    aws iam create-role \
        --role-name "$TASK_ROLE_NAME" \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }'

aws iam put-role-policy --role-name "$TASK_ROLE_NAME" \
    --policy-name "${APP_NAME}-task-permissions" \
    --policy-document "{
        \"Version\": \"2012-10-17\",
        \"Statement\": [
            {
                \"Effect\": \"Allow\",
                \"Action\": [
                    \"elasticfilesystem:ClientMount\",
                    \"elasticfilesystem:ClientWrite\",
                    \"elasticfilesystem:ClientRootAccess\"
                ],
                \"Resource\": \"arn:aws:elasticfilesystem:${REGION}:${ACCOUNT_ID}:file-system/${EFS_ID}\"
            },
            {
                \"Effect\": \"Allow\",
                \"Action\": [
                    \"cloudwatch:PutMetricData\"
                ],
                \"Resource\": \"*\"
            },
            {
                \"Effect\": \"Allow\",
                \"Action\": [
                    \"ssmmessages:CreateControlChannel\",
                    \"ssmmessages:CreateDataChannel\",
                    \"ssmmessages:OpenControlChannel\",
                    \"ssmmessages:OpenDataChannel\"
                ],
                \"Resource\": \"*\"
            }
        ]
    }"

echo "Execution role: $EXEC_ROLE_NAME"
echo "Task role:      $TASK_ROLE_NAME"

# ---------------------------------------------------------------------------
# 6. Secrets Manager Placeholders
# ---------------------------------------------------------------------------
echo "--- [6/9] Creating Secrets Manager placeholders ---"

for SECRET_NAME in openai-key anthropic-key github-token jira-username jira-password bitbucket-app-password api-key; do
    aws secretsmanager describe-secret --secret-id "${APP_NAME}/${SECRET_NAME}" 2>/dev/null || \
        aws secretsmanager create-secret \
            --name "${APP_NAME}/${SECRET_NAME}" \
            --description "Code Autonomy secret: $SECRET_NAME" \
            --secret-string "PLACEHOLDER_UPDATE_ME" || true
done

echo "Secrets created (update with actual values before deploying)"

# ---------------------------------------------------------------------------
# 7. ALB + Target Group
# ---------------------------------------------------------------------------
echo "--- [7/9] Creating ALB and target group ---"

# Target group
TG_ARN=$(aws elbv2 describe-target-groups \
    --names "${APP_NAME}-tg" \
    --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || echo "None")

if [ "$TG_ARN" = "None" ] || [ -z "$TG_ARN" ]; then
    TG_ARN=$(aws elbv2 create-target-group \
        --name "${APP_NAME}-tg" \
        --protocol HTTP \
        --port 8000 \
        --vpc-id "$VPC_ID" \
        --target-type ip \
        --health-check-path "/api/health" \
        --health-check-interval-seconds 30 \
        --health-check-timeout-seconds 5 \
        --healthy-threshold-count 2 \
        --unhealthy-threshold-count 3 \
        --query 'TargetGroups[0].TargetGroupArn' --output text)

    # Enable stickiness for WebSocket connections
    aws elbv2 modify-target-group-attributes \
        --target-group-arn "$TG_ARN" \
        --attributes \
            Key=stickiness.enabled,Value=true \
            Key=stickiness.type,Value=lb_cookie \
            Key=stickiness.lb_cookie.duration_seconds,Value=86400 \
            Key=deregistration_delay.timeout_seconds,Value=60
fi
echo "Target Group: $TG_ARN"

# ALB
ALB_ARN=$(aws elbv2 describe-load-balancers \
    --names "${APP_NAME}-alb" \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "None")

if [ "$ALB_ARN" = "None" ] || [ -z "$ALB_ARN" ]; then
    ALB_ARN=$(aws elbv2 create-load-balancer \
        --name "${APP_NAME}-alb" \
        --subnets "$PUBLIC_SUBNET_1" "$PUBLIC_SUBNET_2" \
        --security-groups "$ALB_SG" \
        --scheme internet-facing \
        --type application \
        --query 'LoadBalancers[0].LoadBalancerArn' --output text)

    # Set idle timeout to 3600s for long WebSocket sessions
    aws elbv2 modify-load-balancer-attributes \
        --load-balancer-arn "$ALB_ARN" \
        --attributes Key=idle_timeout.timeout_seconds,Value=3600
fi

ALB_DNS=$(aws elbv2 describe-load-balancers \
    --load-balancer-arns "$ALB_ARN" \
    --query 'LoadBalancers[0].DNSName' --output text)
echo "ALB: $ALB_DNS"

# HTTP listener
LISTENER_ARN=$(aws elbv2 describe-listeners \
    --load-balancer-arn "$ALB_ARN" \
    --query 'Listeners[?Port==`80`].ListenerArn | [0]' --output text 2>/dev/null || echo "None")

if [ "$LISTENER_ARN" = "None" ] || [ -z "$LISTENER_ARN" ]; then
    aws elbv2 create-listener \
        --load-balancer-arn "$ALB_ARN" \
        --protocol HTTP \
        --port 80 \
        --default-actions Type=forward,TargetGroupArn="$TG_ARN"
fi

# ---------------------------------------------------------------------------
# 8. ECS Cluster
# ---------------------------------------------------------------------------
echo "--- [8/9] Creating ECS cluster ---"

aws ecs describe-clusters --clusters "$APP_NAME" --query 'clusters[?status==`ACTIVE`].clusterName | [0]' --output text 2>/dev/null | grep -q "$APP_NAME" || \
    aws ecs create-cluster \
        --cluster-name "$APP_NAME" \
        --capacity-providers FARGATE FARGATE_SPOT \
        --default-capacity-provider-strategy \
            capacityProvider=FARGATE,weight=1,base=1 \
            capacityProvider=FARGATE_SPOT,weight=1

echo "ECS Cluster: $APP_NAME"

# ---------------------------------------------------------------------------
# 9. Summary
# ---------------------------------------------------------------------------
echo ""
echo "========================================"
echo "  Infrastructure Setup Complete"
echo "========================================"
echo ""
echo "Resources created:"
echo "  ECR Repository:            $ECR_URI"
echo "  ECS Cluster:               $APP_NAME"
echo "  ALB DNS:                   $ALB_DNS"
echo "  EFS Filesystem:            $EFS_ID"
echo "  EFS Data Access Point:     $DATA_AP"
echo "  EFS Workspace Access Point:$WORKSPACE_AP"
echo "  ALB Security Group:        $ALB_SG"
echo "  ECS Security Group:        $ECS_SG"
echo "  EFS Security Group:        $EFS_SG"
echo "  Target Group:              $TG_ARN"
echo ""
echo "Next steps:"
echo "  1. Update secrets with actual values:"
echo "     aws secretsmanager put-secret-value --secret-id ${APP_NAME}/openai-key --secret-string 'sk-...'"
echo "     aws secretsmanager put-secret-value --secret-id ${APP_NAME}/anthropic-key --secret-string 'sk-ant-...'"
echo "     aws secretsmanager put-secret-value --secret-id ${APP_NAME}/github-token --secret-string 'ghp_...'"
echo "     aws secretsmanager put-secret-value --secret-id ${APP_NAME}/api-key --secret-string 'your-api-key'"
echo ""
echo "  2. Update deploy/ecs-task-definition.json placeholders:"
echo "     ACCOUNT_ID  -> $ACCOUNT_ID"
echo "     REGION      -> $REGION"
echo "     EFS_FILESYSTEM_ID             -> $EFS_ID"
echo "     EFS_DATA_ACCESS_POINT_ID      -> $DATA_AP"
echo "     EFS_WORKSPACE_ACCESS_POINT_ID -> $WORKSPACE_AP"
echo ""
echo "  3. Run ./deploy/deploy.sh to build and deploy"
echo ""
echo "  4. (Optional) Add HTTPS: create ACM certificate and add port 443 listener on ALB"
echo ""
echo "  5. (Optional) Ensure NAT Gateway exists for Fargate outbound internet access"
echo "     or use public subnets with assignPublicIp=ENABLED in the service definition."
