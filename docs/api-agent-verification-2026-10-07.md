# API, local agent and compute verification — 7 October 2026

This records the current local implementation, including the later request to
remove payments and use a workspace password. The paid gateway was stopped;
the replacement does not load its old ledger or access codes. Public hosting
and a domain have not been provisioned. No Stripe account is needed.

## Automated checks

- `.venv/bin/pytest -q -m 'not slow and not integration'`: **824 passed,
  9 deselected**. Nine slow/source integration tests were intentionally excluded;
  this is not a rerun of biological validation or whole-brain benchmarks.
- `node --test tests/test_web_*.mjs macos/test_desktop_bridge.mjs macos/test_research_bridge.mjs`: **156 passed**.
- The focused password API, local-agent, launcher and public-release suite passed
  **70 checks** before the full Python run.
- The new compute, messenger and agent browser scripts pass JavaScript syntax
  checks. The compute dialog and research console were visually inspected.
- Source export check passed: generated model weights, runtime settings, codes
  and private ledgers stay outside the public upload set. The bounded scanner
  now also rejects Cognesia access-code and key patterns.

Coverage includes salted password verification, missing/wrong passwords, removed
payment routes, concurrency, idempotency, cache bounds, HTTP range reads,
model/endpoint restrictions, local-agent tool rounds and cancellation, hardware
consent/revocation, enforced compute caps and origin-restricted native commands.

## Live local services

`build/password-api-verification.json` records the current live gateway check:
31 authenticated tools, HTTP 401 without a password, **51 fresh authorized calls
without payment**, a matching idempotent replay, and HTTP 404 for the former
billing-session, redemption, checkout and webhook routes. No simulation was
started. Everyone holding an instance's password shares its configured workspace;
this is a private collaboration gateway rather than separate account tenancy.

The generated password is in `build/private/api-password.json`; the service loads
only the separate salted scrypt verifier `api-password-hash.json`. Both files are
mode 0600 in a mode 0700 directory and excluded from source exports. Previous
ledger/code files are preserved as inactive private artifacts.

The earlier `build/tool-api-live-smoke.json` additionally records 26 messenger
entries, three distinct seeded drafts and a real HTTP 206 anatomy read. Its
historical pricing metadata has been superseded by the password-only gateway.

## Installed native app

`/Applications/Cognesia.app` compiled with warnings treated as errors and passed
strict local code-signature verification. The installer preserved the previous
bundle as a backup. The bundle uses this checkout and its installed Python/runtime
and model files; it is not a notarized, self-contained distribution.

The installed app started the research service and prepared model, connected
through **⌘K**, and completed a real one-call study through **⌘Return**. **⌘E**
opened the native Save dialog and saved a valid JSON trace after the page's Blob
URL had been revoked. **⌘1/⌘3** switched between the simulation and research
windows while preserving the study editor and result.

The trace is `runs/cognesia-study-623ea106f5ca4c93a3982f4f2e3b6547.json`;
the inspected native screenshot is `build/cognesia-macos-research-verified.png`.

## Scientific interpretation

Ten additional messenger candidates are source-backed annotations with missing
kinetics explicitly unset. Existing point-neuron equations and historical
failed scientific gates are preserved. The exact source-rate copy removal has
snapshot and existing chemistry/replay test coverage; no new biological accuracy
or overall throughput result is asserted.

## Real GPT-OSS-20B check

The 12,109,566,624-byte MXFP4 GGUF download passed a full SHA-256 comparison
against the pinned distributor revision. Homebrew llama.cpp 0.4.1 (build 10964,
commit `b29c606e2`) loaded it locally with a 16,384-token context. The real
model passed the structured tool-call probe, then completed one
`cognesia_resources` call and a final answer reporting the returned zero active
experiments and 40 GB simulation budget. Its one-call budget was enforced. No
scientific experiment was started. After the managed runtime was restricted to
local origins and given a private process credential, the real tool round trip
passed again; an unauthenticated inference request was rejected with HTTP 401.
The macOS launcher successfully started the viewer, console and verified model.

The model manifest retains source/hash evidence; `build/gpt-oss-live-verification.json`
retains the actual local inference trace. This is a tool-connectivity check, not
a complex-study benchmark. Runtime credential endpoint binding and nondisclosure
are included in the current focused suite. Mock model tests and real-model
evidence are recorded separately.
