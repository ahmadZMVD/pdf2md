## Summary

Describe the change and why it is needed.

## Verification

- [ ] `python scripts/pre_push_check.py`
- [ ] Relevant cloud CI job passed
- [ ] No document-conversion scope was added unless explicitly planned

## Risk and rollback

Describe affected boundaries, known risks, and how to revert safely.

## Checklist

- [ ] Semantic commit subject (`feat:`, `fix:`, `docs:`, `perf:`, or `refactor:`)
- [ ] Tests cover the changed behavior
- [ ] Documentation is updated where contracts changed
- [ ] No secrets, generated build output, or personal data are included
