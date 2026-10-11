# Third-party notices

Cognesia bundles or separately acquires the following third-party components.
Their original licenses and notices must accompany copies or redistributions
as required by each component's license.

| Component | Included location | License / attribution |
| --- | --- | --- |
| Three.js and OrbitControls | `src/flybrain/web/vendor/` | MIT; [license](src/flybrain/web/vendor/THREE-LICENSE.txt) |
| NeuroMechFly / FlyGym meshes and rig data | `src/flybrain/web/assets/fly/` | Apache-2.0; [license](src/flybrain/web/assets/fly/LICENSE-APACHE-2.0.txt), [original notice](src/flybrain/web/assets/fly/SOURCE-NOTICE.txt), [provenance and modifications](src/flybrain/web/assets/fly/NOTICE.md) |
| Shiu and Spiller Drosophila brain reference implementation | Separately downloaded `data/raw/model.py`, used by the Brian2 reference comparison | MIT; Copyright (c) 2023 Philip Shiu and Nico Spiller; [complete upstream license](src/flybrain/licenses/shiu-drosophila-brain-model-LICENSE.txt), [source identity and scope](src/flybrain/licenses/README.md) |

The NeuroMechFly source meshes and derived browser geometry are included with
their metadata and provenance manifest. The asset license does not establish
an overall license for Cognesia's original code. Original Cognesia material is
**All rights reserved** except for the scientific, educational and personal-use
permissions expressly granted in [LICENSE](LICENSE). These restrictions do not
replace or narrow any third-party license.

The Shiu and Spiller implementation is acquired separately, not bundled as
`model.py` in the source or wheel distribution. Its exact MIT license is bundled
and is preserved beside the downloaded reference file. Retain both its copyright
notice and complete license when copying or redistributing the reference code.
This attribution does not imply endorsement or biological validation of Cognesia.

FlyWire, BANC, DoOR and other research inputs are acquired separately. They are
not included in this public source package. Consult the original providers for
terms, attribution and citation requirements; their data is not relicensed by
Cognesia. Source decisions are documented in [model sources](docs/model-sources.md),
[odour coverage](docs/odour.md) and the fetch/build implementation.

Python dependencies are installed separately and retain their respective licenses.

## Installed wheel locations

The wheel includes this notice and the Cognesia license together under
`flybrain-<version>.dist-info/licenses/`. Paths beginning `src/flybrain/` in the
table above correspond to `flybrain/` in the installed package: the Shiu license
is in `flybrain/licenses/`, Three.js in `flybrain/web/vendor/`, and fly-asset
licenses and notices in `flybrain/web/assets/fly/`. The license README records
upstream source links and checksums. Data acquired separately retain their own
artifact-specific terms.
