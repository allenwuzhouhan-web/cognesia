"""The eye inspector must expose the same assignments as the simulation adapter."""
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain.eye import build_eye_mapping, column_directions
from flybrain.model_eye import build_model_eye_mapping
from flybrain.workbench_api import model_eye_map


def write_optics(root, spacing=6.2, center=48.):
    path = root / 'config'; path.mkdir(exist_ok=True)
    for name, key, value in [('parameters.yaml', 'eye_spacing', spacing),
                              ('visual_parameters.yaml', 'eye_center_azimuth_deg', center)]:
        (path / name).write_text(f'parameters:\n  {key}:\n    value: {value}\n    unit: degrees\n    source: TEST\n')


def provider_fixture(root, monkeypatch):
    write_optics(root)
    neurons = pd.DataFrame({'root_id': [720575940635780001, 720575940635780002, 720575940635780003, 720575940635780004],
        'entity_id': ['banc:1', 'banc:2', 'banc:3', 'banc:4'], 'cell_type': ['R7', 'R8', 'R7', 'central'],
        'cell_class': ['visual', 'visual', 'visual', 'central'],
        'native_cell_class': ['photoreceptor_neuron'] * 3 + ['interneuron'],
        'side': ['left', 'right', '', 'left'], 'is_graded': [True, True, True, False],
        'pos_x': [2., 3., 1., 0.], 'pos_z': [1., 2., 3., 4.]})
    folder = root / 'build/models/banc-626';folder.mkdir(parents=True)
    neurons.to_parquet(folder / 'neurons.parquet', index=False)
    manifest = {'id': 'banc-626', 'model_hash': 'a' * 64, 'optical_mapping_supported': False}
    def get_manifest(_root, model):
        if model != 'banc-626':raise ValueError('Unknown model')
        return manifest
    monkeypatch.setattr('flybrain.model_registry.get_model_manifest', get_manifest)
    state = SimpleNamespace(root=root, neuron_table=lambda: pytest.fail('Provider optics fell back to FlyWire'))
    return state, neurons, manifest


def test_provider_inspector_matches_engine_mapping_and_preserves_exact_root_ids(tmp_path, monkeypatch):
    state, neurons, manifest = provider_fixture(tmp_path, monkeypatch)
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob('*'))
    result = model_eye_map(state, 'banc-626')
    expected = build_model_eye_mapping(tmp_path, {'neurons': neurons, 'manifest': manifest}, spacing_deg=6.2, eye_center_deg=48.)
    assert result['model_id'] == 'banc-626' and result['model_hash'] == manifest['model_hash']
    assert [item['index'] for item in result['receptors']] == expected.photoreceptor_indices.tolist() == [0, 1]
    assert [item['column_index'] for item in result['receptors']] == expected.photoreceptor_columns.tolist()
    assert result['receptors'][0]['root_id'] == '720575940635780001'
    assert result['receptors'][0]['entity_id'] == 'banc:1'
    assert result['columns'][0]['anchor_root_id'] == '720575940635780001'
    assert result['audit'] == expected.audit
    np.testing.assert_allclose([item['azimuth_deg'] for item in result['columns']], expected.columns.azimuth_deg)
    assert result['audit']['photoreceptors_unassigned'] == 1
    assert sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob('*')) == before
    json.dumps(result, allow_nan=False)


def flywire_fixture(root, monkeypatch):
    write_optics(root)
    neurons = pd.DataFrame({'root_id': [720575940635780001, 720575940635780002, 720575940635780003],
        'cell_type': ['Mi1', 'L1', 'R1-6'], 'side': ['right'] * 3})
    export = pd.DataFrame({'root_id': neurons.root_id[:2], 'type': ['Mi1', 'L1'],
        'hemisphere': ['right'] * 2, 'column_id': [17, 17], 'p': [0, 0], 'q': [0, 0], 'x': [0, 0], 'y': [0, 0]})
    source = root / 'data/raw/codex';source.mkdir(parents=True);export.to_csv(source / 'column_assignment.csv', index=False)
    build = root / 'build';build.mkdir(exist_ok=True)
    counts = sparse.csr_matrix(([5., 8.], ([0, 1], [1, 2])), shape=(3, 3))
    sparse.save_npz(build / 'reference_counts.npz', counts)
    manifest = {'id': 'flywire-783', 'model_hash': 'b' * 64, 'optical_mapping_supported': True}
    monkeypatch.setattr('flybrain.model_registry.get_model_manifest', lambda *_: manifest)
    return SimpleNamespace(root=root, neuron_table=lambda: neurons), neurons, counts


def test_flywire_missing_cache_builds_same_mapping_without_persisting(tmp_path, monkeypatch):
    state, neurons, counts = flywire_fixture(tmp_path, monkeypatch)
    result = model_eye_map(state)
    expected = build_eye_mapping(tmp_path, neurons, counts, spacing_deg=6.2, eye_center_deg=48., persist=False)
    assert not (tmp_path / 'build/visual').exists()
    assert [item['index'] for item in result['receptors']] == expected.photoreceptor_indices.tolist() == [2]
    assert result['receptors'][0]['root_id'] == '720575940635780003'
    assert result['columns'][0]['anchor_root_id'] == '720575940635780001'
    assert result['audit'] == expected.audit


def test_flywire_cached_map_uses_current_optics_and_does_not_modify_cache(tmp_path, monkeypatch):
    state, neurons, counts = flywire_fixture(tmp_path, monkeypatch)
    saved = build_eye_mapping(tmp_path, neurons, counts, spacing_deg=5.1, eye_center_deg=45., persist=True)
    paths = list((tmp_path / 'build/visual').iterdir());before = {path: path.read_bytes() for path in paths}
    monkeypatch.setattr('flybrain.eye.build_eye_mapping', lambda *args, **kwargs: pytest.fail('Valid mapping cache was rebuilt'))
    result = model_eye_map(state)
    expected = column_directions(saved.columns, 6.2, 48.)
    np.testing.assert_allclose([item['azimuth_deg'] for item in result['columns']], expected.azimuth_deg)
    assert result['audit']['retinotopy_assumptions'][0].startswith('6.2 degree')
    assert result['audit']['retinotopy_assumptions'][-1].startswith('eye centers at +/-48 degrees')
    assert {path: path.read_bytes() for path in paths} == before


def test_provider_get_route_returns_selected_mapping_and_rejects_unknown_model(tmp_path, monkeypatch):
    from flybrain.visual_server import make_handler
    state, _, _ = provider_fixture(tmp_path, monkeypatch)
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
    client = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    try:
        client.request('GET', '/api/model-eyes?model_id=banc-626')
        response = client.getresponse();body = json.loads(response.read())
        assert response.status == 200 and body['model_id'] == 'banc-626'
        assert len(body['receptors']) == 2
        client.request('GET', '/api/model-eyes?model_id=unavailable-source')
        response = client.getresponse();body = json.loads(response.read())
        assert response.status == 400 and body['error'] == 'Unknown model'
    finally:
        client.close();server.shutdown();server.server_close();thread.join(timeout=2)
