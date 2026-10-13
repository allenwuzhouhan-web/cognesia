# Evidence and identity ledger

All 27 native requests completed and all 15 native endpoint scores were scored. The retained local independent audit reports **23,583 checks, zero findings**, verifying the 27 predictions, 15 native scores, five zero-reference scores and ten comparisons. The public [audit summary](evidence/audit-summary.json) is a selected-field report from that completed audit. It is not the full retained study or a new public replay.

## Original identities

| Byte-identical evidence file | Canonical content identity | SHA-256 of file bytes |
|---|---|---|
| `evidence/protocol.json` | `a78a968b766014514657269da41cf1402489ca7936a497b00b4ef847e437baef` | `ed9a5d37321ec61a153c195952186debd0f6b22a2ddb7b79a425704efc116bf8` |
| `evidence/prediction-seal.json` | `c429ebf38aff0d133bfad1c9c0b9c331279f7c9d819c5fd80afa8b017c6508eb` | `09469317dd549ea5cecbcbda9b36b6c3943f270c3d6dd1445276df19f392ac43` |
| `evidence/resource-annex/v1/manifest.json` | `94cae0f918443ca4d563c04d261a7fecdbc0502c33a840b5e56f146cdc99f33d` | `8765aa3caf9632d1ed7c7e3f3a062b70d43a10cc2d09902f0b8625a586f05c27` |

Canonical identity hashes sorted compact JSON with the document's declared identity field omitted. File SHA-256 hashes the exact bytes including whitespace and final newline. These are intentionally distinct.

Original `scores.json` canonical identity: `37c9ac9606feed579a626c5586ca1150333d0d157d57e08f52eaaaa2b3da39d3`.

Original `scores.json` full-file SHA-256: `77ff18cb31e329de905bfde83bdc9e74c28556ef12367ddbfe88f3ec2946db17`.

## Public derivative

`results.json` preserves every scored numeric field, all 15 native scores, five zero-reference scores, ten comparisons and 27 scored traces. Exactly nine machine-local `observation_sources.<case>.source_path` values were removed. Frozen model IDs remain unchanged; display aliases are in `publication.model_names`. `source_scores_sha256` identifies the original scored object. It does **not** claim that the redacted public file has the original score identity.

Public results canonical identity: `84a77f46ea60798b905723caecac83666c1f13a0f60428484078b3efde0d86ab`.

Public results full-file SHA-256: `0e0b0a85b0809a157380b29ec8da8e09a7da5a130d2e13ece3565f0ee6bcd5be`.

See [machine-readable identities](evidence/identities.json). `public_results_sha256` omits only its own field from canonical hashing.

## What is and is not packaged

This publication contains derived scored traces, exact tables, figures, the public model definition and selected immutable evidence. It excludes the compiled graph, parquet inputs, raw experimental archive, complete source snapshot and full retained study. Manifest-relative paths inside the byte-identical evidence refer to the original study layout and may point to material not distributed here. They are provenance records, not promises that those files exist in this publication.

Full-state checkpoints were actually serialized, restored and replayed per request before removal under the retention policy. The public artifact supports independent score arithmetic and identity checking; it does not support offline full-state replay without the separately pinned inputs and runtime.
