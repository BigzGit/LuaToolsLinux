# Security audit

## Architecture and compatibility contracts (before remediation)

- `plugin.json` loads `backend/main.py` under Millennium. Public PascalCase functions and `Logger.*` return JSON strings; the UI depends on those names and shapes.
- `standalone_cli.py` calls the same functions. `web_bridge_server.py` serves GET `/health` and POST `/rpc` on 127.0.0.1:38495 by default. `ui_injector.py` copies assets and embeds JavaScript into Steam HTML for standalone operation.
- UI runs in Steam client, store and community contexts. Backend RPC can launch processes, download and install executable content, modify SLSsteam configuration, and delete games. Browser content is therefore a privileged trust boundary.
- ACCELA supports configured executable paths, AppImages, run.sh and launch_debug.sh. DepotDownloader receives argument arrays. Steam restart uses a delayed shell script. Steam and library roots may be symlinks and custom mount points.
- Download providers supply Lua/manifests to ACCELA and Steam; fixes write files into user-selected game roots and record a legacy-compatible removal log. Update sources supply executable plugin code.
- Settings and locale JSON, Steam VDF, SLSsteam YAML, launcher path text files, API templates, update configuration and fix logs are separate untrusted data inputs.
- Shell installers invoke upstream installation scripts and package managers; sudo is used for system packages and Millennium installation. No native/Lua implementation is present: SLSsteam and headcrab are unavailable gitlinks. CSS/themes are local assets.

## Confirmed findings and proposed remediation

| Severity | Location | Attacker / exploit / root cause | Remediation and regression risk |
|---|---|---|---|
| Critical | web_bridge_server: dispatch and HTTP handlers | Any website can invoke destructive RPC through wildcard CORS, without credentials; imported helpers are callable too. | Authenticated standalone bridge, explicit RPC surface, Host/Origin and request validation. Must provision credentials through existing UI injection. |
| High | fixes: extraction and unfix worker | Malicious provider ZIP `APPID/../../file` writes outside game; malicious fix log deletes arbitrary absolute/relative paths. Existing symlinks redirect extraction. | Validate every archive/log path before mutation; refuse linked descendants; keep both ZIP layouts and log formats. |
| High | main: AppID, workshop and DLC/token configuration | RPC string AppIDs inject YAML/newlines or escape workshop directories; remote DLC names inject YAML. Type hints do not validate inputs. | Validate numeric IDs and serialize scalar values; preserve JSON responses and valid IDs. |
| High | Install-Millenium.sh | Corrupt/tampered archive still installed after checksum failure; predictable staging and elevated copying amplify impact. | Fail closed, private staging, verify before removing old installation; preserve dry-run. |
| High | downloads and downloadsbroke | Provider URL containing ryuu.lol anywhere receives user's cookie; complete API-key URLs are logged; secret files use ambient permissions. | Exact HTTPS hostname matching, redact URL credentials, private atomic secret writes. |
| High | steam_utils: manifest installdir | Crafted manifest escapes common directory, and full uninstall recursively deletes resolved path. | Reject absolute/traversing manifest paths while retaining linked library roots. |
| Medium | main: config.yaml.tmp | Predictable temporary file follows attacker-planted symlinks and concurrent operations race. | Private random atomic writes and serialization of config mutations. |
| Medium | public/luatools.js | Fix metadata and update messages reach innerHTML, executing attacker-controlled HTML in privileged UI. | Escape dynamic metadata and use text for confirmations; retain explicitly static warning markup. |
| Medium | auto_update.restart / linux_platform LD_AUDIT | Shell-active characters in installation paths become commands. | Pass restart executable as shell arguments; quote generated export values. |
| Medium | install.sh EXIT trap | Release installation overwrites immutable-filesystem restoration trap. | One cleanup handler preserves restoration on failure. |
| Medium | standalone installer PID file | Shared /tmp PID filename follows symlinks during writes. | Private per-user state directory. |
| High | donate_keys / settings.options | Decryption-key donation was enabled by default and sent keys over plaintext HTTP without explicit consent. | Fixed in the follow-up: default off, legacy consent reset, explicit opt-in and configured HTTPS recipient required; no redirects or HTTP fallback. |

## Initial baseline

Isolated copy and HOME, no live Steam or installer execution: smoke tests 9/13 pass. Three failures require Steam; fourth is an existing missing safeMode default. Locale validator, node syntax and bash syntax for all four scripts pass. No test/lint/type/build manifests beyond the smoke test and locale validator are present.

