"""Runtime integration uses synthetic identities, never biological validation."""
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest
from scipy import sparse
import yaml

from flybrain.config import parameters
from flybrain.fetch import checksum
from flybrain.model_registry import _freeze_model, load_model_network, stable_hash
from flybrain.provider_chemistry import build_model_chemistry
from flybrain.visual_experiment import (normalize_provider_neuromod,
    run_visual_experiment, runtime_input_hashes, assert_sources_unchanged)
from flybrain.wholebrain_neuromod import WholeBrainNeuromodEngine

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = 'paralimbo-v0-1-0'


def installed_provider(root):
    """Install only provider artifacts and user configuration, with no FlyWire."""
    for name in ('parameters.yaml', 'visual_parameters.yaml', 'neuromod.yaml', 'receptors.csv'):
        destination = root/'config'/name
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT/'config'/name, destination)
    path = root/'config/parameters.yaml'
    document = yaml.safe_load(path.read_text())
    document['parameters']['pre_equilibration']['value'] = 100.
    path.write_text(yaml.safe_dump(document))
    neurons = pd.DataFrame({
        'root_id': np.arange(9007199254740993, 9007199254740999, dtype=np.int64),
        'cell_type': ['NO-fixture', 'KC-fixture', 'LN-fixture', 'CSD-fixture', 'R1-6', 'LN-negative'],
        'cell_class': ['central', 'Kenyon_Cell', 'ALLN', 'central', 'photoreceptor_neuron', 'ALLN'],
        'native_cell_class': ['central', 'kenyon_cell', 'antennal_lobe_local_neuron', 'central', 'photoreceptor_neuron', 'antennal_lobe_local_neuron'],
        'known_nt': ['nitric oxide', 'acetylcholine;snpf', 'gaba', 'serotonin', 'histamine', 'gaba-negative'],
        'super_class': ['central'] * 4 + ['optic', 'central'],
        'root_region': ['central_brain'] * 4 + ['optic_lobe', 'central_brain'],
        'side': ['left'] * 6, 'is_graded': [False] * 4 + [True, False],
        'mode': ['spiking'] * 4 + ['graded', 'spiking'],
        'fafb_match': ['', '', '', '', '101', ''],
        'status': ['', '', '', '', 'FAFB_MATCH_MANUALLY_CHECKED', ''],
        'pos_x': np.arange(6.), 'pos_y': np.arange(6.), 'pos_z': np.arange(6.),
    })
    neurons['entity_id'] = 'banc:888:' + neurons.root_id.astype(str)
    folder = root/'build/models'/MODEL_ID
    folder.mkdir(parents=True)
    neurons.to_parquet(folder/'neurons.parquet', index=False)
    matrices = {'graded': sparse.csr_matrix(([1.], ([1], [4])), shape=(6, 6)),
                'spiking': sparse.csr_matrix(([-1.], ([0], [2])), shape=(6, 6))}
    for name, matrix in matrices.items():
        for part in ('data', 'indices', 'indptr'):
            np.save(folder/f'{name}_{part}.npy', getattr(matrix, part))
    files = sorted(folder.iterdir())
    manifest = {'schema_version': 1, 'id': MODEL_ID, 'neurons': len(neurons), 'edges': 2,
                'optical_mapping_supported': False, 'warnings': ['Synthetic test fixture'],
                'output_hashes': {p.name: checksum(p) for p in files}}
    manifest['model_hash'] = stable_hash(manifest)
    (folder/'manifest.json').write_text(json.dumps(manifest))
    _freeze_model(root, folder, manifest)
    return load_model_network(root, MODEL_ID)


def test_provider_chemistry_defaults_preserve_explicit_failures():
    assert not normalize_provider_neuromod({'enabled': True}, MODEL_ID)['plasticity_enabled']
    assert normalize_provider_neuromod({'enabled': True}, 'flywire-783')['plasticity_enabled']
    with pytest.raises(ValueError, match='plasticity-compartment transfer'):
        normalize_provider_neuromod({'enabled': True, 'plasticity_enabled': True}, MODEL_ID)


def test_runtime_code_hashes_use_stable_names_across_install_locations(tmp_path):
    names = ('src/flybrain/visual_experiment.py', 'src/flybrain/provider_chemistry.py')
    installed = runtime_input_hashes(tmp_path, names)
    assert installed == runtime_input_hashes(ROOT, names)
    assert set(installed) == set(names)
    assert_sources_unchanged(tmp_path, installed)


