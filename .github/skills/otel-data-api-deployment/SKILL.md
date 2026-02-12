---
name: otel-data-api-deployment
description: Deploy and manage the otel-data-api FastAPI microservice. Covers PR merges, Docker builds, k8s-gitops manifest updates, Argo CD sync, and live deployment validation on k8s-pi5-cluster.
---

# otel-data-api Deployment Workflow

This skill manages the complete deployment lifecycle of the otel-data-api
FastAPI microservice, from code merge to production validation on
k8s-pi5-cluster.

## When to Use

Use this skill when you need to:

- Merge a PR and deploy a new version of otel-data-api
- Update Kubernetes manifests via GitOps
- Validate a live deployment (health, version, API endpoints, OpenAPI spec)
- Troubleshoot deployment failures (Docker build, Argo CD sync, pod issues)
- Roll back to a previous version

## Architecture Overview

```text
GitHub (stuartshay/otel-data-api)
  → PR merge to master
    → GitHub Actions (docker.yml)
      → Docker Hub (stuartshay/otel-data-api:<version>)
        → k8s-gitops manifest update (deployment.yaml)
          → Argo CD auto-sync / manual sync
            → k8s-pi5-cluster (namespace: otel-data-api)
              → https://api.lab.informationcart.com
```

**Key Components**:

- **API**: Python 3.12 / FastAPI / asyncpg
- **Database**: PostgreSQL via PgBouncer (192.168.1.175:6432)
- **Docker**: Multi-arch (amd64/arm64) images on Docker Hub
- **Deployment**: Kubernetes (1 replica, RollingUpdate)
- **GitOps**: k8s-gitops → Argo CD auto-sync
- **Domain**: api.lab.informationcart.com (MetalLB 192.168.1.100)

## Versioning Scheme

| Component    | Format                   | Example          |
| ------------ | ------------------------ | ---------------- |
| VERSION file | `major.minor`            | `1.0`            |
| Docker tag   | `major.minor.run_number` | `1.0.21`         |
| SHA tag      | `sha-<7char>`            | `sha-6a6f125`    |
| Branch build | `major.minor.run-branch` | `1.0.22-develop` |

The `run_number` is the GitHub Actions workflow run number, auto-incremented
per workflow. Master pushes produce `VERSION.run_number` tags.

## Repository References

| Repo                       | Purpose            | Key Path                                          |
| -------------------------- | ------------------ | ------------------------------------------------- |
| `stuartshay/otel-data-api` | API source code    | `app/`, `VERSION`, `.github/workflows/docker.yml` |
| `stuartshay/k8s-gitops`    | K8s manifests      | `apps/base/otel-data-api/deployment.yaml`         |
| Docker Hub                 | Container registry | `stuartshay/otel-data-api`                        |

## Deployment Procedure

### Step 1: Pre-Deployment Checks

Before merging any PR, verify:

```bash
# 1. Pre-commit hooks pass
cd /home/ubuntu/git/otel-data-api
pre-commit run -a

# 2. Tests pass
source venv/bin/activate
pytest tests/

# 3. Lint clean
ruff check .

# 4. Type check (optional)
mypy app/

# 5. Local server starts
make dev
curl -s http://localhost:8080/health | python3 -m json.tool
```

**Checklist**:

- [ ] Pre-commit hooks pass (`pre-commit run -a`)
- [ ] Tests pass (`pytest tests/`)
- [ ] Linter clean (`ruff check .`)
- [ ] VERSION file contains valid `major.minor` format
- [ ] No unencrypted secrets in code
- [ ] No hardcoded connection strings

### Step 2: Merge PR to Master

```bash
# Via GitHub CLI or API
# Always use squash merge to keep clean history
gh pr merge <PR_NUMBER> --squash --repo stuartshay/otel-data-api
```

**Rules**:

- Never commit directly to `master` — always use PRs
- Use squash merge to maintain clean commit history
- Branch protection requires status checks to pass

### Step 3: Wait for Docker Build

The merge triggers `.github/workflows/docker.yml` which:

1. Reads `VERSION` file (e.g., `1.0`)
2. Computes tag: `VERSION.run_number` (e.g., `1.0.21`)
3. Builds multi-arch image (linux/amd64, linux/arm64)
4. Pushes to Docker Hub with tags: `<version>`, `latest`, `sha-<commit>`
5. Dispatches `otel-data-api-release` event to k8s-gitops
6. Checks for OpenAPI schema changes and publishes npm types if changed

