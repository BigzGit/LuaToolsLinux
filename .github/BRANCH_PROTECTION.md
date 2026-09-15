# Branch protection rules (recommended, not applied by this repository)

These rules must be configured by the repository owner in GitHub settings.
This file documents the recommendation; the workflow in `.github/workflows/ci.yml`
does **not** activate them.

For the `main` branch:

- Require a pull request before merging.
- Require at least one approving review.
- Require status checks to pass before merging, and select:
  - `test`
  - `secret-scan`
  - `dependencies`
- Require branches to be up to date before merging.
- Require conversation resolution before merging.
- Require linear history (optional but recommended).
- Do not allow force pushes.
- Do not allow deletions.
- Restrict who can push to matching branches (optional).

Additional repository settings:

- Enable secret scanning and push protection.
- Enable Dependabot alerts and security updates.
- Restrict GitHub Actions to the actions used by `ci.yml`.

Because the repository is archived, these settings are only meaningful if it is
un-archived and actively maintained.
