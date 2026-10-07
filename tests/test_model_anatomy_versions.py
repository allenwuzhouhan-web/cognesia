"""Source-version regressions for full anatomy and directed connectivity APIs."""
from contextlib import contextmanager, nullcontext
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain.fetch import checksum
from flybrain.inspect_data import atomic_write_json
from flybrain.model_anatomy import model_anatomy_directory, prepare_model_anatomy
from flybrain.model_registry import _freeze_model, get_model_manifest, stable_hash
from flybrain.workbench_api import connectivity


MODEL = 'fixture-composite'
ROOT_IDS = [9007199254740993, 9007199254740995, 33]


def neurons(ids=ROOT_IDS):
    return pd.DataFrame({'root_id': ids, 'entity_id': [f'banc:888:{i}' for i in ids],
        'cell_type': ['sensory-a', 'central-b', 'unlocated-c'],
        'super_class': ['sensory', 'central', 'central'], 'side': ['left', 'right', 'left'],
        'root_region': ['AL_L', 'AL_R', 'AL_L'],
        'pos_x': [0., 250., np.nan], 'pos_y': [0., 500., np.nan], 'pos_z': [0., 25., np.nan]})


def publish(root, table, forward, reverse):
    folder = root/'build/models'/MODEL
    folder.mkdir(parents=True, exist_ok=True)
    table.to_parquet(folder/'neurons.parquet', index=False)
    graded = sparse.csr_matrix(([forward, reverse], ([1, 0], [0, 1])), shape=(3, 3))
    for name, matrix in [('graded', graded), ('spiking', sparse.csr_matrix((3, 3)))]:
        for field in ['data', 'indices', 'indptr']:
            np.save(folder/f'{name}_{field}.npy', getattr(matrix, field))
    files = ['neurons.parquet'] + [f'{name}_{field}.npy' for name in ['graded', 'spiking'] for field in ['data', 'indices', 'indptr']]
    manifest = {'id': MODEL, 'neurons': 3, 'output_hashes': {name: checksum(folder/name) for name in files}}
    manifest['model_hash'] = stable_hash(manifest)
    _freeze_model(root, folder, manifest)
    atomic_write_json(folder/'manifest.json', manifest)
    return manifest['model_hash']


@pytest.fixture
def versions(tmp_path):
    old_table = neurons()
    old_hash = publish(tmp_path, old_table, 3., -2.)
    new_table = neurons([103, 101, 102]); new_table.loc[1, 'pos_x'] = 750.
    new_hash = publish(tmp_path, new_table, 11., -13.)
    return SimpleNamespace(root=tmp_path, old=old_hash, new=new_hash, old_table=old_table, new_table=new_table)


@contextmanager
def endpoint(root):
    from flybrain.visual_server import make_handler
    state = SimpleNamespace(root=root, cache_operation=nullcontext, wiring=None)
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    def request(path, payload=None):
        client.request('GET' if payload is None else 'POST', path,
                       body=None if payload is None else json.dumps(payload),
                       headers={} if payload is None else {'Content-Type': 'application/json'})
        response = client.getresponse()
        return response.status, response.read()
    try:
        yield request
    finally:
        client.close(); server.shutdown(); server.server_close(); thread.join()


def test_historical_anatomy_uses_frozen_rows_after_current_alias_changes(versions):
    v = versions
    # No historical anatomy cache exists yet: even its first build must use the
    # frozen old table, although the mutable alias already names a newer table.
    old = prepare_model_anatomy(v.root, MODEL, v.old)
    current = prepare_model_anatomy(v.root, MODEL)
    old_dir = model_anatomy_directory(v.root, MODEL, v.old)
    assert old_dir == v.root/'build/model-versions'/v.old/'anatomy'
    assert old['model_hash'] == v.old and current['model_hash'] == v.new
    identities = json.loads((old_dir/'identities.json').read_text())
    assert [r['index'] for r in identities] == [0, 1, 2]
    assert [r['root_id'] for r in identities] == list(map(str, ROOT_IDS))
    assert [r['entity_id'] for r in identities] == [f'banc:888:{i}' for i in ROOT_IDS]
    assert np.fromfile(old_dir/'visible_indices.bin', dtype='<u4').tolist() == [0, 1]
    np.testing.assert_array_equal(np.fromfile(old_dir/'positions.bin', dtype='<f4').reshape(-1, 3),
                                  [[-.5, -1, -.5], [.5, 1, .5], [0, 0, 0]])
    assert json.loads((old_dir/'regions.json').read_text())['root_region:AL_L'] == [0, 2]
    cached_bytes = {p.name: p.read_bytes() for p in old_dir.iterdir()}
    assert prepare_model_anatomy(v.root, MODEL, v.old) == old
    assert cached_bytes == {p.name: p.read_bytes() for p in old_dir.iterdir()}
    for key in ['metadata_url', 'positions_url', 'groups_url', 'visible_indices_url', 'identities_url', 'regions_url']:
        assert parse_qs(urlparse(old[key]).query) == {'model_hash': [v.old]}


