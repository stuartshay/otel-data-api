---
name: pr-conflict-check
description: Check for and resolve merge conflicts before creating a pull request. Use this skill whenever creating a PR to ensure the branch is rebased onto the latest base branch, conflicts are resolved, tests pass, and the PR is created cleanly.
---

# PR Conflict Check Workflow

This skill ensures that every pull request is created with a clean, conflict-free
branch. It must be invoked **before** creating any PR to prevent merge conflicts
from blocking review and merge.

## When to Use This Skill

- **Before creating any PR** — always check for conflicts first
- **After squash merges** — develop diverges from master after squash merges,
  making rebase essential
- **When a PR shows conflicts** — to resolve and update an existing PR branch
- **Before requesting review** — ensure the branch is up-to-date

## Why This Matters

Squash merges cause the development branch to diverge from the base branch
because the individual commits on develop no longer match the single squashed
commit on master. Without rebasing, every subsequent PR will show conflicts even
if the content is identical.

## Conflict Check Procedure

### Step 1: Fetch Latest Base Branch

Always fetch the latest state of the base branch before checking for conflicts.

```bash
# Determine the base branch (usually master or main)
git fetch origin master
```

### Step 2: Attempt Rebase

Rebase the working branch onto the latest base branch to detect and resolve
conflicts.

```bash
# Rebase current branch onto the base branch
git rebase origin/master
```

### Step 3: Handle Conflicts

If the rebase encounters conflicts:

1. **List conflicted files:**

   ```bash
   git diff --name-only --diff-filter=U
   ```

2. **Inspect each conflict** — read the conflicted files to understand what
   changed on each side.

3. **Resolve conflicts** — choose the appropriate resolution:
   - If the content already exists on master (common after squash merge), accept
     the master version:

     ```bash
     git checkout --ours <file>
     ```

   - If the develop branch has new content, accept develop's version:

     ```bash
     git checkout --theirs <file>
     ```

   - For mixed conflicts, manually edit the file to combine both changes.

4. **Stage resolved files and continue:**

   ```bash
   git add <resolved-files>
   git rebase --continue
   ```

5. **Repeat** for each commit that has conflicts during the rebase.

### Step 4: Verify After Rebase

After the rebase completes successfully:

1. **Check the commit log** to ensure expected commits remain:

   ```bash
   git log --oneline origin/master..HEAD
   ```

2. **Run tests** to validate nothing is broken:

   ```bash
   source venv/bin/activate
   make test
   ```

3. **Run pre-commit hooks**:

   ```bash
   pre-commit run -a
   ```

### Step 5: Force-Push the Rebased Branch

After rebase, the branch history has changed and requires a force push:

```bash
git push origin <branch> --force-with-lease
```

> **Use `--force-with-lease`** instead of `--force` to prevent overwriting
> changes pushed by others.

### Step 6: Verify PR State

If updating an existing PR, verify it is now conflict-free:

- Check the PR's `mergeable_state` via the GitHub API — it should NOT be
  `dirty`
- Confirm the PR diff looks correct

### Step 7: Create or Update the PR

Only after all checks pass, proceed to create the PR or confirm the existing PR
is ready for review.

## Quick Reference

```bash
# Full conflict-check workflow (one-liner for simple cases)
git fetch origin master && git rebase origin/master

# If conflicts occur during rebase
git diff --name-only --diff-filter=U   # List conflicted files
git checkout --ours <file>             # Accept base branch version
git checkout --theirs <file>           # Accept feature branch version
git add <file> && git rebase --continue

# After successful rebase
git log --oneline origin/master..HEAD  # Verify commits
make test                              # Run tests
pre-commit run -a                      # Run linters
git push origin <branch> --force-with-lease
```

## Common Scenarios

### Post-Squash-Merge Divergence

After a PR is squash-merged to master, the develop branch retains the original
individual commits. These will conflict with the squashed commit on master even
though the content is identical.

**Resolution:** Rebase develop onto master. Git will detect that most commits
are "already upstream" and drop them automatically. For any remaining conflicts,
accept master's version (`--ours` during rebase) since the content is already
there.

### Multiple Conflicting Files

When many files conflict (e.g., after a long period without rebasing):

1. Check if all conflicts are from squash-merge divergence
2. If yes, batch-resolve with `git checkout --ours` for all conflicted files
3. If mixed, resolve each file individually by inspecting the diff

### Rebase Abort

If the rebase becomes too complex or produces unexpected results:

```bash
git rebase --abort
```

This safely returns the branch to its pre-rebase state.

## Resolving PR Review Comments

When addressing PR review comments, **always reply to each comment** on the PR
thread — do not silently fix issues without responding.

### For Actionable Comments (Real Issues)

1. Fix the issue in code
2. Commit and push the fix
3. Reply to the comment explaining what was changed and referencing the commit:

   > Fixed in commit `abc1234` — [brief description of the fix].

### For False Positives

When a review comment is incorrect or does not apply, **always reply explaining
why it is a false positive**. Never ignore or silently dismiss review comments.

1. Reply to the comment with a clear, technical explanation of why the flagged
   code is correct
2. Reference documentation, framework APIs, or language specifications to
   support the explanation
3. If a clarifying code comment was added, mention the commit

Example reply format:

> False positive — `[API/pattern]` is the [correct/only/standard] way to
> [achieve X] in [framework/version]. [Brief technical justification].
>
> Added a clarifying comment in commit `abc1234`.

### Comment Resolution Checklist

- [ ] Every review comment has a reply (no silent fixes or dismissals)
- [ ] Actionable fixes reference the commit SHA
- [ ] False positives include a technical explanation
- [ ] Code comments added where the logic is non-obvious

## Checklist

Before creating any PR, verify:

- [ ] `git fetch origin master` completed
- [ ] `git rebase origin/master` completed without conflicts (or
      conflicts resolved)
- [ ] Commit history looks correct (`git log --oneline origin/master..HEAD`)
- [ ] Tests pass (`make test`)
- [ ] Pre-commit hooks pass (`pre-commit run -a`)
- [ ] Branch force-pushed (if rebased)
- [ ] PR shows no conflicts on GitHub

## Adapter Notes

This skill applies to **all repositories** in the workspace. Adjust the test
and lint commands based on the project:

| Repository                  | Test Command   | Lint Command        |
| --------------------------- | -------------- | ------------------- |
| otel-data-api               | `make test`    | `pre-commit run -a` |
| otel-data-gateway           | `npm run test` | `npm run lint:all`  |
| otel-data-ui                | `npm run test` | `npm run lint:all`  |
| otel-agents                 | `make test`    | `pre-commit run -a` |
| k8s-gitops                  | N/A            | `pre-commit run -a` |
| AnsiblePlaybooks            | N/A            | `pre-commit run -a` |
| homelab-infrastructure      | N/A            | `pre-commit run -a` |
| homelab-database-migrations | N/A            | `pre-commit run -a` |
