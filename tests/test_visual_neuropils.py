import json

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.parquet as parquet
import pytest
from scipy import sparse

from flybrain.visual_neuropils import load_neuropil_weights, neuropil_traces


BASE = 720575940606000000


def fixture_data(root):
    (root / "build").mkdir()
    (root / "data/raw").mkdir(parents=True)
    # Adjacent IDs beyond float64's exact integer range, in unsorted model order.
    parquet.write_table(pa.table({"root_id": pa.array([BASE + 1, BASE, BASE + 2], type=pa.int64())}),
                        root / "build/neurons.parquet")
    pre = pa.table({"pre_pt_root_id": pa.array([BASE + 1, BASE + 1, BASE, BASE + 5], type=pa.int64()),
                    "neuropil": pa.array(["ME_L", "AL_L", "ME_L", "ME_L"]),
                    "count": pa.array([2, 1, 3, 999], type=pa.int64())})
    post = pa.table({"post_pt_root_id": pa.array([BASE + 1, BASE], type=pa.int64()),
                     "neuropil": pa.array(["ME_L", "AL_L"]),
                     "count": pa.array([1, 3], type=pa.int64())})
    feather.write_feather(pre, root / "data/raw/per_neuron_neuropil_count_pre_783.feather", chunksize=2)
    feather.write_feather(post, root / "data/raw/per_neuron_neuropil_count_post_783.feather", chunksize=1)


def test_streamed_counts_normalize_columns_and_preserve_adjacent_root_ids(tmp_path):
    fixture_data(tmp_path)
    package = load_neuropil_weights(tmp_path)
    assert package["names"] == ["AL_L", "ME_L"]
    np.testing.assert_array_equal(package["weights"].toarray(), [[.25, .5, 0], [.75, .5, 0]])
    np.testing.assert_array_equal(np.asarray(package["weights"].sum(axis=0)).ravel(), [1., 1., 0.])
    meta = package["metadata"]
    assert meta["model_pre_plus_post_endpoint_count"] == 10
    assert meta["source_measurements"]["pre"]["excluded_endpoint_count"] == 999
    assert meta["source_measurements"]["pre"]["record_batches"] == 2
    assert meta["source_measurements"]["post"]["record_batches"] == 2
    assert meta["missing_weight_indices"] == [2]
    assert meta["missing_weight_root_ids"] == [str(BASE + 2)]
    np.testing.assert_array_equal(sparse.load_npz(tmp_path / "build/visual_neuropil_counts.npz").toarray(),
                                  [[1, 3, 0], [3, 3, 0]])


def test_region_voltage_is_fraction_weighted_mean_and_baseline_is_consistent(tmp_path):
    fixture_data(tmp_path)
    raw = np.array([[-50., -40., 1000.], [-48., -42., 0.]], dtype=np.float32)
    baseline = np.array([-52., -48., -99.], dtype=np.float32)
    traces = {trace["name"]: trace for trace in neuropil_traces(tmp_path, raw, baseline)}
    al = traces["AL_L"]
    np.testing.assert_allclose(al["raw_mv"], [(-50 * .25 - 40 * .5) / .75, (-48 * .25 - 42 * .5) / .75])
    np.testing.assert_allclose(al["baseline_mv"], [(-52 * .25 - 48 * .5) / .75] * 2)
    np.testing.assert_allclose(al["delta_mv"], np.array(al["raw_mv"]) - al["baseline_mv"])
    assert al["n_recorded"] == al["n_total"] == 2
    assert al["not_spike_rate"] is True
    assert al["biological_validation"] is False
    assert al["weight_sum"] == .75
    assert al["endpoint_count"] == 4
    assert al["missing_weight_neurons_global"] == 1


def test_scalar_and_per_frame_baselines(tmp_path):
    fixture_data(tmp_path)
    raw = np.full((2, 3), -50., dtype=np.float32)
    scalar = neuropil_traces(tmp_path, raw, -52.)
    full = neuropil_traces(tmp_path, raw, np.full((2, 3), -52., dtype=np.float32))
    for a, b in zip(scalar, full):
        np.testing.assert_allclose(a["delta_mv"], [2., 2.])
        np.testing.assert_allclose(a["delta_mv"], b["delta_mv"])


def test_cache_reuse_skips_stream_and_corruption_fails_closed(tmp_path, monkeypatch):
    fixture_data(tmp_path)
    package = load_neuropil_weights(tmp_path)
    assert not package["cache_hit"]

    def unexpected_stream(*args):
        raise AssertionError("Cached neuropils must not rescan 43 million rows")

    monkeypatch.setattr("flybrain.visual_neuropils._aggregate_counts", unexpected_stream)
    assert load_neuropil_weights(tmp_path)["cache_hit"]
    (tmp_path / "build/visual_neuropil_weights.npz").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="cache changed"):
        load_neuropil_weights(tmp_path)


def test_changed_real_source_rebuilds_cache(tmp_path):
    fixture_data(tmp_path)
    load_neuropil_weights(tmp_path)
    post = pa.table({"post_pt_root_id": pa.array([BASE + 1], type=pa.int64()),
                     "neuropil": ["ME_L"], "count": pa.array([5], type=pa.int64())})
    feather.write_feather(post, tmp_path / "data/raw/per_neuron_neuropil_count_post_783.feather")
    updated = load_neuropil_weights(tmp_path)
    assert not updated["cache_hit"]
    assert updated["metadata"]["model_pre_plus_post_endpoint_count"] == 11
    np.testing.assert_allclose(updated["weights"].toarray(), [[1 / 8, 0, 0], [7 / 8, 1, 0]])


def test_missing_recordings_are_not_silently_removed_from_region_denominator(tmp_path):
    fixture_data(tmp_path)
    with pytest.raises(ValueError, match="finite"):
        neuropil_traces(tmp_path, np.array([[-52., np.nan, -52.]]), -52.)
    with pytest.raises(ValueError, match="all model neurons"):
        neuropil_traces(tmp_path, np.array([[-52., -52.]]), -52.)


def test_float_root_schema_is_rejected(tmp_path):
    fixture_data(tmp_path)
    bad = pa.table({"pre_pt_root_id": pa.array([float(BASE + 1)], type=pa.float64()),
                    "neuropil": ["ME_L"], "count": pa.array([2], type=pa.int64())})
    feather.write_feather(bad, tmp_path / "data/raw/per_neuron_neuropil_count_pre_783.feather")
    with pytest.raises(ValueError, match="schema"):
        load_neuropil_weights(tmp_path)


def test_literal_none_source_label_is_preserved_and_explicitly_unassigned(tmp_path):
    fixture_data(tmp_path)
    post = pa.table({"post_pt_root_id": pa.array([BASE + 1], type=pa.int64()),
                     "neuropil": ["None"], "count": pa.array([7], type=pa.int64())})
    feather.write_feather(post, tmp_path / "data/raw/per_neuron_neuropil_count_post_783.feather")
    traces = neuropil_traces(tmp_path, np.full((1, 3), -50., np.float32), -52.)
    unassigned = next(trace for trace in traces if trace["name"] == "None")
    assert unassigned["is_unassigned"]
    assert unassigned["n_total"] == 1
    np.testing.assert_allclose(unassigned["delta_mv"], [2.])
