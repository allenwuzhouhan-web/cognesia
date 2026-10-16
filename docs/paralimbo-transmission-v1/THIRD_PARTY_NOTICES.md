# Third-party notices for the compact transmission evidence package

This package contains selected Cognesia source references, model-generated
traces, recorded T4 observation derivatives, reports and provenance. It omits
third-party dependency binaries, browser libraries, fly meshes, the upstream
Shiu model.py, compiled connectomes and raw anatomical tables.

Original Cognesia code and model predictions are governed by [LICENSE](LICENSE).
Recorded T4 observations retain their separate CC BY-NC 4.0 terms; see the full
source citation, changes and license link in [ATTRIBUTION.md](ATTRIBUTION.md).
Attribution is not endorsement.

The project acknowledges the MIT-licensed Drosophila brain model by Philip Shiu
and Nico Spiller, pinned upstream commit 91bdd1e7dcf193f3e7ca5a8933497fcef63b7960.
Its unmodified [MIT notice](licenses/shiu-drosophila-brain-model-LICENSE.txt) is
retained here for provenance. That license does not replace the license on
Cognesia's separate original material or upstream datasets.

The native implementation uses separately installed NumPy, SciPy, Numba and
other dependencies under their respective terms. Their installed code is not
redistributed in this compact package. The verifier requires an independently
installed NumPy package.

BANC and FlyWire anatomy require separate acquisition and their providers'
terms. No raw graph or optical-assignment tables are included here. For notices
covering the full application rather than this compact evidence archive, see
[the public repository notices](https://github.com/allenwuzhouhan-web/cognesia/blob/main/THIRD_PARTY_NOTICES.md).
