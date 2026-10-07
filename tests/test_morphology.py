import json
import struct

import numpy as np
import pandas as pd
import pytest

from flybrain.morphology import (
    _allocation, _import_parquet, build_overview, morphology_neuron,
    morphology_status, parse_skeleton_binary,
)


def test_binary_uses_nanometers_without_voxel_scaling_and_preserves_edges():
    vertices = np.array([[4000, 8000, 40000], [6000, 9000, 42000]], dtype='<f4')
    edges = np.array([[0, 1]], dtype='<u4')
    radius = np.array([500, 250], dtype='<f4')
    data = struct.pack('<II', 2, 1) + vertices.tobytes() + edges.tobytes() + radius.tobytes()
    actual, links, radii = parse_skeleton_binary(data)
    np.testing.assert_allclose(actual, [[4, 8, 40], [6, 9, 42]])
    np.testing.assert_array_equal(links, edges)
    np.testing.assert_allclose(radii, [.5, .25])
    with pytest.raises(ValueError, match='length'):
        parse_skeleton_binary(data[:-1])
    bad = struct.pack('<II', 2, 1) + vertices.tobytes() + np.array([[0, 8]], dtype='<u4').tobytes()
    with pytest.raises(ValueError, match='indices'):
        parse_skeleton_binary(bad)


def fixture_source(tmp_path):
    (tmp_path / 'build').mkdir()
    # Model order differs from source order; each neuron is split across batches.
    pd.DataFrame({'root_id': [303, 101, 202, 404]}).to_parquet(tmp_path / 'build/neurons.parquet')
    table = pd.DataFrame({
        'neuron': [101, 303, 202, 303, 101, 202, 303],
        'node_id': [5, 8, 2, 3, 1, 9, 11],
        'parent_id': [1, 3, -1, -1, -1, 2, 8],
        'x': [5000, 8000, 2000, 3000, 1000, 9000, 11000],
        'y': [1000] * 7, 'z': [2000] * 7, 'radius': [250] * 7,
    })
    table = table.astype({'node_id': 'int32', 'parent_id': 'int64',
                          'x': 'float32', 'y': 'float32', 'z': 'float32', 'radius': 'int32'})
    source = tmp_path / 'source.parquet'
    table.to_parquet(source, row_group_size=2)
    return source


def test_stream_import_preserves_exact_root_order_and_edges_across_batches(tmp_path):
    source = fixture_source(tmp_path)
    manifest = _import_parquet(tmp_path, source, batch_size=2)
    assert manifest['vertex_count'] == 7
    assert manifest['edge_count'] == 4
    assert manifest['covered_neuron_count'] == 3
    assert manifest['missing_neuron_count'] == 1
    assert not manifest['all_model_neurons_covered']
    assert manifest['unresolved_parent_count'] == 0
    out = tmp_path / 'build/visual/morphology'
    np.testing.assert_array_equal(np.load(out / 'root_ids.npy'), [303, 101, 202, 404])
    np.testing.assert_array_equal(np.load(out / 'vertex_offsets.npy'), [0, 3, 5, 7, 7])
    np.testing.assert_array_equal(np.fromfile(out / 'edges.bin', dtype='<u4').reshape(-1, 2),
                                  [[0, 1], [2, 0], [0, 1], [1, 0]])
    metadata = morphology_neuron(tmp_path, 0)
    assert metadata['root_id'] == '303'
    assert metadata['coordinate_units'] == 'um'
    positions = np.fromfile(out / 'neurons/0/vertices.bin', dtype='<f4').reshape(-1, 3)
    np.testing.assert_allclose(positions[:, 0], [8, 3, 11])
    assert morphology_status(tmp_path)['status'] == 'ready'


def test_overview_uses_real_edges_and_covers_every_available_neuron_when_budget_allows(tmp_path):
    _import_parquet(tmp_path, fixture_source(tmp_path), batch_size=2)
    metadata = build_overview(tmp_path, 3)
    assert metadata['segment_count'] == 3
    assert metadata['represented_neuron_count'] == 3
    assert not metadata['all_model_neurons_represented']  # 404 really is absent.
    out = tmp_path / 'build/visual/morphology/overview/3'
    owners = np.fromfile(out / 'owners.bin', dtype='<u4')
    positions = np.fromfile(out / 'positions.bin', dtype='<f4').reshape(-1, 2, 3)
    np.testing.assert_array_equal(owners, [0, 1, 2])
    np.testing.assert_allclose(positions[:, :, 0], [[8, 3], [5, 1], [9, 2]])
    assert build_overview(tmp_path, 3) == metadata
    # API readers and a preparation worker may request the same budget together.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as workers:
        replies = list(workers.map(lambda _: build_overview(tmp_path, 4), range(4)))
    assert all(reply == replies[0] for reply in replies)