def test_server_options_apply_provider_defaults(tmp_path):
    from flybrain.visual_server import VisualState
    installed_provider(tmp_path)
    request = {'model_id': MODEL_ID, 'duration_ms': 300, 'neuromod': {'enabled': True}}
    assert not VisualState.options(request, tmp_path)['neuromod']['plasticity_enabled']
    request['neuromod']['plasticity_enabled'] = True
    with pytest.raises(ValueError, match='plasticity-compartment transfer'):
        VisualState.options(request, tmp_path)


def test_installed_provider_sources_and_alln_receptors(tmp_path):
    network = installed_provider(tmp_path)
    options = normalize_provider_neuromod({'enabled': True, 'chemical_levels': {'5HT': 1.}}, MODEL_ID)
    engine = WholeBrainNeuromodEngine(network['graded'], network['spiking'],
        network['neurons'].is_graded.to_numpy(), parameters(tmp_path), threads=1,
        root=tmp_path, neurons=network['neurons'], neuromod=options,
        chemistry_factory=lambda instance: build_model_chemistry(tmp_path, instance, network, options))
    chemistry = engine.chemistry
    counts = chemistry.field.projection.metadata['source_counts_model']
    assert counts['NO'] == counts['sNPF'] == counts['5HT'] == counts['ACh'] == 1
    # This verifies configured target resolution, not measured receptor expression.
    np.testing.assert_allclose(chemistry.effects.gain, [1., 1., 1.2, 1., 1., 1.])
    result = engine.run(3., record_indices=np.arange(6))
    assert np.isfinite(result['final_v']).all()


@pytest.mark.parametrize('optical_donor', [False, True])
def test_real_visual_run_from_installed_provider_without_flywire(tmp_path, optical_donor):
    installed_provider(tmp_path)
    optional = ('build/visual/eye_assignments.parquet', 'build/visual/eye_columns.csv')
    if optical_donor:
        (tmp_path/'build/visual').mkdir()
        pd.DataFrame({'root_id': [101], 'column_index': [0]}).to_parquet(tmp_path/optional[0], index=False)
        pd.DataFrame({'column_index': [0], 'column_id': [1], 'hemisphere': ['left'],
            'p': [0.], 'q': [0.], 'x': [0.], 'y': [0.], 'anchor_root_id': [101]}).to_csv(tmp_path/optional[1], index=False)
    result = run_visual_experiment(tmp_path, {'model_id': MODEL_ID,
        'stimulus': 'dark', 'duration_ms': 300, 'threads': 1,
        'neuromod': {'enabled': True, 'chemical_levels': {'5HT': 1.}}})
    assert result['model_id'] == MODEL_ID
    assert not result['metadata']['options']['neuromod']['plasticity_enabled']
    assert result['chemistry']['source_projection']['source_counts_model']['sNPF'] == 1
    assert result['metadata']['input_hashes_checked_unchanged']
    hashes = result['metadata']['input_hashes']
    assert 'config/neuromod.yaml' in hashes and 'config/receptors.csv' in hashes
    for path in ('data/raw/codex/column_assignment.csv', 'build/compartments.npz',
                 'config/endocrine_sources.csv', 'config/compartment_rules.csv'):
        assert path not in hashes and not (tmp_path/path).exists()
    assert not (tmp_path/'src').exists()
    for path in optional:
        assert (path in hashes) is optical_donor
        if optical_donor:
            assert hashes[path] == checksum(tmp_path/path)
    assert result['metadata']['eye_audit']['runtime_input_files'] == (list(optional) if optical_donor else [])
    assert result['metadata']['status'] == 'EXPERIMENTAL_UNVALIDATED'
    with np.load(result['activity_path']) as recording:
        assert np.isfinite(recording['raw_mv']).all()
        np.testing.assert_array_equal(recording['delta_mv'], 0.)


def test_models_cli_lists_clean_provider_and_reports_validation_failure(tmp_path, monkeypatch, capsys):
    from flybrain import cli, paralimbo
    installed_provider(tmp_path)
    assert cli.main(['--root', str(tmp_path), 'models', 'list']) == 0
    catalog = json.loads(capsys.readouterr().out)['models']
    entry = next(item for item in catalog if item['id'] == MODEL_ID)
    assert entry['available'] and entry['label'] == 'ParaLimbo 0.1 · BANC × FlyWire'
    monkeypatch.setattr(paralimbo, 'compile_paralimbo', lambda root: {'status': 'ASSEMBLED', 'id': MODEL_ID})
    assert cli.main(['--root', str(tmp_path), 'models', 'compile-paralimbo']) == 0
    capsys.readouterr()
    monkeypatch.setattr(paralimbo, 'validate_paralimbo', lambda root: {'status': 'FAIL'})
    assert cli.main(['--root', str(tmp_path), 'models', 'validate-paralimbo']) == 1
