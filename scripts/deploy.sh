#!/usr/bin/env bash
# Deploys the current git commit to the ask-ai ECS service:
#
#   1. Builds the image from the committed files (not the working tree) and
#      pushes it to ECR, tagged with the commit hash.
#   2. Registers a new revision of the task definition with that image.
#   3. Runs the migrations as a one-off task with the new revision.
#   4. Points the service at the new revision and waits for the rolling deploy.
#
# Run it from anywhere in the repo, with AWS credentials in the environment:
#
#   scripts/deploy.sh
#
# Every setting below can be overridden with an environment variable, so CI can
# run the same script. It never prompts, and running it twice for the same
# commit skips the build and deploys the same image again.
#
# One-time setup: the service must already exist. Create it with the network
# settings of your choice, and with the circuit breaker on so that a deploy
# whose tasks keep failing rolls back on its own. The registry puts the tasks
# in private DNS as api.ask-ai.internal, an address that survives deploys
# (the Cloud Map namespace and service are created separately):
#
#   aws ecs create-service --cluster frank-bee-oawvo1 --service-name ask-ai \
#     --task-definition ask-ai-family --desired-count 1 --launch-type FARGATE \
#     --network-configuration 'awsvpcConfiguration={subnets=[subnet-...],securityGroups=[sg-...],assignPublicIp=ENABLED}' \
#     --deployment-configuration 'deploymentCircuitBreaker={enable=true,rollback=true}' \
#     --service-registries 'registryArn=arn:aws:servicediscovery:...:service/srv-...'

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
ECR_REPO="${ECR_REPO:-ask-ai}"
ECS_CLUSTER="${ECS_CLUSTER:-frank-bee-oawvo1}"
ECS_SERVICE="${ECS_SERVICE:-ask-ai}"
TASK_FAMILY="${TASK_FAMILY:-ask-ai-family}"
CONTAINER_NAME="${CONTAINER_NAME:-ask-ai}"

export AWS_REGION
export AWS_PAGER=""

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

for cmd in aws docker git jq; do
    command -v "$cmd" >/dev/null || die "$cmd is not installed"
done

cd "$(git rev-parse --show-toplevel)"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "warning: uncommitted changes are not deployed, only HEAD is" >&2
fi

TAG="$(git rev-parse --short=12 HEAD)"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
IMAGE="$REGISTRY/$ECR_REPO:$TAG"

# Fail before building anything if the service isn't there to deploy to.
service_status="$(aws ecs describe-services --cluster "$ECS_CLUSTER" \
    --services "$ECS_SERVICE" --query 'services[0].status' --output text)"
[[ "$service_status" == "ACTIVE" ]] ||
    die "service $ECS_SERVICE not found in cluster $ECS_CLUSTER (see the setup note at the top of this script)"

log "Deploying $IMAGE"

# 1. Build and push.
if aws ecr describe-images --repository-name "$ECR_REPO" \
    --image-ids "imageTag=$TAG" >/dev/null 2>&1; then
    log "Image $TAG is already in ECR, skipping the build"
else
    log "Building the image"
    aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"
    # Build from a copy of HEAD so the image holds exactly the committed files.
    # (Piping `git archive` into `docker build -` would skip .dockerignore.)
    build_dir="$(mktemp -d)"
    trap 'rm -rf "$build_dir"' EXIT
    git archive --format=tar HEAD | tar -x -C "$build_dir"
    docker build --platform linux/amd64 --tag "$IMAGE" "$build_dir"
    docker push "$IMAGE"
fi

# 2. Register a new task definition revision: a copy of the latest one with
# the new image. Settings such as environment variables carry over unchanged.
log "Registering a task definition revision"
task_def="$(aws ecs describe-task-definition --task-definition "$TASK_FAMILY" \
    --query taskDefinition --output json |
    jq --arg image "$IMAGE" --arg name "$CONTAINER_NAME" '
        (.containerDefinitions[] | select(.name == $name) | .image) = $image
        | del(.taskDefinitionArn, .revision, .status, .requiresAttributes,
              .compatibilities, .registeredAt, .registeredBy)')"
TASK_DEF_ARN="$(aws ecs register-task-definition --cli-input-json "$task_def" \
    --query taskDefinition.taskDefinitionArn --output text)"
echo "$TASK_DEF_ARN"

# 3. Run the migrations, in the service's network so they can reach the
# database. The old code keeps serving meanwhile, so migrations must not break
# it: add columns in one deploy, and drop old ones in a later one.
log "Running the migrations"
network_config="$(aws ecs describe-services --cluster "$ECS_CLUSTER" \
    --services "$ECS_SERVICE" --query 'services[0].networkConfiguration' --output json)"
overrides="$(jq -n --arg name "$CONTAINER_NAME" \
    '{containerOverrides: [{name: $name, command: ["alembic", "upgrade", "head"]}]}')"
migrate_task="$(aws ecs run-task --cluster "$ECS_CLUSTER" --launch-type FARGATE \
    --task-definition "$TASK_DEF_ARN" \
    --network-configuration "$network_config" \
    --overrides "$overrides" \
    --started-by deploy-migrations \
    --query 'tasks[0].taskArn' --output text)"
echo "$migrate_task"
aws ecs wait tasks-stopped --cluster "$ECS_CLUSTER" --tasks "$migrate_task"
exit_code="$(aws ecs describe-tasks --cluster "$ECS_CLUSTER" --tasks "$migrate_task" \
    --query "tasks[0].containers[?name=='$CONTAINER_NAME'].exitCode | [0]" --output text)"
if [[ "$exit_code" != "0" ]]; then
    reason="$(aws ecs describe-tasks --cluster "$ECS_CLUSTER" --tasks "$migrate_task" \
        --query 'tasks[0].stoppedReason' --output text)"
    die "migrations failed (exit code $exit_code: $reason); the service was not updated. Logs are in CloudWatch under the task's log group."
fi

# 4. Roll out the new revision. ECS starts new tasks before stopping old ones.
log "Updating the service"
deployment_id="$(aws ecs update-service --cluster "$ECS_CLUSTER" \
    --service "$ECS_SERVICE" --task-definition "$TASK_DEF_ARN" \
    --query "service.deployments[?status=='PRIMARY'] | [0].id" --output text)"
echo "$deployment_id"

# Wait for this deployment's rollout to finish, rather than for the service to
# be stable: ECS reports COMPLETED a minute or so after the service settles, and
# the service also settles after the circuit breaker rolls a failed deploy back.
for _ in $(seq 1 80); do
    rollout_state="$(aws ecs describe-services --cluster "$ECS_CLUSTER" \
        --services "$ECS_SERVICE" \
        --query "services[0].deployments[?id=='$deployment_id'] | [0].rolloutState" \
        --output text)"
    case "$rollout_state" in
        COMPLETED) break ;;
        IN_PROGRESS) sleep 15 ;;
        # FAILED, or None once ECS has replaced the deployment after a rollback.
        *) die "the deploy failed (rollout state: $rollout_state); see the service's events" ;;
    esac
done
[[ "$rollout_state" == "COMPLETED" ]] || die "timed out waiting for the deploy"

log "Deployed $TAG"
