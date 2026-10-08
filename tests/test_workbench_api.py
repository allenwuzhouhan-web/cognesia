import json
import struct
import socket
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from flybrain.workbench_api import interval_analysis, connectivity, inspect_neuron, json_safe
from flybrain.session_stream import websocket_frame
from flybrain.model_anatomy import write_anatomy


def test_fourier_signed_dc_phase_nyquist_and_spectrum_are_independent():
    n = 32
    phase = np.arange(n) * 2 * np.pi / n
    values = -7 + 3*np.cos(2*phase) - 4*np.sin(2*phase) + 1.5*(-1.)**np.arange(n)
    result = interval_analysis({'time_ms': (900+np.arange(n)*.5).tolist(), 'values': values.tolist(),
                                'harmonics': n//2, 'window': 'hann', 'demean': True})
    assert result['dc'] == pytest.approx(-7)
    assert result['coefficients'][1]['cos'] == pytest.approx(3)
    assert result['coefficients'][1]['sin'] == pytest.approx(-4)
    assert result['coefficients'][-1]['cos'] == pytest.approx(1.5)
    assert result['coefficients'][-1]['sin'] == 0
    assert result['time_origin_ms'] == 900
    assert result['rmse'] < 1e-12
    np.testing.assert_allclose(result['reconstruction'], values, atol=1e-12)


def test_fourier_fits_only_original_interval_and_handles_constant_signal():
    payload = {'time_ms': list(range(20)), 'values': [100]*4+[-2]*12+[900]*4,
               'start_ms': 15, 'end_ms': 4, 'harmonics': 0}
    result = interval_analysis(payload)
    assert result['sample_count'] == 12
    assert result['range'] == {'start_ms': 4, 'end_ms': 15, 'first_sample': 4, 'last_sample': 15}
    assert result['dc'] == -2 and result['rmse'] == 0
    assert result['r_squared'] is None
    with pytest.raises(ValueError, match='no resampling'):
        interval_analysis({'time_ms': [0, 1, 2.1], 'values': [1, 2, 3]})


def table():
    return pd.DataFrame({'root_id': [11, 22, 33], 'entity_id': ['fw:11', 'fw:22', 'fw:33'],
                         'cell_type': ['a', 'b', 'c'], 'super_class': ['optic', 'central', 'central'],
                         'pos_x': [0, 250, np.nan], 'pos_y': [0, 500, np.nan], 'pos_z': [0, 25, np.nan]})


def test_connectivity_direction_and_no_reference_double_counting(tmp_path):
    neurons = table()
    matrix = sparse.csr_matrix(([3., -2.], ([1, 0], [0, 1])), shape=(3, 3))
    state = SimpleNamespace(root=tmp_path, wiring={'graded': matrix, 'spiking': matrix*0, 'reference': matrix},
                            neuron_table=lambda: neurons)
    result = connectivity(state, {'source_indices': [0], 'target_indices': [1]})
    assert result['forward']['edge_count'] == 1
    assert result['forward']['synapse_count'] == 3
    assert result['forward']['edges'][0]['source_id'] == 'fw:11'
    assert result['reverse']['synapse_count'] == 2
    directory = tmp_path/'runs'/'example'; directory.mkdir(parents=True)
    (directory/'visual_summary.json').write_text(json.dumps({'model_id': 'flywire-783'}))
    neurons.iloc[[1, 0]].to_parquet(directory/'recorded_neurons.parquet')
    result = connectivity(state, {'run_id': 'example', 'source_indices': [0], 'target_indices': [1]})
    assert result['forward']['edges'][0]['source_id'] == 'fw:22'
    assert result['forward']['edges'][0]['weight'] == -2
    assert inspect_neuron(state, 0, run_id='example')['root_id'] == '22'
    with pytest.raises(ValueError, match='Invalid recording'):
        inspect_neuron(state, 0, run_id='../example')


def test_anatomy_assets_keep_row_identity_missing_positions_and_isotropic_scale(tmp_path):
    neurons = table().iloc[[1, 2, 0]].reset_index(drop=True)
    metadata = write_anatomy(neurons, tmp_path, '/api/test', model_id='test', model_hash='abc')
    assert metadata['neuron_count'] == 3 and metadata['visible_neuron_count'] == 2
    assert np.fromfile(tmp_path/'visible_indices.bin', dtype='<u4').tolist() == [0, 2]
    assert [item['root_id'] for item in json.loads((tmp_path/'identities.json').read_text())] == ['22', '33', '11']
    points = np.fromfile(tmp_path/'positions.bin', dtype='<f4').reshape(-1, 3)
    np.testing.assert_allclose(points[0]-points[2], [1, 2, 1])


@pytest.mark.parametrize('size', [0, 125, 126, 65535, 65536, 180000])
def test_websocket_encodes_all_payload_lengths(size):
    payload = b'x'*size
    frame = websocket_frame(payload)
    assert frame[0] == 0x81
    if size < 126:
        assert frame[1] == size
        offset = 2
    elif size < 65536:
        assert frame[1] == 126 and struct.unpack('!H', frame[2:4])[0] == size
        offset = 4
    else:
        assert frame[1] == 127 and struct.unpack('!Q', frame[2:10])[0] == size
        offset = 10
    assert frame[offset:] == payload


def test_nonfinite_diagnostics_are_valid_json():
    result = json_safe({'values': np.array([1, np.nan, np.inf]), 'count': np.int64(2)})
    assert json.dumps(result, allow_nan=False) == '{"values": [1.0, null, null], "count": 2}'


def test_live_stream_origin_handshake_and_disconnect_do_not_cancel_session(tmp_path):
    from flybrain.visual_server import make_handler
    state = SimpleNamespace(root=tmp_path, lock=threading.Lock(),
        jobs={'example': {'id': 'example', 'status': 'running'}},
        frames={'example': {'sequence': 3, 'voltage_mv': np.array([-52.]), 'step': 10}})
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    client = HTTPConnection('127.0.0.1', server.server_port)
    try:
        client.request('GET', '/ws/sessions/example', headers={'Origin': 'https://example.org'})
        response = client.getresponse()
        assert response.status == 403
        response.read()
        stream = socket.create_connection(('127.0.0.1', server.server_port), timeout=2)
        stream.sendall((f'GET /ws/sessions/example HTTP/1.1\r\nHost: 127.0.0.1:{server.server_port}\r\n'
                        f'X-Cognesia-Internal: {state.access.capability}\r\n'
                        'Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\n'
                        'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n').encode())
        data = b''
        while b'\r\n\r\n' not in data:
            data += stream.recv(4096)
        header, body = data.split(b'\r\n\r\n', 1)
        assert b'101 Switching Protocols' in header
        assert b's3pPLMBiTxaQ9kYGzzhZRbK+xOo=' in header
        while len(body) < 2:
            body += stream.recv(4096)
        size = body[1] & 127
        assert size < 126
        while len(body) < 2+size:
            body += stream.recv(4096)
        frame = json.loads(body[2:2+size])
        assert frame['frame']['voltage_mv'] == [-52.]
        stream.close()
        assert state.jobs['example']['status'] == 'running'
        assert state.frames['example']['step'] == 10
    finally:
        client.close(); server.shutdown(); server.server_close(); thread.join()
