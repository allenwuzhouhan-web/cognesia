from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from flybrain.protocol_adapter import import_protocol, parse_protocol


def neurons():
    return pd.DataFrame({'root_id': [101, 102, 103, 104], 'cell_type': ['PPL101', 'PPL101', 'ORN_A', 'PN_A'],
                         'known_nt': ['dopamine', 'dopamine-negative', 'acetylcholine', 'acetylcholine'],
                         'top_nt': ['dopamine'] * 4, 'super_class': ['central', 'central', 'sensory', 'central'],
                         'cell_class': ['DAN', 'DAN', 'olfactory', 'ALPN']})


def test_native_yaml_resolves_exact_indices_and_normalizes_clock():
    original = '''schema_version: 1
name: Exact electrical input
blocks:
  - kind: electrode
    t_ms: 2
    dur_ms: 5
    electrode:
      target: {kind: group, field: cell_type, values: [PPL101]}
      voltage_mv: 3
'''
    result = import_protocol(original, neurons=neurons())
    assert result['compatible'] and result['duration_ms'] == 7
    block = result['timeline']['blocks'][0]
    assert block['start_ms'] == 2 and block['duration_ms'] == 5
    assert 't_ms' not in block
    assert block['electrode']['target'] == {'kind': 'indices', 'indices': [0, 1]}
    assert result['source_audit'][0]['root_ids'] == ['101', '102']
    assert result['original_text'] == original
    assert result['original_document']['blocks'][0]['electrode']['target']['kind'] == 'group'


@pytest.mark.parametrize('document', [
    'blocks: []\nblocks: []', 'blocks: &a [*a]', 'blocks: !!python/object/apply:os.system [whoami]',
    'blocks: []\nseed: .nan', 'blocks: []\nname: 2026-01-01', {'blocks': [None]},
])
def test_import_rejects_ambiguous_or_non_json_yaml(document):
    with pytest.raises(ValueError):
        parse_protocol(document)


def test_native_unknown_fields_and_chemical_misclock_rejected():
    with pytest.raises(ValueError, match='Unsupported fields'):
        import_protocol({'schema_version': 1, 'blocks': [{'kind': 'rest', 'duration_ms': 3, 'pretend': True}]})
    with pytest.raises(ValueError, match='align'):
        import_protocol({'schema_version': 1, 'blocks': [{'kind': 'chemical', 'start_ms': .1, 'duration_ms': 2, 'species': 'DA', 'level': .1}]})


def test_native_repeated_duration_and_missing_targets():
    doc = {'schema_version': 1, 'repeat': {'count': 3, 'interval_ms': 10}, 'blocks': [{'kind': 'recording', 'start_ms': 2, 'duration_ms': 3}]}
    result = import_protocol(doc)
    assert result['duration_ms'] == 25
    assert [b['start_ms'] for b in result['compiled_events']] == [2, 12, 22]
    doc['blocks'] = [{'kind': 'electrode', 'duration_ms': 1, 'electrode': {'target': {'kind': 'indices', 'indices': [42]}}}]
    with pytest.raises(ValueError, match='indices'):
        import_protocol(doc, neurons=neurons())


def test_legacy_keeps_empirical_mismatch_and_positive_known_sources():
    mapping = SimpleNamespace(model_root_ids=np.array([104, 103, 102, 101]),
                              mb_assignment=np.array([-1, -1, 0, 1]), names=('g1', 'g4'))
    doc = {'name': 'named', 'blocks': [{'kind': 'dan_pulse', 'source': 'PPL101', 'compartment': 'g1', 't_ms': 0, 'dur_ms': 2}]}
    result = import_protocol(doc, neurons=neurons(), compartment_map=mapping)
    assert not result['compatible'] and result['timeline'] is None
    assert result['legacy_execution']['source_ready']
    assert result['source_audit'][0]['indices'] == [0]
    assert result['source_audit'][0]['observed_compartments'] == ['g4']
    assert any('nominal g1' in warning and 'g4' in warning for warning in result['warnings'])
    assert result['legacy_execution']['document'] == doc


def test_legacy_odour_requires_actual_door_mapping_and_preserves_test_freeze():
    doc = {'blocks': [{'kind': 'test', 't_ms': 10, 'dur_ms': 2, 'iti_ms': 1, 'odours': ['OCT', 'MCH']}]}
    result = import_protocol(doc, neurons=neurons())
    assert not result['legacy_execution']['source_ready']
    assert result['duration_ms'] == 15
    events = result['legacy_execution']['events']
    assert next(e for e in events if e.get('_test_boundary') == 'start')['value'] is False
    assert next(e for e in events if e.get('_test_boundary') == 'end')['value'] is None
    library = SimpleNamespace(mode='door', root_ids=np.array([103]), responses=lambda name: SimpleNamespace(metadata={'requested_name': name, 'source_commit': 'pinned'}))
    result = import_protocol(doc, neurons=neurons(), odour_library=library)
    assert result['legacy_execution']['source_ready']
    assert all(row['indices'] == [2] for row in result['source_audit'])
    assert result['timeline'] is None


def test_shipped_yaml_survives_roundtrip_and_keeps_original_controls():
    text = (Path(__file__).resolve().parents[1] / 'protocols/forward_pairing_gamma1.yaml').read_text()
    result = import_protocol(text)
    assert result['original_text'] == text
    assert result['legacy_execution']['duration_ms'] == 18000
    assert result['legacy_execution']['document']['blocks'][2]['compartment'] == 'g1'
    assert any(event['control_id'] == 'odour' and event['value'] == 'OCT' for event in result['compiled_events'])
    assert result['timeline'] is None
