# Cognesia 0.0.2 and ParaLimbo 0.1 alpha verification

Release verification performed on 2026-10-08. This document distinguishes software
checks, model construction and biological evidence. Publication is verified
separately through the GitHub release pages and Actions run.

## Full model

Frozen ParaLimbo identity:
`251615940b84dad843d0cf85138c936e118b0890274231bb8e5720b5b381bb5c`.

- 52 structural and source-fidelity checks passed.
- Two full compilations produced identical hashes and every manifest field.
- Isolated assembly reproduced both the exact BANC baseline model hash and the
  pinned FlyWire donor-neuron table checksum.
- All 175,401 neurons were simulated in two repeats of a paired 300 ms dark
  experiment after 100 ms fixed preparation. Every saved numeric activity and
  chemistry array was finite and identical across repeats. The recording sampled
  32 specified neuron IDs; it is not a saved voltage trace for every neuron.
- Preparation, experimental arms and paired baselines had zero clamp events;
  preparation had zero nonfinite endpoint derivatives. The short preparation
  endpoint was stationary under the configured tolerance. Long-term stability,
  timestep convergence and biological predictive improvement remain unestablished.

See the [model results](fly-model/results.md), [protocol](fly-model/validation-protocol.md)
and [reproduction recipe](fly-model/reproduce.md) for scope, source counts and
acceptance criteria. Release JSON assets retain the actual checks and hashes.

## App and package

- Personal-key tests exercise fail-closed access, identity binding, scope checks,
  session expiry/revalidation, CSRF, origin checks and private internal transport.
- Browser modules and both native JavaScript bridges: 167 tests passed.
- Native macOS app: optimized Swift build with warnings treated as errors,
  Info.plist validation and ad-hoc code-signature verification passed. The built
  bundle references its own local checkout and is not a portable release asset.
- Python wheel version 0.0.2 builds successfully. Source ZIP and wheel are the app
  preview distribution; native users build the shell from the source checkout.
- Original code retains its all-rights-reserved notice. Third-party notices remain
  included. No upstream raw datasets or private access state are bundled.

Final clean-source check: **931 Python tests passed, 9 integration/slow tests
excluded**, in 100.82 seconds. The separate full-data construction, reproduction
and runtime checks above cover their documented scope. The clean source tree
contained no cached models, recordings or private state; tests reused the
installed release dependency environment, rather than reinstalling dependencies.
The clean-tree wheel contains 193 files; version metadata, compiler, access gate,
browser UI and third-party licenses were checked. This tested snapshot defines
the release boundary; later concurrent workspace changes remain local.

The [real access report](evidence/app-access-0.0.2.json) records 23 passing
checks using actual registry/CLI and loopback HTTP transport, including revocation
after 31.015 seconds without altering the clock. Website signup, automatic customer-key issuance,
admin usage reports and public HTTPS deployment are planned separately; this
release does not make those services live.

The release also corrects the visual-stimulus default to use at most the
available thread capacity. Regression cases cover one, four and 64 available
threads while retaining rejection of explicit requests above capacity.