History screening: 313 reachable blobs scanned for private-key, GitHub token and AWS key signatures; none matched. This is not proof that arbitrary credentials are absent. The tracked app-access-token database is intentional application data; validity/ownership cannot be determined locally, and history was not rewritten.

## Remediation results

The proposed fixes above are implemented. The donation vulnerability was missed in the first remediation pass and corrected in the follow-up described below. Additional confirmed findings addressed during implementation:

- **High — tracked credential exposure (`backend/keys.json`)**: a non-empty Morrenus API key was present in one reachable historical blob. Anyone with repository access could recover it; its current validity was not tested. The unused legacy configuration now contains an empty value, and a regression test prevents shipping a non-empty default. The active settings workflow still stores user-provided keys in ignored `backend/api.json`. **The owner must revoke/rotate the old key. Clearing the working tree does not revoke it or remove history.**
- **Medium — generated shell wrappers (`install_with_slssteam.sh`)**: shell-active characters in the installation path were embedded directly in shell source. Bash `%q` now quotes generated executable/script paths, with a metacharacter regression test.
- **Medium — transport downgrade (`http_client.py`)**: followed HTTPS redirects could downgrade executable downloads to HTTP. A response hook now rejects this transition before sending the next request. Intentionally configured initial HTTP URLs remain a compatibility conflict rather than being silently removed.
- **Medium — update staging/integrity (`auto_update.py`)**: interrupted downloads could leave a pending update file. Downloads now stage privately, validate ZIP names/CRC, verify SHA-256 when the release API or custom manifest supplies it, and atomically publish only after validation. Older manifests without digests still work. This is not signature verification or protection against a compromised publisher.
- **Medium — linked file writes/permissions (`downloads.py`, `downloadsbroke.py`, `fixes.py`)**: destination symlinks could redirect manifest/Lua/log writes or recursive execute-bit changes. Atomic replacement prevents leaf-link writes; native permission fixes use no-follow file descriptors and regular-file checks. ZIP names are validated before passing downloads to ACCELA.

### Important implementation details

- Bridge credentials are random, installation-local and mode 0600. The injector embeds the credential into Steam HTML and makes that HTML owner-only because it now contains a credential. The normal Millennium API continues to take precedence in JavaScript.
- GET `/health` remains unauthenticated and non-mutating. POST `/rpc` requires `X-LuaTools-Token`, JSON, a bounded body, a recognized Host and an allowed Origin when supplied. Opaque `null` origins remain supported for local-file Steam contexts, but still require the token. The bridge is restricted to 127.0.0.1; there is no documented remote-use requirement.
- Archive extraction validates the complete member list before writing. It accepts flat and AppID-prefixed layouts, preserves existing executable permissions, supports symlinked installation roots and prevents traversal through linked descendants. Directory descriptors protect member operations against symlink substitution. Removal validates the complete log-derived deletion plan first.
- SLSsteam writes preserve line-oriented configuration and comments. Random temporary files replace predictable `.tmp` files; process-local locking serializes RPC configuration mutations. This does not coordinate separate CLI/plugin processes or external SLSsteam writers.
- Installer ZIP paths are validated and archive symlinks rejected. Python 3, already an application requirement, is used consistently instead of alternating between unzip and Python. Upstream scripts are downloaded completely over HTTPS before execution. Their contents are still trusted upstream code.
- Installer user configuration removal no longer uses sudo. System package removal/copy remains privileged as required. Millennium checksum failure exits before extraction, uninstall or privileged copying. Dry-run skips uninstall and post-install writes.

## Files changed and reasons

