import asyncio
import base64
from copy import deepcopy
import json
from types import SimpleNamespace
import threading
from http.server import ThreadingHTTPServer
from urllib.request import urlopen, Request

import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer

from flybrain.local_agent import ResearchAgent, create_app
from flybrain.api_tools import ToolError
from flybrain.research_paper import (capture_figure, recording_evidence, load_recording,
                                    validate_report, report_pdf, study_scope, recorded_limitations)
from flybrain.visual_server import make_handler
from test_local_agent import fixtures, close, completion, call, authorized_console


def recording():
    return {'id': 'recorded-1', 'label': 'Matched visual pilot', 'model_id': 'model-1',
            'frames': {'time_ms': [0, 500, 1000], 'count': 3, 'dt_ms': 500},
            'traces': [{'name': 'T4a', 'n_recorded': 5, 'n_total': 8, 'delta_mv': [0, 2, 0]}],
            'metadata': {'seed': 17}, 'neuron_count': 8,
            'warnings': ['Stability gate failed.'], 'stats': {'clamp_count': 10}}


def paper():
    return {'title': 'Recorded visual response', 'abstract': 'A recorded pilot was inspected.',
            'methodology': {'experimental_design':'One saved simulation was inspected.', 'experimental_units':'One recording with 5 selected neurons.', 'control':'A matched baseline was recorded.'},
            'data': 'The population mean peaks at 2 mV.',
            'analysis': {'interpretation':'An excursion was recorded.','limitations':'Clamps limit interpretation.'},
            'futures': {'next_experiments':'Resolve stability.','generalization':'Test independent conditions.'}, 'evidence_ids': ['e1']}


def test_snapshot_statistics_units_and_partial_population_are_source_derived():
    result = capture_figure(recording(), 'a'*64, group='type', trace='T4a', series='delta')
    assert result['sample_count'] == 3 and result['recorded_neurons'] == 5
    assert result['total_population_neurons'] == 8
    assert result['statistics']['integral_mv_s'] == 1
    assert result['statistics']['maximum_at_ms'] == 500
    assert result['statistics']['mean_mv'] == pytest.approx(2/3)
    assert result['warnings'] == ['Stability gate failed.']
    assert base64.b64decode(result['png_base64']).startswith(b'\x89PNG')
    assert 'does not inspect pixels' in result['interpretation']


def test_report_evidence_excludes_inactive_stimulus_fields_and_preserves_controls():
    summary = recording()
    summary['stimulus'] = {'stimulus':'grating','mean_luminance':.5,'grating_waveform':'sine',
                           'apparent_flash_onset_ms':100,'electrodes':[{'voltage_mv':5}]}
    summary['metadata']['baseline'] = 'Control has electrodes OFF.'
    evidence = recording_evidence(summary, 'a'*64)
    assert 'apparent_flash_onset_ms' not in evidence['stimulus']
    assert evidence['protocol']['electrodes'] == [{'voltage_mv':5}]
    assert evidence['protocol']['baseline'] == 'Control has electrodes OFF.'
    assert 'Normalized' in evidence['units']['mean_luminance']


def test_visual_reduction_preserves_extrema_without_changing_statistics():
    summary = recording()
    summary['frames']['time_ms'] = list(range(10000))
    values = np.zeros(10000); values[2345] = 10; values[8888] = -7
    summary['traces'][0]['delta_mv'] = values.tolist()
    result = capture_figure(summary, 'a'*64, group='type', trace='T4a', series='delta')
    assert result['sample_count'] == 10000 and result['plotted_samples'] <= 2000
    assert result['statistics']['mean_mv'] == pytest.approx(.0003)
    assert result['statistics']['minimum_mv'] == -7
    assert result['statistics']['maximum_mv'] == 10
    assert result['statistics']['maximum_absolute_mv'] == 10
    summary['traces'][0]['delta_mv'][8888] = -12
    assert capture_figure(summary, 'a'*64, group='type', trace='T4a', series='delta')['statistics']['maximum_absolute_mv'] == 12


@pytest.mark.parametrize('mutation', ['nan', 'missing', 'time', 'name'])
def test_bad_or_missing_data_is_never_silently_repaired(mutation):
    summary = recording()
    if mutation == 'nan': summary['traces'][0]['delta_mv'][1] = float('nan')
    if mutation == 'missing': summary['traces'][0].pop('delta_mv')
    if mutation == 'time': summary['frames']['time_ms'][1] = 0
    if mutation == 'name': summary['traces'][0]['name'] = 'another'
    with pytest.raises(ValueError):
        capture_figure(summary, 'a'*64, group='type', trace='T4a', series='delta')


def test_report_requires_complete_sections_and_traceable_evidence():
    value = paper(); value['abstract'] = '### Summary\n**Recorded** pilot.'
    assert validate_report(value, ['e1'])['abstract'] == 'Summary\nRecorded pilot.'
    value['analysis']['interpretation'] = '*Drosophila* whole\u2011brain `trace`'
    assert validate_report(value, ['e1'])['analysis'].startswith('Drosophila whole-brain trace\n\n')
    for change in ({'evidence_ids': ['invented']}, {'evidence_ids': []}, {'data': '   '}):
        with pytest.raises(ValueError): validate_report(paper() | change, ['e1'])
    value = paper(); value['futures'].pop('generalization')
    with pytest.raises(ToolError): validate_report(value, ['e1'])
    value = paper(); value['futures']['next_experiments'] = 'The source is e1.'
    with pytest.raises(ValueError, match='Futures'): validate_report(value, ['e1'])
    for claim in ('No statistically significant deviation is observed.', 'There is no detectable response.',
                  'The input did not produce a robust, reproducible change in the mean.'):
        value = paper(); value['data'] = claim
        with pytest.raises(ValueError, match='descriptive'): validate_report(value, ['e1'])


