import asyncio
from copy import deepcopy
import json
import os

from aiohttp.test_utils import TestClient, TestServer

from flybrain.local_agent import ResearchAgent, create_app
from flybrain.research_history import ResearchHistory
from flybrain.research_paper import capture_figure, validate_report
from test_research_paper import recording, paper
from test_local_agent import authorized_console


def saved_study(identifier='saved-1'):
    return {'id': identifier, 'prompt': 'Inspect a recorded experiment', 'status': 'completed',
            'started_at': 1, 'finished_at': 2, 'max_calls': 2, 'calls_used': 2,
            'events': [], 'answer': 'The observed trace.', 'report': validate_report(paper(), ['e1']),
            'figures': [], 'model_id': 'gpt-oss-20b', 'mode': 'owner'}


def test_restart_restores_selected_chat_pdf_and_figures_without_replacing_active_study(tmp_path):
    async def scenario():
        first = ResearchAgent(history_dir=tmp_path)
        first.run = saved_study()
        metadata = first.retain_figure(capture_figure(recording(), 'a'*64, group='type', trace='T4a', series='delta'))
        original_png = first.figures[metadata['figure_id']]['png']
        first.persist()
        assert os.stat(tmp_path / 'saved-1/study.json').st_mode & 0o777 == 0o600
        restarted = ResearchAgent(history_dir=tmp_path)
        restarted.run = saved_study('active-2') | {'status':'running', 'report':None, 'started_at':3}
        restarted.persist()
        assert len(restarted.state()['history']) == 2
        client, viewer = await authorized_console(restarted)
        try:
            old = await (await client.get('/api/history/saved-1')).json()
            assert old['prompt'] == first.run['prompt'] and old['report'] == first.run['report']
            pdf = await client.get('/api/report/saved-1.pdf')
            assert pdf.status == 200 and b'/Subtype /Image' in await pdf.read()
            image = await client.get(f'/api/studies/saved-1/figures/{metadata["figure_id"]}.png')
            assert await image.read() == original_png
            assert restarted.run['id'] == 'active-2' and restarted.run['status'] == 'running'
            assert (await client.get('/api/history/unknown')).status == 404
            assert restarted.history.get('../saved-1') is None
            (tmp_path / 'saved-1' / (metadata['figure_id'] + '.png')).unlink()
            assert (await client.get('/api/report/saved-1.pdf')).status == 422
        finally:
            await client.close()
            await viewer.close()
    asyncio.run(scenario())


def test_interrupted_chat_is_recovered_without_resuming_tools_and_bad_file_is_preserved(tmp_path):
    history = ResearchHistory(tmp_path)
    history.save(saved_study() | {'status': 'running', 'report':None})
    bad = tmp_path / 'broken'; bad.mkdir(); (bad / 'study.json').write_text('{partial')
    recovered = ResearchAgent(history_dir=tmp_path)
    run = recovered.saved_run('saved-1')
    assert run['status'] == 'interrupted'
    assert 'restarted' in run['events'][-1]['message']
    assert recovered.task is None and recovered.run is None
    assert recovered.history_error and (bad / 'study.json').read_text() == '{partial'
    again = ResearchHistory(tmp_path)
    assert len(again.get('saved-1')['events']) == 1


def test_persistence_redacts_credentials_and_does_not_save_connection_state(tmp_path):
    agent = ResearchAgent(history_dir=tmp_path)
    agent.api_password = 'private-workspace-secret'
    agent.model_api_key = 'private-model-secret'
    agent.run = saved_study() | {'prompt': 'Inspect private-workspace-secret', 'answer':'private-model-secret'}
    agent.event('error', message='An endpoint echoed private-workspace-secret')
    persisted = (tmp_path / 'saved-1/study.json').read_text()
    assert 'private-workspace-secret' not in persisted and 'private-model-secret' not in persisted
    assert agent.csrf not in persisted and 'api_password' not in persisted
    assert '[credential redacted]' in persisted


def test_unlimited_chat_above_old_history_size_ceiling_can_reopen(tmp_path):
    history = ResearchHistory(tmp_path)
    run = saved_study() | {'max_calls': None, 'calls_used': 900,
        'events': [{'kind':'tool_result','call_id':f'e{i}', 'result':{'data':'x'*10000}} for i in range(900)]}
    history.save(run)
    assert (tmp_path / 'saved-1/study.json').stat().st_size > 8 * 1024 * 1024
    restored = ResearchHistory(tmp_path).get('saved-1')
    assert restored['max_calls'] is None and len(restored['events']) == 900


def test_starting_next_chat_and_stopping_it_keep_the_original(tmp_path):
    async def scenario():
        agent = ResearchAgent(history_dir=tmp_path)
        agent.run = saved_study()
        original = deepcopy(agent.run)
        agent.connected = True
        async def waiting(_):
            await asyncio.Future()
        agent._run = waiting
        second = agent.start({'prompt': 'A new question'})
        await agent.stop()
        restored = ResearchHistory(tmp_path)
        assert restored.get(original['id']) == original
        assert restored.get(second['id'])['status'] == 'cancelled'
        assert len(restored.summaries()) == 2
    asyncio.run(scenario())
