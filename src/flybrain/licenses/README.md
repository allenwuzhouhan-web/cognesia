# Third-party license provenance

`shiu-drosophila-brain-model-LICENSE.txt` is the unmodified MIT license from
[Philip Shiu and Nico Spiller's Drosophila brain model](https://github.com/philshiu/Drosophila_brain_model),
commit `91bdd1e7dcf193f3e7ca5a8933497fcef63b7960`.

- Original file: [LICENSE at the pinned commit](https://github.com/philshiu/Drosophila_brain_model/blob/91bdd1e7dcf193f3e7ca5a8933497fcef63b7960/LICENSE).
- Copyright: (c) 2023 Philip Shiu and Nico Spiller.
- License file SHA-256: `3621f6d6476189190e2960fa43f11b275ba4eca848fdac50a1ba2925de6223e8`.
- Reference `model.py` SHA-256 at that commit: `fc45837d7122c6ce2a7f3f2f23c515992e4b232aadb919efabb72337fac88e4e`.

Cognesia's `flybrain fetch` acquires the upstream reference `model.py` and
connectome inputs separately. It also retrieves and verifies this license as
`data/raw/shiu-drosophila-brain-model-LICENSE.txt`, beside the reference code.
The reference implementation is used by `flybrain.validate_engine`; its source
and downloaded datasets are excluded from the source release and wheel.
ParaLimbo's input recipe also uses the completeness table from this repository.
Research data retains its original providers' applicable terms and attribution;
this software notice does not establish a new license for those datasets.

The bundled license is installed at
`flybrain/licenses/shiu-drosophila-brain-model-LICENSE.txt`. The wheel also
contains Cognesia's `LICENSE` and `THIRD_PARTY_NOTICES.md` under its
`flybrain-<version>.dist-info/licenses/` directory. Existing browser-component
licenses and notices remain under `flybrain/web/vendor/` and
`flybrain/web/assets/fly/`.

MIT applies to the covered upstream material. It does not license Cognesia's
separate original material; consult the root `LICENSE` for those terms.
