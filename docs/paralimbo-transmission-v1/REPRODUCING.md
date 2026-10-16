# Verify this publication offline

Use Python 3.12 with NumPy installed. From the public repository root:

```sh
python scripts/verify_transmission_publication.py
python -m pytest -q tests/test_transmission_publication.py
```

The release ZIP includes the verifier and complete evidence folder. In its
extracted root, the same first command verifies the included publication.
Verification reads local files and does not download data, start a simulation,
select another candidate or access a remote service.

The verifier checks published file hashes, both unchanged prediction seals,
observation trial selection, every condition error, all five endpoint formulas,
comparison statuses, and the equal eight-proposal development inventory.
Compact native observation traces permit checking recorded refinement and
selection arithmetic. A successful check means the published evidence agrees
with its arithmetic; it does not turn incomplete comparisons into wins.

## What is preserved and what is transformed

- The original final prediction NPZs, prediction seals, scores and selected
  candidate records are preserved byte-for-byte where indicated in
  [public-provenance.json](public-provenance.json).
- The 166 native trace projections contain exact observation-array members.
  [trace-inventory.json](trace-inventory.json) records the original archive hash,
  published path, member dtype/shape and member-byte hash. Full-population hidden
  states are omitted. Their original archive hashes attest the local extraction;
  the public package can recheck only the included bytes.
- Local machine paths are removed from specified public documents. Their new
  public hashes are distinct from the original artifact hashes. Historical seal
  identifiers in such projections identify the original local experiment and
  are not valid seals for the changed document bytes.
- [source-inventory.json](source-inventory.json) identifies the frozen
  implementation references. Four default workspace-root literals were made
  portable, with original and published hashes recorded. The remaining source
  references are unchanged. These excerpts are not a standalone native engine
  package and are not imported by the offline verifier.

The original campaign identity is
`d8e027ebb3b71bfb32fbaa43b958ae641a103010f06f90d8b7a37012274b0671`.
It binds a larger source, input, anatomy and reference inventory. This compact
publication does not independently reconstruct that complete native identity.
A full native rerun needs separately acquired model/input artifacts and the
recorded environment. No full rerun is claimed by this publication.

## Retained methodological limits

The primary T4c predictions were sealed before their evaluation scoring. The
fixed alternate T4d predictions were generated after primary outcomes were
loaded and sealed before their own scoring. The inherited alternate-seal flag
does not establish that no primary evaluation access had occurred.

All 108 final T4 native replay fields are null. Exact checkpoint replay evidence
covers four direct pilots, not every T4 request. No new cold/cache equivalence
or hard-crash exercise was performed for final acceptance. The retained replay
I/O-denial log was capped at eight entries and was not an operating-system audit.

See [the full report](README.md) and both independent
[scientific](reviews/scientific-review.md) and
[engineering](reviews/engineering-review.md) reviews. The result remains
engineering incomplete, comparison inconclusive, and biological validation
pending.
