'use strict';
const $ = id => document.getElementById(id);
let state = null;
let initialized = false;
let busy = false;
let lastRunId = null;
let renderedEvents = 0;
let renderedReport = '';
let selectedId;
let selectedRun = null;
let renderedHistory = '';
const statusLabels = {running:'In progress', completed:'Completed', cancelled:'Stopped', interrupted:'Interrupted', failed:'Needs attention', rate_limited:'Rate limit reached', budget_reached:'Call limit reached', output_limit:'Output limit reached'};
const templates = {
  audit: 'Inspect the available models, simulation options, resource limits and chemical messengers. Summarize current scientific validation, failed gates, missing data and which studies can be run responsibly. Do not start simulations yet.',
  replicates: 'Design and run a small replicated visual-motion study after inspecting available options and validation gates. Use a master seed of 20261007 and at least three distinct independent seeds; record master seed, replicate index, seed, full options, model/source/config identity and run IDs. Use matched controls and one prespecified outcome. Run experiments serially. Preserve every failed, unstable or clamped run. Identical checkpoint-plus-seed reruns are technical replay, not independent replicates. Report variability and limitations; do not claim biological validation. If stability or resource gates prevent a meaningful study, report that before further runs.',
  chemistry: 'Inspect the chemical messenger catalog, evidence, receptor assumptions and supported simulation controls. Choose one implemented messenger for a conservative control-versus-intervention pilot; candidate messengers must remain annotations. Specify the hypothesis and outcome, use matched control seeds and independent seed pairs across replicates, and record model/config/source identity. Inspect stability before proceeding, keep failed/clamped outcomes in the record, and distinguish model assumptions from measured fly biology.'
};
function error(message) { $('error-banner').textContent = message; $('error-banner').hidden = !message; }
function selectedBudget() { return $('call-limit').value === 'custom' ? Number($('max-calls').value) : null; }
function budgetLabel(value) { return value == null ? '∞' : String(value); }
async function request(path, payload) {
  const response = await fetch(path, payload === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Cognesia-Token': state?.csrf || ''}, body: JSON.stringify(payload)});
  let data;
  try { data = await response.json(); } catch { throw new Error('The local console did not return JSON. Restart the service and reload this page.'); }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function renderEvent(event) {
  const li = document.createElement('li');
  const title = document.createElement('div'); title.className = 'event-title';
  const tag = document.createElement('span'); tag.className = 'event-kind'; tag.textContent = event.kind.replaceAll('_', ' ').toUpperCase();
  const name = document.createElement('span'); name.textContent = event.name || '';
  const time = document.createElement('time'); time.className = 'event-time'; time.textContent = new Date(event.time * 1000).toLocaleTimeString();
  title.append(tag, name, time); li.append(title);
  if (event.message) { const p = document.createElement('p'); p.className = 'event-message'; p.textContent = event.message; li.append(p); }
  for (const key of ['arguments', 'result']) if (Object.hasOwn(event, key)) {
    const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = key === 'arguments' ? 'Inspect inputs' : 'Inspect returned evidence';
    const pre = document.createElement('pre'); pre.textContent = JSON.stringify(event[key], null, 2); details.append(summary, pre); li.append(details);
  }
  $('events').append(li);
}
function displayedRun() { return selectedId && (state?.run?.id === selectedId ? state.run : selectedRun); }
function renderHistory() {
  const chats = [...(state.history || [])];
  if (state.run && !chats.some(chat => chat.id === state.run.id)) chats.unshift({id:state.run.id, title:state.run.prompt, status:state.run.status, started_at:state.run.started_at});
  const key = JSON.stringify([selectedId, chats]);
  if (renderedHistory === key) return;
  renderedHistory = key;
  $('history-list').replaceChildren();
  $('history-count').textContent = String(chats.length);
  $('history-empty').hidden = chats.length > 0;
  for (const chat of chats) {
    const li = document.createElement('li'), button = document.createElement('button');
    button.className = 'chat-entry'; button.setAttribute('aria-current', String(chat.id === selectedId));
    const title = document.createElement('span'); title.className = 'chat-title'; title.textContent = chat.title;
    const meta = document.createElement('span'); meta.className = 'chat-meta';
    meta.textContent = `${new Date(chat.started_at * 1000).toLocaleDateString(undefined, {month:'short',day:'numeric'})} · ${statusLabels[chat.status] || chat.status}`;
    if (chat.status === 'running') button.classList.add('is-running');
    button.append(title, meta); button.title = chat.title;
    button.addEventListener('click', () => openChat(chat.id)); li.append(button); $('history-list').append(li);
  }
}
async function openChat(id) {
  selectedId = id; selectedRun = null; error(''); render(state);
  try {
    const run = state.run?.id === id ? state.run : await request(`/api/history/${encodeURIComponent(id)}`);
    if (selectedId !== id) return;
    selectedRun = run; render(state);
    $('workspace-scroll').scrollTop = 0;
  } catch (e) { if (selectedId === id) error(e.message); }
}
function newChat(clear = true) {
  if (!state) return;
  selectedId = null; selectedRun = null;
  if (clear) $('prompt').value = '';
  error(''); render(state); $('prompt').focus(); $('workspace-scroll').scrollTop = 0;
}
function render(next) {
  state = next;
  if (!initialized) {
    for (const [id, key] of [['model-url','model_url'], ['model-id','model_id'], ['gateway-url','gateway_url'], ['mode','mode']]) $(id).value = state[key];
    $('gateway-fields').hidden = state.mode !== 'gateway';
    $('workbench-link').href = state.viewer_url;
    $('llama-executable').value = state.launcher_defaults?.executable || '';
    $('model-file').value = state.launcher_defaults?.model_file || '';
    $('connection-panel').open = !state.connected;
    initialized = true;
  }
  $('connection-state').textContent = state.connection_message;
  $('connection-indicator').textContent = state.connected ? 'Connected' : 'Offline';
  $('connection-indicator').setAttribute('data-state', state.connected ? 'connected' : 'offline');
  $('connection-indicator').title = state.connection_message || '';
  $('budget-summary').textContent = `${selectedBudget() === null ? 'Unlimited calls' : `${budgetLabel(selectedBudget())} calls`} · ${Number($('max-tokens').value).toLocaleString()} tokens`;
  const readiness = state.launcher_readiness;
  $('launcher-readiness').textContent = readiness && (state.launcher_defaults?.executable || state.launcher_defaults?.model_file)
    ? `${readiness.executable_present ? 'Runtime found' : 'Runtime not found'} · ${readiness.model_file_present ? 'Model file present' : 'Model file not found'}. File presence does not verify complete weights or a loaded model.`
    : '';
  $('api-password').placeholder = state.password_present ? 'Password retained in server memory; enter to replace' : 'Held in server memory only';
  const run = displayedRun(), running = run?.status === 'running', active = state.run?.status === 'running';
  renderHistory();
  $('history-error').textContent = state.history_error || ''; $('history-error').hidden = !state.history_error;
  $('study-editor').hidden = selectedId !== null;
  $('active-chat-note').hidden = !active;
  $('saved-prompt').hidden = !run;
  $('saved-prompt-text').textContent = run?.prompt || '';
  $('study-context').textContent = selectedId === null ? 'NEW CHAT' : 'SAVED STUDY';
  $('start').disabled = busy || active || !state.connected || selectedId !== null;
  $('connect').disabled = busy || active;
  $('launch-model').disabled = busy || active || state.managed_model_running;
  $('unload-model').disabled = busy || !state.managed_model_running;
  $('stop').disabled = !active;
  $('stop').textContent = active && !running ? 'Stop running study' : 'Stop agent';
  $('export').disabled = !run;
  $('download-pdf').disabled = !run?.report || running;
  $('generate-paper').hidden = !run || Boolean(run.report) || running;
  $('generate-paper').disabled = busy || active || !state.connected;
  $('generate-paper').textContent = run?.report_error ? 'Retry paper' : 'Generate paper';
  window.dispatchEvent(new Event('cognesia-agent-updated'));
  if (!run) {
    $('run-status').textContent = selectedId ? 'Opening saved chat…' : 'Ready when you are';
    $('answer').textContent = 'Your paper will appear here with Abstract, Methodology, Data, Analysis and Futures. Start a study after connecting the model.';
    $('answer').classList.add('empty');
    $('answer').classList.remove('has-paper');
    $('report-error').hidden = true; renderedReport = '';
    $('calls-used').textContent = `0 / ${budgetLabel(selectedBudget())}`;
    $('events').replaceChildren(); $('trace-count').textContent = '0 events'; $('trace-empty').hidden = false;
    lastRunId = null; renderedEvents = 0;
    return;
  }
  $('run-status').textContent = running && run.phase === 'report' ? 'Writing the research paper…' : statusLabels[run.status] || run.status;
  $('calls-used').replaceChildren(document.createTextNode(`${run.calls_used} `));
  const max = document.createElement('span'); max.textContent = `/ ${budgetLabel(run.max_calls)}`; $('calls-used').append(max);
  $('answer').classList.toggle('empty', !run.report && !run.answer && !run.error);
  $('answer').classList.toggle('has-paper', Boolean(run.report));
  $('report-error').textContent = run.report_error || ''; $('report-error').hidden = !run.report_error;
  if (run.report) {
    const key = run.id + JSON.stringify(run.report);
    if (renderedReport !== key) { $('answer').replaceChildren(window.CognesiaReport.render(run)); renderedReport = key; }
  } else {
    renderedReport = '';
    $('answer').textContent = running && run.phase === 'report' ? 'Writing your paper with Abstract, Methodology, Data, Analysis and Futures…'
      : run.answer || run.error || (running ? 'The agent is gathering evidence for your paper. Tool calls are visible below.' : 'No final answer was produced. Inspect the trace for the last completed step.');
  }
  if (lastRunId !== run.id) { lastRunId = run.id; renderedEvents = 0; $('events').replaceChildren(); }
  for (const event of run.events.slice(renderedEvents)) renderEvent(event);
  renderedEvents = run.events.length;
  $('trace-count').textContent = `${renderedEvents} events`;
  $('trace-empty').hidden = renderedEvents > 0;
}
async function refresh() {
  const next = await request('/api/state');
  if (selectedId === undefined) {
    selectedId = next.run?.id || next.history?.[0]?.id || null;
    render(next);
    if (selectedId && selectedId !== next.run?.id) await openChat(selectedId);
  } else render(next);
}
async function act(action) {
  if (busy) return;
  busy = true; error(''); if (state) render(state);
  try { await action(); await refresh(); } catch (e) { error(e.message); } finally { busy = false; if (state) render(state); }
}
$('mode').addEventListener('change', () => { $('gateway-fields').hidden = $('mode').value !== 'gateway'; });
$('call-limit').addEventListener('change', () => {
  const custom = $('call-limit').value === 'custom';
  $('max-calls-field').hidden = !custom;
  $('call-limit-hint').textContent = custom ? 'The agent writes its conclusion when the call limit is reached.' : 'Unlimited calls until the study finishes or you stop it.';
  if (state) render(state);
});
$('max-calls').addEventListener('input', () => { if (state) render(state); });
$('max-tokens').addEventListener('change', () => { if (state) render(state); });
$('connect').addEventListener('click', () => act(async () => {
  const payload = {mode:$('mode').value, model_url:$('model-url').value.trim(), model_id:$('model-id').value.trim(), gateway_url:$('gateway-url').value.trim()};
  if ($('api-password').value) payload.api_password = $('api-password').value;
  render(await request('/api/configure', payload));
  $('api-password').value = '';
  $('connection-state').textContent = 'Verifying GPT-OSS-20B structured tool calling…';
  render(await request('/api/connect', {}));
  $('connection-panel').open = false;
}));
$('new-chat').addEventListener('click', () => newChat());
window.addEventListener('cognesia-show-editor', () => { if (selectedId !== null) newChat(false); });
$('start').addEventListener('click', () => act(async () => {
  const max_calls = selectedBudget();
  if (max_calls !== null && (!Number.isSafeInteger(max_calls) || max_calls < 1)) throw new Error('Enter a positive whole number of calls, or choose Unlimited.');
  const run = await request('/api/run', {prompt:$('prompt').value, max_calls, max_tokens:Number($('max-tokens').value)});
  selectedId = run.id; selectedRun = run;
}));
$('stop').addEventListener('click', async () => { try { await request('/api/stop', {}); await refresh(); } catch (e) { error(e.message); } });
$('generate-paper').addEventListener('click', () => act(async () => {
  const run = displayedRun(); if (!run) return;
  const result = await request('/api/report', {study_id:run.id});
  selectedId = result.id; selectedRun = result;
}));
$('launch-model').addEventListener('click', () => act(async () => {
  render(await request('/api/launch-model', {executable:$('llama-executable').value, model_file:$('model-file').value, context_size:Number($('context-size').value), threads:Number($('model-threads').value)}));
  $('model-url').value = state.model_url; $('model-id').value = state.model_id;
}));
$('unload-model').addEventListener('click', () => act(async () => { render(await request('/api/unload-model', {})); }));
for (const button of document.querySelectorAll('[data-template]')) button.addEventListener('click', () => { newChat(false); $('prompt').value = templates[button.dataset.template]; });
$('export').addEventListener('click', () => {
  const run = displayedRun(); if (!run) return;
  const artifact = {schema_version:1, model_id:run.model_id || state.model_id, model_url:run.model_url || state.model_url, viewer_url:run.viewer_url || state.viewer_url, exported_at:new Date().toISOString(), study:run};
  const url = URL.createObjectURL(new Blob([JSON.stringify(artifact, null, 2)], {type:'application/json'}));
  const a = document.createElement('a'); a.href = url; a.download = `cognesia-study-${run.id}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$('download-pdf').addEventListener('click', () => {
  const run = displayedRun(); if (!run?.report || run.status === 'running') return;
  const a = document.createElement('a');
  a.href = `/api/report/${encodeURIComponent(run.id)}.pdf`;
  a.download = `cognesia-report-${run.id}.pdf`;
  a.click();
});
async function poll() {
  try { await refresh(); } catch (e) { error('The local console is unavailable. Start “flybrain agent --open” or “python -m flybrain.local_agent --open” and reload.'); }
  setTimeout(poll, 1200);
}
poll();
