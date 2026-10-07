import hashlib
import json
import zipfile

import pytest

from flybrain.workspace_sessions import save_workspace_session, session_archive_path


def payload():
    return {'notes': {'schema_version': 1, 'session_title': 'Motion response', 'notes': [
        {'id': 'note-a', 'text': 'Voltage rises.\nKeep my exact words & symbols: αβ.', 'anchor': {'run_id': 'run-1', 'panel_id': 'brain', 'panel_title': 'Brain', 'time_ms': 20, 'rect': {'x': .1, 'y': .2, 'width': .3, 'height': .4}}},
        {'id': 'note-b', 'text': 'Compare this point with the earlier response.', 'anchor': {'run_id': 'run-1', 'panel_id': 'brain', 'panel_title': 'Brain', 'time_ms': 40}},
    ]}, 'workspace': {'run_id': 'run-1', 'time_ms': 40, 'draft': {'duration_ms': 100}}}


def test_archive_preserves_notes_recording_and_linked_summary(tmp_path):
    run = tmp_path/'runs/run-1'; run.mkdir(parents=True)
    values = b'original scientific data\x00' * 10000
    (run/'raw.bin').write_bytes(values)
    (run/'visual_summary.json').write_text('{"partial":false}')
    original = payload()
    result = save_workspace_session(tmp_path, original)
    assert result['bytes'] < len(values)
    with zipfile.ZipFile(result['path']) as archive:
        assert json.loads(archive.read('notes.json')) == original['notes']
        assert json.loads(archive.read('workspace.json')) == original['workspace']
        assert archive.read('recordings/run-1/raw.bin') == values
        assert '[Voltage rises.' in archive.read('Summary.md').decode()
        assert 'Notes.md#note-note-a' in archive.read('Summary.md').decode()
        links = json.loads(archive.read('connections.json'))
        assert links[0]['from'] == 'note-a' and links[0]['to'] == 'note-b'
        manifest = json.loads(archive.read('manifest.json'))
        entry = next(item for item in manifest['files'] if item['path'].endswith('raw.bin'))
        assert entry['sha256'] == hashlib.sha256(values).hexdigest()


@pytest.mark.parametrize('run', ['../outside', '/etc', 'bad/run', '', 'x\ny'])
def test_invalid_recording_paths_never_write_an_archive(tmp_path, run):
    value = payload(); value['workspace']['run_id'] = run
    with pytest.raises(ValueError): save_workspace_session(tmp_path, value)
    assert not (tmp_path/'build/saved-sessions').exists()


def test_external_symlink_is_rejected_and_missing_runs_are_explicit(tmp_path):
    value = payload()
    saved = save_workspace_session(tmp_path, value)
    assert saved['unavailable_recordings'] == ['run-1']
    run = tmp_path/'runs/run-1'; run.mkdir(parents=True)
    external = tmp_path/'private.txt'; external.write_text('not part of this recording')
    (run/'raw.bin').symlink_to(external)
    with pytest.raises(ValueError, match='external file link'): save_workspace_session(tmp_path, value)


def test_duplicate_ids_and_nonfinite_times_rejected(tmp_path):
    value = payload(); value['notes']['notes'][1]['id'] = 'note-a'
    with pytest.raises(ValueError, match='Duplicate'): save_workspace_session(tmp_path, value)
    value = payload(); value['notes']['notes'][0]['anchor']['time_ms'] = float('nan')
    with pytest.raises(ValueError, match='finite'): save_workspace_session(tmp_path, value)
    with pytest.raises(ValueError): session_archive_path(tmp_path, '../escape')


def test_comparison_note_includes_both_recordings_without_inventing_one_time(tmp_path):
    value = payload()
    value['notes']['notes'] = [value['notes']['notes'][0]]
    value['notes']['notes'][0]['anchor'].update(run_id=None, run_ids=['run-1', 'run-2'], time_ms=None)
    for run_id in ['run-1', 'run-2']:
        run = tmp_path / 'runs' / run_id
        run.mkdir(parents=True)
        (run / 'raw.bin').write_bytes(run_id.encode())
    saved = save_workspace_session(tmp_path, value)
    with zipfile.ZipFile(saved['path']) as archive:
        assert archive.read('recordings/run-1/raw.bin') == b'run-1'
        assert archive.read('recordings/run-2/raw.bin') == b'run-2'
        note = json.loads(archive.read('notes.json'))['notes'][0]
        assert note['anchor']['time_ms'] is None
        assert note['anchor']['run_ids'] == ['run-1', 'run-2']
        assert 'run-1 + run-2' in archive.read('Summary.md').decode()


def test_http_save_and_native_download_headers(tmp_path):
    from test_model_anatomy_versions import endpoint
    with endpoint(tmp_path) as request:
        status, response = request('/api/workspace-sessions', payload())
        assert status == 201
        saved = json.loads(response)
        status, data = request(saved['download_url'])
        assert status == 200 and data.startswith(b'PK')
