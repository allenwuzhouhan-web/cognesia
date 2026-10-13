"""Synthetic software regression checks; these are not biological benchmarks."""
from pathlib import Path
import json
import subprocess
import sys

import numpy as np
import pytest
from scipy import sparse
import flybrain
import paralimbo1
from flybrain.hybrid_engine import HybridEngine
from flybrain.neural_baseline import initialize_equilibrium, complete_residual, partition_counts

ROOT = Path(__file__).resolve().parents[1]


def make_engine(*, dt=.1, cap=.8, weights=(100., -80.)):
    p = paralimbo1.parameters() | {"dt": dt, "graded_input_cap": cap}
    w = sparse.csr_matrix((weights, ([1, 2], [0, 1])), shape=(3, 3))
    return HybridEngine(w, sparse.csr_matrix((3, 3)), np.array([True, True, False]), p, threads=1)


def test_own_imports_and_pinned_source_bytes():
    assert Path(flybrain.__file__).resolve() == ROOT / "src/flybrain/__init__.py"
    assert Path(paralimbo1.__file__).resolve() == ROOT / "src/paralimbo1/__init__.py"
    subprocess.run([sys.executable, str(ROOT / "scripts/check_source.py")], check=True)


@pytest.mark.parametrize("dt", [.1, .05, .025])
def test_equilibrium_preserves_voltage_synapse_and_delays(dt):
    e = make_engine(dt=dt)
    result = initialize_equilibrium(e, [0], [10.])
    assert result["max_fixed_point_residual_mv"] < 1e-10
    v, g = e.v.copy(), e.g.copy()
    r = e.run(100, photoreceptor_indices=np.array([0]), photoreceptor_drive=10.)
    np.testing.assert_allclose(e.v, v, atol=1e-10, rtol=0)
    np.testing.assert_allclose(e.g, g, atol=1e-10, rtol=0)
    assert r["clamp_count"] == 0 and not len(r["spike_indices"])
    assert complete_residual(e, [0], 10.)["max_delay_history_residual_mv"] < 1e-10


def test_gain_cap_preserves_counts_and_weak_rows():
    e = make_engine(weights=(100., 20000.))
    assert e.graded_counts.tolist() == [100., 20000.]
    np.testing.assert_allclose(e.graded_row_scale, [1., 1., .08])
    initialize_equilibrium(e, [0], [10.])
    assert e.v[2] < -45
    assert not len(e.run(100, photoreceptor_indices=np.array([0]), photoreceptor_drive=10.)["spike_indices"])


def test_partition_conserves_counts_and_modes():
    w = sparse.csr_matrix(([3., -4., 2.], ([1, 2, 0], [0, 1, 2])), shape=(3, 3))
    g, s = partition_counts(w, np.array([True, False, True]))
    assert (g + s != w).nnz == 0
    assert g.indices.tolist() == [2, 0] and s.indices.tolist() == [1]


def test_perturbation_decays():
    e = make_engine()
    initialize_equilibrium(e, [0], [10.])
    v = e.v.copy()
    e.v[1] += .5
    e.run(1000, photoreceptor_indices=np.array([0]), photoreceptor_drive=10.)
    assert abs(e.v - v).max() < 1e-9


@pytest.mark.parametrize("cap", [0, 1, -1, float("nan"), True])
def test_invalid_gain_caps_rejected(cap):
    with pytest.raises(ValueError, match="graded_input_cap"):
        make_engine(cap=cap)


def test_missing_graph_fails_actionably(tmp_path):
    with pytest.raises(FileNotFoundError, match="source release excludes compiled connectome"):
        paralimbo1.check_graph_inputs(tmp_path)


def test_corrupt_graph_manifest_is_rejected_before_loading(tmp_path):
    expected = paralimbo1.archived_manifest()
    folder = tmp_path / "build/model-versions" / paralimbo1.MODEL_HASH
    folder.mkdir(parents=True)
    for name in ["manifest.json", *expected["output_hashes"]]:
        (folder / name).write_text("{}")
    with pytest.raises((KeyError, ValueError)):
        paralimbo1.check_graph_inputs(tmp_path)


def test_rebuild_rejects_self_consistent_different_base_at_pinned_path(tmp_path):
    from flybrain.model_registry import get_model_manifest, stable_hash
    from flybrain.neural_baseline import BASE_MODEL, BASE_HASH
    other = {"schema_version": 1, "id": BASE_MODEL, "output_hashes": {}}
    other["model_hash"] = stable_hash(other)
    assert other["model_hash"] != BASE_HASH
    folder = tmp_path / "build/model-versions" / BASE_HASH
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps(other))
    # The frozen loader verifies self-consistency and ID, but trusts the
    # requested directory. The publication boundary must verify the hash pin.
    assert get_model_manifest(tmp_path, BASE_MODEL, BASE_HASH) == other
    with pytest.raises(ValueError, match="Original base manifest identity differs"):
        paralimbo1.check_rebuild_inputs(tmp_path)
