from pathlib import Path
from types import SimpleNamespace
import json

import numpy as np
import pandas as pd
import pytest

from flybrain.legacy_protocol_session import _run


class Runtime:
    """Transport fixture: each advance writes real deterministic spike bytes."""
    instances = []

    def __init__(self, root, seed):
        self.root, self.seed = Path(root), seed
        self.session_dir = self.root / 'runs/neuromod/fake'
        self.session_dir.mkdir(parents=True)
        self.neurons = pd.DataFrame({'root_id': [101, 104], 'cell_type': ['KC_a', 'MBON1'],
                                     'super_class': ['central', 'central'], 'pos_x': [10, 20], 'pos_y': [2, 3], 'pos_z': [1, 2]})
        self.core = SimpleNamespace(model_indices=np.array([0, 3]))
        self.cells = self.neurons.cell_type.to_numpy()
        self.mapping = SimpleNamespace(mb_assignment=np.array([0, 0, 0, 1]), names=['g1', 'g4'])
        self.plasticity = SimpleNamespace(weights=np.array([1., 2.]))
        self.config_hash, self.closed = 'fixture-config', False
        self.instances.append(self)
        self.reset(seed)

    def reset(self, seed):
        for handle in getattr(self, '_spike_files', []):
            handle.close()
        self.engine = SimpleNamespace(v=np.array([-52., -51.]), step=0, dt=.1)
        self.controls = {'plasticity.enabled': True}
        self.events, self.advances = [], []
        self._spike_files = [(self.session_dir / name).open('wb') for name in ['spike_indices.i32', 'spike_steps.i64']]

    def warmup(self):
        self.reset(self.seed)

    @property
    def t_sim_ms(self):
        return self.engine.step * .1

    def advance(self, amount):
        self.advances.append(amount)
        self.engine.step += amount * 10
        self.engine.v += amount * .01
        self._spike_files[0].write(np.array([1], np.int32).tobytes())
        self._spike_files[1].write(np.array([self.engine.step], np.int64).tobytes())

    def control(self, key, value):
        self.controls[key] = value
        self.events.append((self.t_sim_ms, key, value))

    def snapshot(self):
        return {'t_sim_ms': self.t_sim_ms, 'controls': dict(self.controls), 'concentrations_au': [[.2]], 'field_clamps': 0, 'weight_clamps': 0, 'voltage_out_of_bounds': 0}

    def metadata(self):
        return {'warnings': [], 'species': ['DA'], 'compartments': ['g1']}

    def export(self, path):
        Path(path).write_bytes(b'fixture archive')
        return path

    @property
    def all_spike_indices(self):
        self._spike_files[0].flush()
        return np.fromfile(self.session_dir / 'spike_indices.i32', np.int32)

    @property
    def all_spike_steps(self):
        self._spike_files[1].flush()
        return np.fromfile(self.session_dir / 'spike_steps.i64', np.int64)

    def digests(self):
        return {'spikes': 'fixture'}

    def close(self):
        self.closed = True
        for handle in self._spike_files:
            handle.close()


def protocol(duration=43):
    return {'name': 'transport fixture', 'blocks': [{'kind': 'rest', 't_ms': 0, 'dur_ms': duration}]}


def test_finite_session_preserves_raw_frames_and_index_mapping(tmp_path):
    frames = []
    summary = _run(tmp_path, protocol(), Runtime, frame=frames.append)
    runtime = Runtime.instances[-1]
    assert runtime.advances == [20, 20, 3] and runtime.t_sim_ms == 43
    assert summary['completed'] and not summary['baseline_available'] and runtime.closed
    assert summary['frames']['time_ms'] == [0, 20, 40, 43]
    assert 'delta_url' not in summary['activity'] and 'baseline_url' not in summary['activity']
    np.testing.assert_array_equal(frames[-1]['parent_indices'], [0, 3])
    np.testing.assert_array_equal(frames[-1]['spike_parent_indices'], [3])
    np.testing.assert_array_equal(frames[0]['voltage_mv'], [-52, -51])
    directory = tmp_path / 'runs' / summary['id']
    data = np.fromfile(directory / 'raw.bin', np.float32).reshape(4, 2)
    np.testing.assert_array_equal(data[-1], frames[-1]['voltage_mv'])
    assert json.loads((directory / 'visual_summary.json').read_text())['status'] == 'complete'
    assert summary['anatomy']['neuron_count'] == 2


def test_pause_single_step_resume_and_checkpoint_rejection(tmp_path):
    updates, polls = [], 0
    def poll():
        nonlocal polls
        polls += 1
        if polls == 1:
            return [{'action': 'pause'}, {'action': 'checkpoint', 'request_id': 'x'}, {'action': 'step', 'duration_ms': 1}]
        if polls == 2:
            assert Runtime.instances[-1].t_sim_ms == 1
            return {'action': 'resume'}
    result = _run(tmp_path, protocol(22), Runtime, updates.append, control=poll)
    assert result['frames']['time_ms'] == [0, 1, 21, 22]
    assert any(u.get('action') == 'step_complete' and u['status'] == 'paused' for u in updates)
    rejected = next(u for u in updates if u.get('request_id') == 'x')
    assert rejected['status'] == 'rejected' and 'complete restart states' in rejected['error']


def test_stop_saves_partial_and_never_advances_after_acknowledgement(tmp_path):
    polls = 0
    def poll():
        nonlocal polls
        polls += 1
        return {'action': 'stop'} if polls == 2 else None
    result = _run(tmp_path, protocol(100), Runtime, control=poll)
    assert result['status'] == 'stopped' and result['partial'] and not result['completed']
    assert Runtime.instances[-1].advances == [20]
    assert result['frames']['time_ms'] == [0, 20]


def test_original_test_freeze_and_restore_reach_exact_endpoint(tmp_path):
    doc = {'blocks': [{'kind': 'test', 't_ms': 0, 'dur_ms': 3, 'iti_ms': 1, 'odours': ['OCT', 'MCH']}]}
    result = _run(tmp_path, doc, Runtime)
    runtime = Runtime.instances[-1]
    assert runtime.t_sim_ms == 7
    assert runtime.controls['plasticity.enabled'] is True
    assert runtime.events[0] == (0, 'plasticity.enabled', False)
    assert result['metadata']['frozen_test_readouts'][0]['weights_unchanged']


def test_source_gate_failure_preserves_requested_protocol(tmp_path):
    def unavailable(*args, **kwargs):
        raise ValueError('Source integrity gate failed')
    with pytest.raises(ValueError, match='Source integrity'):
        _run(tmp_path, protocol(), unavailable)
    directory = next((tmp_path / 'runs').iterdir())
    assert (directory / 'protocol.yaml').exists()
    assert json.loads((directory / 'protocol_failure.json').read_text())['status'] == 'failed'
