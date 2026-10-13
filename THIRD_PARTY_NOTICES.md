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


## ParaLimbo 1 benchmark recordings

The selected T4 voltage traces and their processed derivatives in
`docs/paralimbo-1/results.json` and the interactive benchmark are adapted from
Gruntman, Romani and Reiser (2018), *Simple integration of fast excitation and
offset, delayed inhibition computes directional selectivity in Drosophila*,
[Nature Neuroscience](https://doi.org/10.1038/s41593-017-0046-4). Dataset:
[Gruntman_2017_Data.zip, version 1](https://doi.org/10.25378/janelia.5576101.v1),
licensed under [Creative Commons Attribution-NonCommercial 4.0 International](https://creativecommons.org/licenses/by-nc/4.0/).

Changes: selected one recorded T4 cell and nine condition/trial pairs; converted
and filtered voltage samples, subtracted baselines, aligned onset grids and
plotted paired model predictions. The released derived recordings retain
CC BY-NC 4.0; Cognesia's research and personal-use license does not replace or
extend those source-data permissions. No endorsement by the authors is implied.
Model predictions and original code retain their separately stated terms.

BANC anatomy is credited to Bates et al. and The BANC-FlyWire Consortium;
FlyWire annotations retain their original attribution. The ParaLimbo 1 source
release does not include compiled connectomes, raw graph tables or optical
assignment tables. Those inputs require separate acquisition and review of
the original providers' terms.
