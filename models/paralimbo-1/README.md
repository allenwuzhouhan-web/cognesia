# ParaLimbo 1 — headless model source

**ParaLimbo 1** is the public name for the graded visual model evaluated in the
[five-endpoint benchmark](../../docs/paralimbo-1/README.md). Its scientific ID is
`paralimbo-visual-graded-v1`; its archived compiled model hash is
`229f9970e0b67cfa14658142dbc3adae8614d49887cd131521bf02e4d86cd884`.
This distribution is named `paralimbo-1`, version `1.0.0`.

The package contains the byte-identical headless scientific core used by the
frozen retrospective study, a parameter configuration, the original model
manifest, and a small publication wrapper. It does not contain the Cognesia
desktop app, compiled connectome arrays, optical assignment tables, or datasets.
The public name changes no scientific identity or measured score.

## Benchmarks and scope

The completed study ran 27 native requests: three model variants on nine
conditions from one recorded T4 cell, with one paired trial per condition.
ParaLimbo 1 had lower errors than BANC on all five related endpoints; four
differences exceeded the frozen numerical separation rules (0.14–0.61% lower
error). The fifth was within tolerance. Original ParaLimbo tied BANC on all five.
BANC and original ParaLimbo produced zero evoked selected-cell responses under
the fixed uncalibrated inputs. This is a small retrospective numerical result;
general biological superiority remains unestablished. See the linked benchmark
for every score, direction, threshold, source, and limitation.

## Install in a separate environment

Python 3.12 is required. This package includes a `flybrain` namespace that also
exists in Cognesia. Use an isolated environment to avoid mixing versions.

```sh
python3.12 -m venv .venv-paralimbo1
source .venv-paralimbo1/bin/activate
python -m pip install ./models/paralimbo-1
paralimbo1 identity
```

Run those commands from the repository root. For a downloaded source archive,
install its extracted `paralimbo-1` directory instead. No raw data are downloaded
on import or by the public wrapper.

## Required graph inputs

Running the full graph requires separately acquired, authorized inputs. The
source release does not grant rights to BANC or FlyWire research data. Consult
their providers and [third-party notices](THIRD_PARTY_NOTICES.md).

To run the exact archived model, supply a data root with
`build/model-versions/<model-hash>/manifest.json` and every file listed in
[`output_hashes`](src/paralimbo1/model-manifest.json). The compiled graph has
175,401 neurons, 13,542,180 signed edges and 26,597 graded neurons. Its optical
tables are required by the immutable model binding even for a headless run;
they are not distributed here. A newly fetched graph or approximate optical
map is not a replacement for those exact files.

```sh
paralimbo1 check-inputs --graph-root /path/to/authorized-data-root
```

The check verifies the exact manifest identity and every output checksum. It
refuses missing or changed inputs and does not silently fetch substitutes.

```python
from paralimbo1 import make_engine
from flybrain.neural_baseline import initialize_equilibrium

engine, network = make_engine("/path/to/authorized-data-root", threads=1)
# No external drive: solve a complete quiescent initial state.
initialization = initialize_equilibrium(engine, [], [])
result = engine.run(100.0)
print(initialization, result["clamp_count"])
```

`make_engine` preserves the archived electrical mask and applies the declared
0.8 incoming graded gain cap. The 20 ms graded membrane time constant is the
evaluated default; chemistry and organ coupling are not included. For experiments,
use `initialize_equilibrium(engine, indices, drive)` with explicit, documented
normalized membrane inputs in mV. This short example exercises the dynamics;
it does not implement the study's sensory, trial, and observation pipeline.

## Rebuilding is a separate operation

The frozen `flybrain.neural_baseline.build_candidate` compiler is included.
An exact historical data rebuild additionally needs the original ParaLimbo base
graph (`251615940b84dad843d0cf85138c936e118b0890274231bb8e5720b5b381bb5c`) and
the original `config/reference-visual-map/{manifest.json,columns.parquet,assignments.parquet}`.
These restricted inputs are not distributed. The public command requires a
clean data root and checks their archived bindings before compilation:

```sh
paralimbo1 check-rebuild-inputs --graph-root /path/to/authorized-data-root
paralimbo1 rebuild --graph-root /path/to/authorized-data-root
```

The archived graph was compiled with a different revision of `neural_baseline.py`
than the later frozen study source. Both hashes are recorded in
[`release.json`](src/paralimbo1/release.json). Recompilation can therefore produce
a different model hash even if data arrays agree. Such a rebuild is a new
compiled identity and does not inherit the published benchmark result. The
wrapper's `make_engine` deliberately binds only to the archived tested identity.

## Verify the source package

```sh
python -m pip install -e './models/paralimbo-1[test]' build
python models/paralimbo-1/scripts/check_source.py
python -m pytest -q models/paralimbo-1/tests
python -m build models/paralimbo-1
```

The standard-library source check verifies the unchanged source hashes,
canonical manifest, parameter binding, and closed local import dependencies.
Scoped tests verify the import location, gain cap, anatomical count conservation,
equilibrium and delayed-state behavior on tiny synthetic graphs. They are
software checks, not additional biological benchmarks. No whole-graph jobs
are run by these checks. Wheels include the scientific core, wrapper, parameter
file, model manifest and notices; the source distribution additionally includes
these tests and the source manifest.

Original Cognesia material remains **All rights reserved**, with scientific,
educational and personal-use permissions in [LICENSE](LICENSE).