def test_counts_and_limitations_survive_truncation_without_counting_failed_reads():
    run = {'events': [
        {'kind':'tool_start','call_id':'a','arguments':{'run_id':'r1'}},
        {'kind':'tool_result','call_id':'a','name':'cognesia_run_summary','result':{'truncated':True}},
        {'kind':'tool_start','call_id':'b','arguments':{'run_id':'r1'}},
        {'kind':'tool_result','call_id':'b','name':'cognesia_report_data','result':{'warnings':['Gate failed']}},
        {'kind':'tool_start','call_id':'c','arguments':{'run_id':'r2'}},
        {'kind':'tool_result','call_id':'c','name':'cognesia_report_data','result':{'call_failed':True,'error':'Missing run'}},
    ]}
    assert 'Saved recordings inspected: 1.' in study_scope(run)
    assert recorded_limitations(run) == ['Gate failed','Evidence call cognesia_report_data failed: Missing run']


def test_recording_endpoints_use_saved_sources_without_simulation(tmp_path):
    folder = tmp_path / 'runs/recorded-1'; folder.mkdir(parents=True)
    (folder / 'visual_summary.json').write_text(json.dumps(recording()))
    state = SimpleNamespace(root=tmp_path)
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        origin = f'http://127.0.0.1:{server.server_port}'
        headers = {'X-Cognesia-Internal': state.access.capability}
        with urlopen(Request(origin + '/api/runs/recorded-1/report-data', headers=headers)) as response:
            evidence = json.load(response)
        assert evidence['seed'] == 17 and evidence['available_traces']['type'] == ['T4a']
        assert evidence['biological_specimens_in_this_recording'] == 0
        with urlopen(Request(origin + '/api/runs/recorded-1/report-figure?group=type&trace=T4a&series=delta', headers=headers)) as response:
            figure = json.load(response)
        assert figure['source_sha256'] == evidence['source_sha256']
        assert figure['statistics']['integral_mv_s'] == 1
        with pytest.raises(ValueError): load_recording(tmp_path, '../recorded-1')
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_report_finalization_has_a_reserved_local_call_and_repairs_invalid_output():
    async def scenario():
        f = await fixtures(replies=[completion(calls=[call('e1')]), completion('Observed model evidence.')],
                           report_replies=[completion('not a structured report')])
        try:
            await f.agent.connect(); f.agent.start({'prompt': 'Inspect', 'max_calls': 1})
            await f.agent.task
            run = f.agent.run
            assert run['status'] == 'budget_reached' and run['calls_used'] == 1
            assert run['report']['evidence_ids'] == ['e1']
            assert len(f.report_history) == 2 and len(f.sent) == 1
            assert f.report_history[0]['tool_choice']['function']['name'] == 'cognesia_write_report'
            assert 'Observed model evidence.' not in json.dumps(f.report_history[0]['messages'])
            assert 'Live organisms' in run['report_scope']
        finally: await close(f)
    asyncio.run(scenario())


def test_saved_chat_can_generate_a_paper_without_repeating_any_research_calls():
    async def scenario():
        f = await fixtures(replies=[completion(calls=[call('e1')]), completion('Preserved findings')],
                           report_replies=[completion('bad'), completion('bad')])
        try:
            await f.agent.connect(); f.agent.start({'prompt':'Inspect'}); await f.agent.task
            identifier = f.agent.run['id']; original_calls = len(f.sent)
            assert f.agent.run['report'] is None
            f.agent.rewrite_report(identifier); await f.agent.task
            assert f.agent.run['report']['evidence_ids'] == ['e1']
            assert len(f.sent) == original_calls and f.agent.run['calls_used'] == original_calls
            assert f.agent.history.get(identifier)['report']
            assert len(f.report_history[-1]['tools']) == 1
        finally: await close(f)
    asyncio.run(scenario())


def test_failed_report_does_not_claim_pdf_ready_or_lose_findings():
    async def scenario():
        f = await fixtures(replies=[completion('Preserved findings')], report_replies=[completion('bad'), completion('bad')])
        try:
            await f.agent.connect(); f.agent.start({'prompt':'Inspect'}); await f.agent.task
            assert f.agent.run['answer'] == 'Preserved findings'
            assert f.agent.run['report'] is None and f.agent.run['report_error']
        finally: await close(f)
    asyncio.run(scenario())


def test_pdf_download_embeds_captured_image_and_rejects_stale_study_ids():
    async def scenario():
        client, viewer = await authorized_console()
        agent = next(value for value in client.server.app.values() if isinstance(value, ResearchAgent))
        agent.run = {'id': 'study-1', 'status': 'completed', 'report': validate_report(paper(), ['e1']), 'started_at': 0,
                     'events': [], 'figures': []}
        figure = capture_figure(recording(), 'a'*64, group='type', trace='T4a', series='delta')
        metadata = agent.retain_figure(figure)
        assert 'png_base64' not in json.dumps(agent.run)
        try:
            response = await client.get('/api/report/study-1.pdf')
            data = await response.read()
            assert response.status == 200 and response.content_type == 'application/pdf'
            assert 'attachment' in response.headers['Content-Disposition']
            assert data.startswith(b'%PDF') and b'/Subtype /Image' in data
            image = await client.get(f'/api/figures/{metadata["figure_id"]}.png')
            assert image.status == 200 and image.content_type == 'image/png'
            assert (await client.get('/api/report/old-study.pdf')).status == 404
            agent.run['status'] = 'running'
            assert (await client.get('/api/report/study-1.pdf')).status == 409
        finally:
            await client.close()
            await viewer.close()
    asyncio.run(scenario())
