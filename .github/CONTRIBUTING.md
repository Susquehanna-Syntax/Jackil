# Contributing standards

Conventions for issues, branches, commits, and pull requests in Jackil. The
templates in `.github/` enforce most of this — this is the why.

## Issues

- Use the Bug report or Feature request form (blank issues are disabled).
- One issue = one problem or one request.
- Security issues go through a private advisory, never a public issue.
- Never paste secrets, SMTP/IMAP credentials, or customer data.

## Branches

Short, prefixed, kebab-case off `main`:

```
fix/sla-pause-on-pending
feat/kb-article-versioning
docs/proxy-deployment
chore/bump-2026.2.1
```

## Commits

- Plain style. Short subject with the version in parens when it's a release,
  e.g. `Pause the SLA clock on Pending and recompute on priority change (2026.2.1)`.
- One sentence per change on its own line in the body; no bullet lists.
- **No AI / Co-Authored-By trailers.**
- Don't commit secrets, keys, or customer data.

## Pull requests

- Fill in the PR template, including the proposed commit message.
- Tests must pass: `USE_SQLITE=1 .venv/bin/python manage.py test`.
- Run `makemigrations` if a model changed, and commit the migration.
- Keep lint clean: `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`.

## Releases

Jackil's version lives in git tags (there is no in-code version string). A
release is a `vYYYY.N.P` tag on `main` after the PR merges.