def test_anatomy_rejects_wrong_provider_and_invalid_version(versions):
    with pytest.raises(ValueError, match='another provider'):
        prepare_model_anatomy(versions.root, 'different-model', versions.old)
    with pytest.raises(ValueError, match='Invalid model hash'):
        prepare_model_anatomy(versions.root, MODEL, '../manifest')
    with pytest.raises(FileNotFoundError):
        prepare_model_anatomy(versions.root, MODEL, '0'*64)


def test_http_assets_propagate_historical_hash_and_reject_incompatible_requests(versions):
    v = versions
    with endpoint(v.root) as request:
        status, body = request(f'/api/model-anatomy/{MODEL}/metadata.json?model_hash={v.old}')
        assert status == 200
        metadata = json.loads(body)
        for key, name in [('positions_url', 'positions.bin'), ('groups_url', 'groups.bin'),
                          ('visible_indices_url', 'visible_indices.bin'), ('identities_url', 'identities.json'),
                          ('regions_url', 'regions.json'), ('metadata_url', 'metadata.json')]:
            status, content = request(metadata[key])
            assert status == 200
            assert content == (v.root/'build/model-versions'/v.old/'anatomy'/name).read_bytes()
        status, body = request(f'/api/model-anatomy/{MODEL}/metadata.json')
        assert status == 200 and json.loads(body)['model_hash'] == v.new
        for path in [f'/api/model-anatomy/different-model/metadata.json?model_hash={v.old}',
                     f'/api/model-anatomy/{MODEL}/metadata.json?model_hash=invalid',
                     f'/api/model-anatomy/{MODEL}/manifest.json?model_hash={v.old}']:
            status, body = request(path)
            assert status == 400 and 'error' in json.loads(body)


def test_explicit_connectivity_hash_uses_frozen_edges_and_qualified_identities(versions):
    v = versions; state = SimpleNamespace(root=v.root)
    options = {'model_id': MODEL, 'source_indices': [0], 'target_indices': [1]}
    old = connectivity(state, options | {'model_hash': v.old})
    current = connectivity(state, options)
    assert old['forward']['edge_count'] == 1 and old['forward']['synapse_count'] == 3.
    assert old['reverse']['edges'][0]['weight'] == -2.
    assert old['forward']['edges'][0]['source_id'] == f'banc:888:{ROOT_IDS[0]}'
    assert old['forward']['edges'][0]['target_id'] == f'banc:888:{ROOT_IDS[1]}'
    assert current['forward']['synapse_count'] == 11.
    assert current['forward']['edges'][0]['source_id'] == 'banc:888:103'
    with endpoint(v.root) as request:
        status, body = request('/api/connectivity', options | {'model_hash': v.old})
        assert status == 200 and json.loads(body) == old
        status, body = request('/api/connectivity', options | {'model_hash': 'bad-hash'})
        assert status == 400 and 'Invalid model hash' in json.loads(body)['error']


def test_recorded_connectivity_keeps_local_row_order_and_rejects_conflicting_hash(versions):
    v = versions; state = SimpleNamespace(root=v.root)
    folder = v.root/'runs/old-recording'; folder.mkdir(parents=True)
    atomic_write_json(folder/'visual_summary.json', {'model_id': MODEL, 'model_hash': v.old})
    v.old_table.iloc[[1, 0]].to_parquet(folder/'recorded_neurons.parquet', index=False)
    options = {'model_id': MODEL, 'run_id': 'old-recording', 'source_indices': [0], 'target_indices': [1]}
    result = connectivity(state, options | {'model_hash': v.old})
    assert result['forward']['edges'][0]['weight'] == -2.
    assert result['forward']['edges'][0]['source_id'] == f'banc:888:{ROOT_IDS[1]}'
    assert result['forward']['edges'][0]['source_index'] == 1
    assert connectivity(state, options) == result
    with pytest.raises(ValueError, match='differs from the recording'):
        connectivity(state, options | {'model_hash': v.new})
    with endpoint(v.root) as request:
        status, body = request('/api/connectivity', options | {'model_hash': v.new})
        assert status == 400 and 'differs from the recording' in json.loads(body)['error']


