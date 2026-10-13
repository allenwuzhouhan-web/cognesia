# ParaLimbo 1 third-party notices

Original Cognesia and ParaLimbo source remains All rights reserved subject to
the scientific, educational and personal-use grant in [LICENSE](LICENSE).

This headless package does not bundle Three.js, FlyGym meshes, raw recordings,
compiled connectomes or optical assignment tables. BANC anatomy is credited to
Bates et al. and The BANC-FlyWire Consortium. FlyWire annotations and all other
research inputs retain their providers' terms. Consult the repository's
[umbrella notice](../../THIRD_PARTY_NOTICES.md) for dataset attribution and the
separately published benchmark recordings. No research-data rights are granted
by this software license.

The spiking reference parameters cite the Drosophila brain model of Philip Shiu
and Nico Spiller, DOI 10.1038/s41586-024-07763-9. Their separately acquired
reference implementation is MIT licensed, copyright (c) 2023 Philip Shiu and
Nico Spiller. The complete unmodified license is included at
`src/flybrain/licenses/shiu-drosophila-brain-model-LICENSE.txt`; its SHA-256 is
`3621f6d6476189190e2960fa43f11b275ba4eca848fdac50a1ba2925de6223e8`.
The reference `model.py` and its data are not bundled. Retain its copyright and
complete license when redistributing that separately obtained code.

NumPy, SciPy, Numba, pandas, PyArrow, PyYAML and psutil are installed separately
under their respective licenses. This notice does not imply author endorsement
or biological validation.

In a wheel, the reference license is under `flybrain/licenses/`; this notice
and Cognesia LICENSE are in `paralimbo_1-1.0.0.dist-info/licenses/`.