| File | Reason |
|---|---|
| `backend/security.py` | Shared ID validation, configuration serialization, private atomic writes and confined ZIP/file operations. |
| `backend/bridge_auth.py` | Stable per-installation bridge token with private permissions and locked initialization. |
| `backend/web_bridge_server.py` | Authenticate RPC, limit exposed methods, validate Host/Origin and request shape/size, enforce loopback. |
| `backend/ui_injector.py` | Provision token through existing injection and protect credential-bearing HTML permissions. |
| `backend/main.py` | Validate RPC IDs; serialize YAML values and replace predictable configuration writes. |
| `backend/downloads.py` | Scope cookies to HTTPS Ryuu hosts, encode API-key values, protect secret/download/file writes, validate archives before launcher execution. |
| `backend/downloadsbroke.py` | Apply equivalent security fixes to the retained alternative implementation. |
| `backend/fixes.py` | Confine archive writes and logged deletions; protect file writes and execute-bit handling. |
| `backend/steam_utils.py` | Reject escaping manifest install directories and linked intermediate descendants while retaining custom library roots. |
| `backend/auto_update.py` | Confine extraction, validate/stage downloads and supplied digests; pass restart executable as shell arguments. |
| `backend/http_client.py` | Reject HTTPS downgrade redirects while retaining TLS verification and proxy configuration. |
| `backend/linux_platform.py` | Quote the generated LD_AUDIT export. |
| `backend/logger.py` | Redact URL userinfo/query strings and recognized credential assignments before all logger outputs. |
| `backend/keys.json` | Clear the exposed unused legacy key while retaining the JSON shape. |
| `public/luatools.js` | Authenticate fallback RPC, escape dynamic metadata, render confirmation messages as text, preserve explicit static warning markup. |
| `Install-Millenium.sh` | Fail closed on checksum/install failure, use private staging, correct dry-run and reduce elevated deletion scope. |
| `install.sh` | Preserve immutable-system cleanup, validate extraction, fetch complete HTTPS scripts, reduce elevated deletion scope. |
| `install_with_slssteam.sh` | Validate extraction, quote generated paths, move PID state out of shared `/tmp`, preserve healer paths containing spaces. |
| `update.sh` | Validate extraction and restrict curl download/redirect protocols to HTTPS. |
| `tests/test_security.py` | Primitive path, symlink, credential-scope, numeric-ID and secret-default regressions. |
| `tests/test_backend_security.py` | RPC, configuration, launcher, fix-removal, manifest, transport and update integration regressions with mocked external effects. |
| `tests/test_installers.py` | Stubbed checksum failure, malicious ZIP and generated-wrapper tests. |
| `tests/test_ui_security.js` | JavaScript escaping/text rendering and static warning markup tests using a minimal DOM fixture. |
| `SECURITY_AUDIT.md` | Architecture, findings, compatibility evidence and remaining risks. |

## Compatibility and validation

Verified locally:

- Public RPC names and JSON result envelopes, including the standalone logging API.
- Valid integer/numeric-string AppIDs; malicious IDs are rejected before side effects.
- ACCELA custom executable paths containing spaces, `$` and `;`, default run.sh discovery, argument-array execution and existing environment cleanup. Actual ACCELA binaries were mocked.
- Lua `setManifestid` commenting, numeric Lua selection, and depot-manifest installation.
- Flat/AppID-prefixed ZIP layouts; relative file removal in the legacy log format; custom Steam library paths containing spaces.
- SLSsteam comments, FakeAppId configuration and YAML-safe DLC strings with quotes/newlines/backslashes.
- Stable standalone token provisioning and owner-only credential-bearing HTML.
- Text confirmations and the existing formatted full-deletion warnings.
- Matching update SHA-256 acceptance and mismatching digest rejection without publishing a pending file.
- Installer checksum failure stops before extraction or system changes; generated wrappers parse with hostile-looking installation paths.

Executed results:

- `python -m unittest discover -s tests -v`: **22 passed**, using dependencies installed only in `/tmp/luatools-audit-venv`.
- `node tests/test_ui_security.js`: **passed** (escaping, text confirmations, static markup).
- `node --check public/luatools.js`: **passed**.
- Python parsing with the Python 3.10 grammar: **31 Python files passed**; execution used Python 3.13, not a Python 3.10 runtime.
- `bash -n` on all four shell scripts: **passed**.
- Existing smoke suite in an isolated copy/HOME: **9/13 passed**, same four baseline failures. Three require Steam; the fourth expects a pre-existing absent `safeMode` default. No new smoke failures.
- Locale validator in an isolated copy: **passed**. Its generated formatting output was not included.
- `git -c core.whitespace=cr-at-eol diff --check`: **passed**. Existing CRLF/mixed line endings were retained.
- No configured lint/type/build pipeline exists; shellcheck/ruff/tsc were unavailable. Syntax checks are not substitutes for semantic type checking.
- `pip-audit` queried the resolved isolated environment: no reported advisories in the resolved application packages (`httpx` 0.27.2, `beautifulsoup4` 4.15.0, `ruamel.yaml` 0.18.6 and their resolved dependencies). It reported 12 advisory records, including duplicates, for the environment's **pip 25.1.1**. Pip is host/bootstrap tooling, not pinned by this repository; the audit did not upgrade the developer's tools. No speculative application dependency upgrades were made. Unlocked transitive versions mean existing deployments can differ.

