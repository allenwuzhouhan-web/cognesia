# Publishing Cognesia and ParaLimbo

Public repository: [allenwuzhouhan-web/cognesia](https://github.com/allenwuzhouhan-web/cognesia).
The app and model have separate release tags in the same repository:

- `v0.0.2`: Cognesia source preview with personal access key protection.
- `paralimbo-v0.1.0-alpha.1`: ParaLimbo compiler, pinned acquisition recipe and validation evidence.

Original code and documentation remain **all rights reserved**. Public source
availability is not an open-source license. Preserve `LICENSE` and
`THIRD_PARTY_NOTICES.md`; upstream datasets retain their own artifact-specific terms.

## Verify and export

Use Python 3.12. Install the locked environment described in
[reproduction instructions](fly-model/reproduce.md), then run:

```sh
python -m pytest -q -m 'not integration and not slow'
node --test tests/test_web_*.mjs macos/test_desktop_bridge.mjs macos/test_research_bridge.mjs
python scripts/prepare_public_release.py --check
python scripts/prepare_public_release.py --export
```

The exporter writes `release/Cognesia-v0.0.2/`, a matching ZIP and a SHA-256
manifest. It includes current tracked and unignored source files, including
uncommitted work. It excludes the original Git history, local environments,
private credentials, downloaded datasets, recordings and caches. Existing exports
are never overwritten. The bounded audit checks common credential formats,
machine paths, symlinks, forbidden filenames and oversized files; it is not an
exhaustive secret audit.

Build the Python wheel from this exact clean snapshot (`python -m build --wheel`
after installing `build`, or `uv build --wheel`). Verify package version, license,
browser assets and CLI entry point. The native macOS app is built locally using
`python macos/build_app.py`; its bundle is tied to the builder's source checkout.
Do not distribute that machine-bound bundle as a portable installer.

## Update the existing public repository

Use a clean clone of the public repository and fetch its current default branch.
Copy the audited export into that clone while preserving its `.git` directory.
Review the complete staged diff and run checks from the clean source tree. Commit
and push only this clean public history. The original research workspace has
older machine-specific history and must not be pushed wholesale.

Create the two tags at the tested commit. Publish both as prereleases, with
separate release notes and explicit assets:

- App: source ZIP, source-file/checksum manifest, Python wheel.
- Model: source/compiler ZIP, model manifest, structural audit, determinism,
  input-reproduction and runtime reports, plus checksums.

Model release assets should contain recipes and audit summaries, not the upstream
raw datasets or unreviewed derived tables. The pinned acquisition script retrieves
those inputs separately. Preserve their attribution and terms when downloading.

Verify both GitHub release URLs, tags, uploaded asset sizes/checksums and the
public source CI result. Record these independently from local test results.

## Website deployment is separate

The Pages workflow is **manual only**. Pushing source or creating a release does
not deploy the website. GitHub Pages serves static files; signup, key issuance,
account sessions and authoritative usage metering require an application service.
See the [website accounts and admin plan](website-accounts-plan.md),
[existing deployment design](customer-website.md) and
[app access setup](app-access.md).

Only after provisioning and verifying the chosen host, HTTPS, email delivery,
workspaces and account flows should the site describe signup as available. A
working local gateway or GitHub release does not establish public availability.
