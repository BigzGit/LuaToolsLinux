# Security policy

## Reporting

Please report suspected vulnerabilities privately to the maintainers instead of
opening a public issue.

## Secrets

- Never commit real credentials. `.gitignore` excludes `backend/keys.json`,
  `backend/data/`, `backend/temp_dl/` and `**/*.key`.
- `backend/keys.example.json` is a template only; it must stay empty.
- The active Morrenus API key is stored separately in
  `backend/data/morrenus_key.txt` with mode `0600` (directory `0700`) and is
  substituted into API templates in memory only. Legacy keys embedded in
  `backend/api.json` (`?api_key=...`) are migrated automatically on first use.
- If a key was ever committed, it must be treated as compromised and rotated by
  the owner. Removing it from the current tree does not revoke it or remove it
  from Git history.

## Dependency integrity

- `requirements.txt` pins the direct dependencies.
- `requirements.lock` pins all transitive dependencies with SHA-256 hashes and
  is installed with `pip install --require-hashes`.
- Installer scripts are pinned by SHA-256 in `dependencies.lock.json`. A hash
  mismatch is fatal; remote scripts are never executed without a verified hash.

## Third-party components

The following components are **not** vendored in this repository and are
installed from their upstream sources:

- Millennium / SteamClientHomebrew (installer pinned by version + SHA-256).
- enter-the-wired / ACCELA (installer scripts pinned by SHA-256).
- headcrab (installer pinned by SHA-256).
- SLSsteam and ACCELA native binaries.

The previous inconsistent `SLSsteam/SLSsteam` and `headcrab/h3adcr-b` gitlinks
(no `.gitmodules`) were removed; these are external artifacts, not submodules.

## Branch protection

See `.github/BRANCH_PROTECTION.md` for the recommended rules. This repository
does not apply them automatically.

## Residual risks

- Upstream installers and native binaries remain trusted third-party code.
- The local RPC bridge is loopback-only and token-authenticated, but any process
  already running as the same OS user can read the token.
- Steam depot decryption keys are only donated when the user opts in and an
  operator configures an HTTPS recipient.