Reference checks: [HTTPX TLS behavior](https://www.python-httpx.org/advanced/ssl/), [HTTPX releases](https://github.com/encode/httpx/releases), and [ruamel.yaml upstream package history](https://pypi.org/project/ruamel.yaml/). Automated advisory results are point-in-time evidence, not a guarantee about future vulnerabilities.

## Remaining risks and required follow-up

1. **Rotate/revoke the exposed Morrenus key.** Its value remains recoverable from Git history. No credential was used and no external rotation or history rewrite was attempted. Other tracked app-access-token data is intentional application input; ownership and validity were not verified.
2. **Donation follow-up corrected:** donation no longer has a default recipient and cannot use HTTP. An operator must configure a trusted HTTPS endpoint using `LUATOOLS_DONATION_URL`, then the user must explicitly enable donation. The old endpoint was removed without inventing an upstream TLS replacement. Explicitly configured legacy HTTP download providers remain a separate unresolved risk; they do not receive decryption-key donations.
3. **Upstream code trust remains.** ACCELA, Steam/Millennium, headcrab, remote installers, game fixes, Lua content and unsigned updates can execute code by design. No mechanism can make a compromised authorized publisher safe while retaining arbitrary plugin/fix execution. Digest checking only helps where trusted metadata supplies a digest.
4. **Native code is unavailable.** `SLSsteam/SLSsteam` and `headcrab/h3adcr-b` are gitlinks without source here. No submodule code, external binaries, remote installers, native IPC implementation or their dependency trees were audited.
5. **Live integration needs validation.** No real Steam/Millennium UI, ACCELA/DepotDownloader process, privileged installation, package-manager operation, destructive uninstall or external game download was run. Real Chromium origin/CSP behavior and Millennium's own RPC authorization remain unverified. The allowed origin list reflects the repository's Steam contexts and may need adjustment if a supported client uses a different origin.
6. **Standalone deployment migration:** run the updated `luatools-heal-ui` after updating an existing standalone installation, then restart Steam and the bridge so the injected token and backend match. Re-save existing API credentials to apply the new private atomic-write permissions. The normal Millennium call path is unchanged.
7. **Local concurrency/resources:** configuration locking is process-local; concurrent external writers can still lose updates. Large authenticated downloads and archives are not given arbitrary size limits because legitimate content sizes are unknown. No resistance to malicious code already running as the same OS user is claimed.
8. **Pre-existing behavior defects remain:** smoke settings-default mismatch, DLC section matching and SLSsteam status parsing have non-security correctness issues outside these fixes. They were not silently refactored during security work.

No commits, deployment, user account changes, real game deletion or secret-bearing generated files were added. This audit supports the specific remediations and tests above; it does not establish that the application is fully secure or that all legitimate live behavior has been exhaustively verified.


## Follow-up: default-on HTTP DecryptionKey donation corrected

The earlier description of this feature as opt-in was incorrect: the original settings schema set `donateKeys=True`. Severity: **High**, as Steam depot decryption keys were automatically disclosed to the configured remote server and exposed to network interception.

- `backend/settings/options.py`: default now false; disclosure identifies Steam depot decryption keys and config.vdf instead of calling this a placeholder or spare-key donation.
- `backend/settings/manager.py`: schema version 2 migrates older settings to donation disabled, including previously persisted true values. Other settings remain intact. Re-enabling requires a configured HTTPS recipient, displayed in the settings description.
- `backend/donate_keys.py`: removes the hardcoded HTTP recipient. The optional `LUATOOLS_DONATION_URL` environment setting must specify HTTPS, without userinfo or fragments. Consent is checked even for direct calls to the sender. Redirects are explicitly disabled, TLS verification remains enabled by the shared HTTP client, and failures never fall back to plaintext or log response details.
- `backend/auto_update.py`: checks consent and HTTPS configuration before extracting keys.
- `public/luatools.js`: shows the accurate disclosure even when an old translation still contains the misleading placeholder description.
- `tests/test_donation_security.py`: six local tests cover defaults, legacy migration, opt-in requirements, extraction gating, direct sender gating, payload preservation, redirects and failures. Network calls use mocks and synthetic keys only.

Deploying the updated code and restarting the backend applies the settings migration automatically. No key donation can occur until a trusted HTTPS endpoint is configured and the user opts in again. No live donation endpoint was contacted, and no real Steam key was read or transmitted. These protections cannot undo prior disclosure.