**Verification**:

```bash
# Check GitHub Actions (wait ~4-5 minutes after merge)
# https://github.com/stuartshay/otel-data-api/actions/workflows/docker.yml

# Find the new image tag by scanning Docker Hub
for i in $(seq 20 30); do
  result=$(docker manifest inspect stuartshay/otel-data-api:1.0.$i 2>&1 | head -1)
  if [[ "$result" == "{" ]]; then echo "FOUND: 1.0.$i"; fi
done

# Or verify using the merge commit SHA
docker manifest inspect stuartshay/otel-data-api:sha-<commit_sha_7char>

# Confirm matching digests
docker manifest inspect stuartshay/otel-data-api:<version> | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['manifests'][0]['digest'])"
```

**Known Issue**: The `publish-types` job may fail if `NPM_TOKEN` secret is not
configured or schema hasn't changed. This does NOT affect the Docker
build/push — the image is still published successfully.

### Step 4: Update k8s-gitops Manifests

```bash
cd /home/ubuntu/git/k8s-gitops

# 1. Sync develop branch
git checkout develop && git fetch origin && git pull origin develop

# 2. Rebase onto master if needed (squash merges cause divergence)
git fetch origin master
git rebase origin/master

# 3. Update deployment (option A: script)
cd apps/base/otel-data-api
./update-version.sh <NEW_VERSION>

# 3. Update deployment (option B: manual - 3 places to update)
# In deployment.yaml, update ALL THREE occurrences:
#   - metadata.labels.app.kubernetes.io/version: "<NEW_VERSION>"
#   - spec.template.spec.containers[0].image: stuartshay/otel-data-api:<NEW_VERSION>
#   - spec.template.spec.containers[0].env APP_VERSION: "<NEW_VERSION>"

# 4. Commit and push
cd /home/ubuntu/git/k8s-gitops
git add apps/base/otel-data-api/
git commit -m "chore: Update otel-data-api to v<NEW_VERSION>"
git push origin develop  # or --force-with-lease if rebased

# 5. Create PR to master
gh pr create --base master --head develop \
  --title "chore: Update otel-data-api to v<NEW_VERSION>" \
  --repo stuartshay/k8s-gitops

# 6. Wait for CI checks AND GitHub Copilot code review before merge
# CI status checks take ~60-90 seconds
# GitHub Copilot code review takes ~5+ minutes (runs automatically)
# All Copilot review comments must be resolved before merge is allowed
gh pr merge <PR_NUMBER> --squash --repo stuartshay/k8s-gitops
```

**Critical**: The deployment.yaml has THREE version references that must ALL
be updated. The `update-version.sh` script handles this atomically.

### Step 5: Argo CD Sync

After merging to k8s-gitops master:

```bash
# Option A: Wait for auto-sync (up to 3 minutes)

# Option B: Force sync via CLI
kubectl config set-context --current --namespace=argocd

# Hard refresh to detect new commit
argocd app get apps --core --hard-refresh

# If OutOfSync, trigger sync
argocd app sync apps --core --timeout 120

# If sync is stuck ("another operation in progress")
argocd app terminate-op apps --core
sleep 5
argocd app sync apps --core --force --timeout 180
```

**Verify rollout**:

```bash
kubectl rollout status deployment/otel-data-api -n otel-data-api --timeout=120s
```

### Step 6: Live Deployment Validation

Run the full validation checklist:

