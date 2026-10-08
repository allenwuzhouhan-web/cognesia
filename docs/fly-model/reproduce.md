# Reproduce ParaLimbo

Use the source checkout at tag `paralimbo-v0.1.0-alpha.1`, Python 3.12 and the
included dependency lock. Raw BANC/FlyWire datasets are downloaded separately
under their upstream terms; they are not included in the source release.

From the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python scripts/prepare_paralimbo_inputs.py --root .
.venv/bin/flybrain --root . models compile-paralimbo
.venv/bin/flybrain --root . models validate-paralimbo
```

The input preparation script acquires exact pinned URLs, verifies checksums,
and reconstructs the historical BANC model and FlyWire donor table. Stop on a
checksum or dependency mismatch; do not relax pins to obtain a passing result.
The compile command freezes the new model and runs its construction audit.

Expected model hash:

```text
251615940b84dad843d0cf85138c936e118b0890274231bb8e5720b5b381bb5c
```

The authoritative model is stored under `build/model-versions/<model_hash>/`;
`build/models/paralimbo-v0-1-0/` is a convenience copy. Inspect `manifest.json`,
`policy.json`, `crosswalk.parquet`, `annotation_ledger.parquet` and
`conflicts.parquet`. The input donor table is captured in the local frozen
artifact so later working-table changes cannot reinterpret this version.
The [release manifest](evidence/manifest.json) and [published aggregate results](results.md)
provide reference hashes and outcomes without requiring a download of model data.

Run the bounded execution/replay check separately:

```sh
.venv/bin/python scripts/validate_paralimbo_runtime.py --root .
```

This performs two full-network dark runs with chemistry and writes
`build/validation_paralimbo_runtime.json`. Its scope and exact acceptance rules
are in the [validation protocol](validation-protocol.md). Optional eye-mapping
inputs and all effective runtime inputs must remain recorded in the run
manifest; do not compare runs whose inputs differ.

Focused compiler fixtures:

```sh
.venv/bin/python -m pytest -q tests/test_paralimbo.py tests/test_paralimbo_runtime.py
```

Input acquisition requires network access. The two pinned BANC files total
416,664,684 bytes and the FlyWire completeness/annotation files add 35,045,852
bytes, before local intermediate and frozen outputs. Allow several gigabytes
of free storage because compilation retains independent artifact copies.
Memory and wall time depend on the machine; this release does not establish a
minimum supported hardware configuration. Model construction and numerical
checks do not require a hosted account; opening the protected Cognesia viewer
requires the configured personal access key service described in the app docs.

Reproduction has been checked on the release environment. Exact cross-platform
artifact reproduction is not established by two builds on the same machine.
Report environment, dependency versions and mismatching hashes if your build
differs. [Results](results.md) distinguishes source reproduction, deterministic
compilation, bounded runtime and pending biology.

The [bootstrap acceptance report](evidence/validation_paralimbo_bootstrap.json)
records fresh downloads of the two pinned FlyWire tables, checksum-verified
cached BANC raw inputs, reconstruction of both exact model inputs, and a
second run with no downloads. BANC network downloads were not repeated by that
acceptance check.
