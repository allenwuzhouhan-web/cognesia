# Third-party notices

Cognesia includes the following third-party components. Their original licenses
and notices remain in the source tree and must accompany redistribution.

| Component | Included location | License / attribution |
| --- | --- | --- |
| Three.js and OrbitControls | `src/flybrain/web/vendor/` | MIT; [license](src/flybrain/web/vendor/THREE-LICENSE.txt) |
| NeuroMechFly / FlyGym meshes and rig data | `src/flybrain/web/assets/fly/` | Apache-2.0; [license](src/flybrain/web/assets/fly/LICENSE-APACHE-2.0.txt), [original notice](src/flybrain/web/assets/fly/SOURCE-NOTICE.txt), [provenance and modifications](src/flybrain/web/assets/fly/NOTICE.md) |

The NeuroMechFly source meshes and derived browser geometry are included with
their metadata and provenance manifest. The asset license does not establish
an overall license for Cognesia's original code, which is All rights reserved
as stated in [LICENSE](LICENSE).

FlyWire, BANC, DoOR and other research inputs are acquired separately. They are
not included in this public source package. Consult the original providers for
terms, attribution and citation requirements; their data is not relicensed by
Cognesia. Source decisions are documented in [model sources](docs/model-sources.md),
[odour coverage](docs/odour.md) and the fetch/build implementation.

Python dependencies are installed separately and retain their respective licenses.
