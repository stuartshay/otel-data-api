## Summary

Refs #<!-- issue number — do NOT use "Closes" or "Fixes" (see below) -->

Describe the change and why it's needed.

## Type of Change

- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature / endpoint (non-breaking)
- [ ] Breaking change (existing behavior altered)
- [ ] Database migration required
- [ ] CI/CD pipeline change
- [ ] Documentation update

## Checklist

- [ ] Read `README.md` and relevant docs
- [ ] No secrets or credentials committed
- [ ] Environment variables used for configuration (not hardcoded)
- [ ] Ran `pre-commit run -a` locally (hooks passing)
- [ ] Ran `make test` (tests passing, coverage ≥ 85%)
- [ ] Ran `make lint` (no lint errors)

## Deployment

- [ ] Does this need [k8s-gitops](https://github.com/stuartshay/k8s-gitops)
      manifest changes?
- [ ] Does this need
      [database migrations](https://github.com/stuartshay/homelab-database-migrations)?
- [ ] Does this publish `@stuartshay/otel-data-types`?

## Testing

```bash
# Commands used to validate changes
make test
make lint
pre-commit run -a
```

## Post-Merge Validation

⚠️ **Do NOT use `Closes #` or `Fixes #` in this PR.** Issues must remain open
until post-deploy acceptance criteria are validated on the cluster.

After this PR merges:

- [ ] Docker image built and pushed (CI)
- [ ] k8s-gitops deployment PR created and merged
- [ ] Argo CD synced to cluster
- [ ] Acceptance criteria validated against deployed behavior
- [ ] Final validation comment posted on the linked issue
- [ ] Issue closed manually after all criteria confirmed
- [ ] If any criterion cannot be validated, reason documented on the issue

## Notes

Any additional context, screenshots, or log output.