```bash
# 1. Health check — must show new version
curl -s https://api.lab.informationcart.com/health | python3 -m json.tool
# Expected: {"status": "healthy", "version": "<NEW_VERSION>", "timestamp": "..."}

# 2. Readiness check
curl -s https://api.lab.informationcart.com/ready | python3 -m json.tool
# Expected: {"status": "ready", ...}

# 3. Swagger UI accessible
curl -s https://api.lab.informationcart.com/docs | head -3
# Expected: <!DOCTYPE html>

# 4. API endpoint functional — locations
curl -s "https://api.lab.informationcart.com/api/v1/locations?limit=1" \
  | python3 -m json.tool | head -10

# 5. API endpoint functional — garmin activities
curl -s "https://api.lab.informationcart.com/api/v1/garmin/activities?limit=1" \
  | python3 -m json.tool | head -10

# 6. OpenAPI spec includes schema examples
curl -s https://api.lab.informationcart.com/openapi.json | python3 -c "
import sys, json
spec = json.load(sys.stdin)
schemas = spec.get('components', {}).get('schemas', {})
count = sum(1 for s in schemas.values() if 'examples' in s or 'example' in s)
print(f'Schemas with examples: {count}')
print(f'Total schemas: {len(schemas)}')
"

# 7. Kubernetes pod status
kubectl get pods -n otel-data-api -o wide
kubectl get deployment otel-data-api -n otel-data-api \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
```

## Implementation Checks

### Pre-Merge Checklist

| Check               | Command             | Expected                    |
| ------------------- | ------------------- | --------------------------- |
| Pre-commit hooks    | `pre-commit run -a` | All passed                  |
| Unit tests          | `pytest tests/`     | All passed                  |
| Linting             | `ruff check .`      | No errors                   |
| VERSION file format | `cat VERSION`       | `major.minor` (e.g., `1.0`) |
| No secrets          | `git diff --cached` | No credentials              |

### Post-Build Checklist

| Check               | Command                                                  | Expected       |
| ------------------- | -------------------------------------------------------- | -------------- |
| Docker image exists | `docker manifest inspect stuartshay/otel-data-api:<ver>` | JSON manifest  |
| Multi-arch          | Check manifest platforms                                 | amd64 + arm64  |
| SHA tag matches     | Compare digests of version and SHA tags                  | Same digest    |
| Latest tag updated  | `docker manifest inspect ...latest`                      | Updated digest |

### Post-Deploy Checklist

| Check            | Command                                          | Expected                                 |
| ---------------- | ------------------------------------------------ | ---------------------------------------- |
| Pod running      | `kubectl get pods -n otel-data-api`              | 1/1 Running                              |
| Correct image    | `kubectl get deploy ... -o jsonpath='{..image}'` | New version                              |
| Health endpoint  | `curl .../health`                                | `{"status":"healthy","version":"<ver>"}` |
| Ready endpoint   | `curl .../ready`                                 | `{"status":"ready"}`                     |
| Swagger UI       | `curl .../docs`                                  | HTML response                            |
| API functional   | `curl .../api/v1/locations?limit=1`              | JSON with items                          |
| OpenAPI examples | Check `openapi.json` schemas                     | Examples present                         |
| No restarts      | `kubectl get pods`                               | RESTARTS = 0                             |
| Argo CD synced   | `argocd app get apps --core`                     | Synced, Healthy                          |

## Rollback Procedure

If a deployment has issues:

```bash
# 1. Find last working version
cd /home/ubuntu/git/k8s-gitops
git log --oneline apps/base/otel-data-api/VERSION | head -5

# 2. Update to previous version
cd apps/base/otel-data-api
./update-version.sh <PREVIOUS_VERSION>

# 3. Commit and push directly to develop, then PR to master
cd /home/ubuntu/git/k8s-gitops
git add -A
git commit -m "revert: Rollback otel-data-api to v<PREVIOUS_VERSION>"
git push origin develop

# 4. Create and merge PR
gh pr create --base master --title "revert: Rollback otel-data-api"
# Wait for CI, then merge

# 5. Force Argo CD sync
kubectl config set-context --current --namespace=argocd
argocd app sync apps --core --force

# 6. Verify rollback
kubectl rollout status deployment/otel-data-api -n otel-data-api
curl -s https://api.lab.informationcart.com/health | python3 -m json.tool
```

## Troubleshooting

### Docker Build Fails

**Check GitHub Actions**:
`https://github.com/stuartshay/otel-data-api/actions/workflows/docker.yml`

**Common causes**:

