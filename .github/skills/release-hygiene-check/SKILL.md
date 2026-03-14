---
name: release-hygiene-check
description: Run a repeatable post-deploy hygiene check for otel-data-api. Validates issue acceptance criteria, resolves stale blocked status, and verifies downstream types PR lifecycle before marking work Done.
---

# Release Hygiene Check (otel-data-api)

Use this skill whenever a code PR and deployment PR have merged, or when
`@stuartshay/otel-data-types` was published.

## Required Outputs

- Final acceptance-validation comment on the linked issue
- Evidence links for each acceptance criterion
- Confirmation that stale "blocked" validation state is superseded
- Types downstream PR status (if package publish occurred)
- Project item moved to `Done` only after all items above are complete

## Workflow

### 1. Collect Linked Artifacts

Identify and record:

- Implementation issue (`otel-data-api`)
- Code PR (`otel-data-api`)
- Deployment PR (`k8s-gitops`)
- Types dependency PR (`otel-data-gateway`, if applicable)

Suggested commands:

```bash
gh issue view <issue_number> --repo stuartshay/otel-data-api \
  --json number,title,state,body,comments,projectItems
gh pr view <pr_number> --repo stuartshay/otel-data-api \
  --json number,title,state,mergedAt,url
gh pr view <pr_number> --repo stuartshay/k8s-gitops \
  --json number,title,state,mergedAt,url
```

### 2. Validate Deployed Behavior

Validate against the live cluster, not only local CI:

```bash
curl -s https://api.lab.informationcart.com/health
curl -s https://api.lab.informationcart.com/openapi.json | jq '.info.version'
```

Add endpoint-specific checks required by the issue acceptance criteria.

### 3. Validate Each Acceptance Criterion

Create a criterion-by-criterion mapping from issue text to evidence:

- `PASS`: criterion is satisfied in deployed environment
- `FAIL`: criterion not met; open follow-up and do not move to `Done`

If issue body checkboxes are not updated, post a final checklist comment with
all criteria statuses.

### 4. Validate Types Downstream PR (When Applicable)

If API changes published `@stuartshay/otel-data-types`:

```bash
gh pr list --repo stuartshay/otel-data-gateway --state all \
  --search "Update @stuartshay/otel-data-types in:title" --limit 5
```

Confirm:

- Bumped version matches npm publish version
- Required checks passed
- Merge status is recorded or blocker is documented

### 5. Post Final Superseding Comment

If earlier comments reported blocked validation, post a new final comment that
supersedes that state and links the resolving PR/run.

Template:

```text
Final acceptance validation (YYYY-MM-DD):
- Criterion 1: PASS — <evidence link/command output>
- Criterion 2: PASS — <evidence link/command output>
- Deployment PR: <link>
- Types PR (if applicable): <link>
- Prior blocker status: Resolved (<link>)
```

### 6. Project Board Hygiene

Move the project item to `Done` only after Step 5 is posted and all criteria
pass.

## Completion Checklist

- [ ] Acceptance criteria validated in deployed environment
- [ ] Final validation comment posted with evidence links
- [ ] Prior blocked status explicitly superseded
- [ ] Types downstream PR validated (if applicable)
- [ ] Project item status updated after evidence is posted