def test_fair_budget_is_exact_capped_and_does_not_invent_missing_neurons():
    for budget in range(1, 30):
        counts = np.array([0, 1, 3, 14, 2])
        result = _allocation(counts, budget)
        assert result.sum() == min(budget, counts.sum())
        assert np.all(result <= counts)
        if budget >= 4:
            assert np.all(result[counts > 0] >= 1)


def test_reordered_model_cannot_report_ready_or_serve_stale_overview(tmp_path):
    manifest = _import_parquet(tmp_path, fixture_source(tmp_path), batch_size=2)
    overview = build_overview(tmp_path, 3)
    directory = tmp_path / 'build/visual/morphology'
    # A previous ready progress record must not override the stale manifest check.
    (directory / 'status.json').write_text(json.dumps(manifest))
    original_manifest = (directory / 'manifest.json').read_bytes()
    original_overview = (directory / 'overview/3/metadata.json').read_bytes()
    pd.DataFrame({'root_id': [101, 303, 202, 404]}).to_parquet(tmp_path / 'build/neurons.parquet')
    status = morphology_status(tmp_path)
    assert status['status'] == 'not_prepared'
    assert status['requires_prepare']
    assert status['root_order_sha256'] != manifest['root_order_sha256']
    for budget in (3, 4):  # Both cached and newly requested budgets fail closed.
        response = build_overview(tmp_path, budget)
        assert response['status'] == 'not_prepared'
        assert response['requires_prepare']
        assert 'positions_url' not in response
        assert 'owners_url' not in response
    assert (directory / 'manifest.json').read_bytes() == original_manifest
    assert (directory / 'overview/3/metadata.json').read_bytes() == original_overview
    # Restoring matching model order can reuse the untouched, verified cache.
    pd.DataFrame({'root_id': [303, 101, 202, 404]}).to_parquet(tmp_path / 'build/neurons.parquet')
    assert morphology_status(tmp_path) == manifest
    assert build_overview(tmp_path, 3) == overview


def test_neuron_fallback_is_cached_and_bad_index_never_fetches(tmp_path, monkeypatch):
    (tmp_path / 'build').mkdir()
    pd.DataFrame({'root_id': [987654321]}).to_parquet(tmp_path / 'build/neurons.parquet')
    vertices = np.array([[1000, 2000, 3000], [2000, 3000, 4000]], dtype='<f4')
    data = struct.pack('<II', 2, 1) + vertices.tobytes() + np.array([[0, 1]], dtype='<u4').tobytes()
    import io
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return io.BytesIO(data)
    monkeypatch.setattr('flybrain.morphology.urllib.request.urlopen', fetch)
    metadata = morphology_neuron(tmp_path, 0)
    assert metadata['root_id'] == '987654321'
    assert metadata['edge_count'] == 1
    assert morphology_neuron(tmp_path, 0) == metadata
    assert len(calls) == 1
    partial = build_overview(tmp_path, 1000000)
    assert partial['status'] == 'partial'
    assert partial['represented_neuron_count'] == 1
    assert not partial['all_model_neurons_represented']
    path = tmp_path / 'build/visual/morphology/overview/1000000/partial'
    np.testing.assert_array_equal(np.fromfile(path / 'owners.bin', dtype='<u4'), [0])
    np.testing.assert_allclose(np.fromfile(path / 'positions.bin', dtype='<f4').reshape(1, 2, 3),
                               [[[1, 2, 3], [2, 3, 4]]])
    timestamp = (path / 'positions.bin').stat().st_mtime_ns
    assert build_overview(tmp_path, 1000000) == partial
    assert (path / 'positions.bin').stat().st_mtime_ns == timestamp
    with pytest.raises(ValueError, match='outside'):
        morphology_neuron(tmp_path, 1)
    assert len(calls) == 1