- VERSION file missing or wrong format (must be `major.minor`)
- Docker Hub credentials expired (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`)
- Build error in Python dependencies

### Argo CD Stuck

```bash
# Check for stuck operations
argocd app get apps --core | grep -E 'Status|Operation'

# Terminate stuck operation
argocd app terminate-op apps --core

# Force sync after termination
sleep 5
argocd app sync apps --core --force --timeout 180
```

### Pod CrashLoopBackOff

```bash
# Check logs
kubectl logs -n otel-data-api -l app.kubernetes.io/name=otel-data-api --tail=50

# Check events
kubectl describe pod -n otel-data-api -l app.kubernetes.io/name=otel-data-api

# Common causes:
# - Database connection failure (PgBouncer unreachable)
# - Missing secrets (postgres-credentials not sealed)
# - Invalid environment variables in configmap
```

### ImagePullBackOff

```bash
# Verify image exists
docker manifest inspect stuartshay/otel-data-api:<version>

# Check pull secret
kubectl get secret dockerhub-registry -n otel-data-api

# Check events
kubectl describe pod -n otel-data-api -l app.kubernetes.io/name=otel-data-api
```

### k8s-gitops Branch Protection Rules

The `master` branch on `stuartshay/k8s-gitops` enforces these protections:

| Rule                             | Setting                                                                                          |
| -------------------------------- | ------------------------------------------------------------------------------------------------ |
| Required status checks           | Pre-commit Checks, Kubernetes Schema Validation, Kubernetes Best Practices, Kustomize Build Test |
| Strict status checks             | Yes (branch must be up-to-date)                                                                  |
| Required approving reviews       | 1                                                                                                |
| GitHub Copilot code review       | **Yes** — automatic review on every PR (agent runtime ~5+ minutes)                               |
| Dismiss stale reviews            | No                                                                                               |
| Require code owner review        | No                                                                                               |
| Required conversation resolution | **Yes** — all PR comments must be resolved before merge                                          |
| Enforce admins                   | Yes                                                                                              |
| Allow force pushes               | No                                                                                               |
| Allow deletions                  | No                                                                                               |

**Implications for deployments**:

- PRs must pass all 4 CI checks before merge is enabled
- At least 1 approving review is required
- **GitHub Copilot code review** runs automatically on every PR (~5+ minutes)
  — Copilot review comments must be resolved before merge
- All review comments/conversations must be marked resolved
- Even repo admins are subject to these rules (`enforce_admins: true`)
- Branch must be up-to-date with master (strict mode) — may require rebasing

To inspect current settings:

```bash
gh api repos/stuartshay/k8s-gitops/branches/master/protection \
  | python3 -m json.tool
```

### k8s-gitops PR Merge Conflict

The develop branch may diverge from master due to squash merges. Fix with:

```bash
cd /home/ubuntu/git/k8s-gitops
git checkout develop
git fetch origin master
git rebase origin/master
git push origin develop --force-with-lease
```

## Kubernetes Resources

| Resource       | Namespace     | Details                     |
| -------------- | ------------- | --------------------------- |
| Deployment     | otel-data-api | 1 replica, RollingUpdate    |
| Service        | otel-data-api | ClusterIP :8080             |
| Ingress        | otel-data-api | api.lab.informationcart.com |
| ConfigMap      | otel-data-api | otel-data-api-config        |
| SealedSecret   | otel-data-api | postgres-credentials        |
| SealedSecret   | otel-data-api | dockerhub-registry          |
| ServiceAccount | otel-data-api | otel-data-api               |

## Quick Reference Commands

```bash
# Check deployed version
kubectl get deployment otel-data-api -n otel-data-api \
  -o jsonpath='{.spec.template.spec.containers[0].image}'

# View logs
kubectl logs -n otel-data-api -l app.kubernetes.io/name=otel-data-api -f

# Restart deployment (force re-pull)
kubectl rollout restart deployment otel-data-api -n otel-data-api

# Check Argo CD sync status
kubectl config set-context --current --namespace=argocd
argocd app get apps --core | grep -E 'Sync|Health'

# Full validation one-liner
curl -s https://api.lab.informationcart.com/health | python3 -m json.tool

# Find Docker image version
docker manifest inspect stuartshay/otel-data-api:<tag> 2>&1 | head -3
```

## Version History

| Version | Date       | Changes                                         |
| ------- | ---------- | ----------------------------------------------- |
| 1.0.21  | 2026-02-12 | Swagger examples, test coverage, health UTC fix |
| 1.0.15  | 2026-02-11 | Spatial endpoint fix, OpenAPI spec regeneration |