def test_uncached_anatomy_rejects_changed_frozen_source_table(versions):
    table = versions.old_table.copy(); table.loc[0, 'root_id'] = 123
    table.to_parquet(versions.root/'build/model-versions'/versions.old/'neurons.parquet', index=False)
    with pytest.raises(ValueError, match='(?i)(changed|checksum|hash|identity)'):
        prepare_model_anatomy(versions.root, MODEL, versions.old)


def legacy_assets(root, monkeypatch):
    from flybrain import visual_assets
    directory = root/'build/visual/anatomy'; directory.mkdir(parents=True)
    table = neurons().drop(columns='entity_id'); table.to_parquet(root/'build/neurons.parquet', index=False)
    atomic_write_json(root/'build/build_summary.json', {'output_hashes': {'neurons.parquet': checksum(root/'build/neurons.parquet')}})
    np.asarray([[-.5, -1, -.5], [.5, 1, .5], [0, 0, 0]], dtype='<f4').tofile(directory/'positions.bin')
    np.asarray([2, 1, 1], dtype='u1').tofile(directory/'groups.bin')
    np.asarray([0, 1], dtype='<u4').tofile(directory/'visible_indices.bin')
    metadata = {'neuron_count': 3, 'analysis': {'receptors': [{'index': 0, 'root_id': str(ROOT_IDS[0])}]},
                'regions': [{'key': 'AL_L', 'name': 'Antennal lobe left'}]}
    monkeypatch.setattr(visual_assets, 'prepare_anatomy', lambda root: metadata)
    return get_model_manifest(root, 'flywire-783')['model_hash'], metadata


def test_flywire_versioned_assets_preserve_original_optics_atlas_and_large_ids(tmp_path, monkeypatch):
    digest, original = legacy_assets(tmp_path, monkeypatch)
    metadata = prepare_model_anatomy(tmp_path, 'flywire-783', digest)
    directory = model_anatomy_directory(tmp_path, 'flywire-783', digest)
    assert metadata['analysis'] == original['analysis'] and metadata['regions'] == original['regions']
    for name in ['positions.bin', 'groups.bin', 'visible_indices.bin']:
        assert (directory/name).read_bytes() == (tmp_path/'build/visual/anatomy'/name).read_bytes()
    rows = json.loads((directory/'identities.json').read_text())
    assert [r['root_id'] for r in rows] == list(map(str, ROOT_IDS))
    assert [r['entity_id'] for r in rows] == [f'flywire:783:{i}' for i in ROOT_IDS]
    with pytest.raises(ValueError, match='Historical FlyWire source identity differs'):
        prepare_model_anatomy(tmp_path, 'flywire-783', '0'*64)


def test_flywire_uncached_anatomy_rejects_changed_declared_source_table(tmp_path, monkeypatch):
    digest, _ = legacy_assets(tmp_path, monkeypatch)
    altered = neurons().drop(columns='entity_id'); altered.loc[0, 'root_id'] = 123
    altered.to_parquet(tmp_path/'build/neurons.parquet', index=False)
    with pytest.raises(ValueError, match='(?i)(changed|checksum|hash|identity)'):
        prepare_model_anatomy(tmp_path, 'flywire-783', digest)


def test_valid_cached_historical_anatomy_does_not_regenerate_from_changed_table(versions):
    v = versions
    metadata = prepare_model_anatomy(v.root, MODEL, v.old)
    directory = model_anatomy_directory(v.root, MODEL, v.old)
    saved = {p.name: p.read_bytes() for p in directory.iterdir()}
    v.new_table.to_parquet(v.root/'build/model-versions'/v.old/'neurons.parquet', index=False)
    # Existing historical display assets still describe the verified original
    # table. They need not be rebuilt from a now-incompatible executable table.
    assert prepare_model_anatomy(v.root, MODEL, v.old) == metadata
    assert saved == {p.name: p.read_bytes() for p in directory.iterdir()}
