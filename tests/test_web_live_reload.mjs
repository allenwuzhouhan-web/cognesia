import test from 'node:test';
import assert from 'node:assert/strict';
import {createLiveReloadController, fetchLiveReloadStatus, isEditableElement} from '../src/flybrain/web/live-reload.js';

const status = (overrides = {}) => ({enabled: true, instance_id: 'server-a', web_revision: 'web-a',
  backend_revision: 'backend-a', busy: false, pending: false, restart_pending: false, error: null, ...overrides});

function harness(options = {}) {
  let next = status(), reloads = 0, nextTimer = 0;
  const timers = new Map(), reports = [];
  const controller = createLiveReloadController({
    initialStatus: status(), readStatus: async () => {
      if (next instanceof Error) throw next;
      return next;
    },
    reload: () => { reloads++; }, onStatus: value => reports.push(value),
    schedule: (callback, delay) => { const id = ++nextTimer; timers.set(id, {callback, delay}); return id; },
    cancel: id => timers.delete(id),
    ...options,
  });
  return {controller, timers, reports, setStatus: value => { next = value; },
    get reloads() { return reloads; }, get phase() { return reports.at(-1)?.phase; }};
}

test('injected HTML baseline detects an edit before the first request completes', async () => {
  const h = harness();
  h.setStatus(status({web_revision: 'web-b'}));
  await h.controller.start();
  assert.equal(h.reloads, 1);
  assert.equal(h.timers.size, 0);
  await h.controller.checkNow();
  assert.equal(h.reloads, 1);
});

test('without injected state, first successful status becomes the baseline', async () => {
  const h = harness({initialStatus: null});
  h.setStatus(new Error('server down'));
  await h.controller.start();
  assert.equal(h.phase, 'reconnecting');
  h.setStatus(status({web_revision: 'web-b'}));
  await h.controller.checkNow();
  assert.equal(h.reloads, 0);
  h.setStatus(status({instance_id: 'server-b', web_revision: 'web-b'}));
  await h.controller.checkNow();
  assert.equal(h.reloads, 1);
});

test('pending edits and active experiments defer refresh without losing the baseline', async () => {
  const h = harness();
  await h.controller.start();
  for (const blocking of [{busy: true}, {pending: true}, {restart_pending: true}, {busy: true, pending: true}]) {
    h.setStatus(status({web_revision: 'web-b', ...blocking}));
    await h.controller.checkNow();
    assert.equal(h.reloads, 0);
    assert.equal(h.phase, blocking.busy ? 'waiting' : 'updating');
  }
  h.setStatus(status({web_revision: 'web-b'}));
  await h.controller.checkNow();
  assert.equal(h.reloads, 1);
});

test('unpublished pending edits show progress even before a new revision exists', async () => {
  const h = harness();
  h.setStatus(status({pending: true, busy: true}));
  await h.controller.start();
  assert.equal(h.phase, 'waiting');
  assert.equal(h.reloads, 0);
  h.controller.stop();
});

test('backend revision alone waits for a new server instance', async () => {
  const h = harness();
  h.setStatus(status({backend_revision: 'backend-b'}));
  await h.controller.start();
  assert.equal(h.reloads, 0);
  h.setStatus(status({backend_revision: 'backend-b', instance_id: 'server-b'}));
  await h.controller.checkNow();
  assert.equal(h.reloads, 1);
});

test('a server outage and file errors preserve the page until recovery', async () => {
  const h = harness();
  await h.controller.start();
  h.setStatus(new Error('connection refused'));
  await h.controller.checkNow();
  assert.equal(h.phase, 'reconnecting');
  h.setStatus(status({web_revision: 'web-b', error: 'SyntaxError in experiment.py'}));
  await h.controller.checkNow();
  assert.equal(h.phase, 'error');
  assert.match(h.reports.at(-1).text, /experiment.py/);
  assert.equal(h.reloads, 0);
  h.setStatus(status({web_revision: 'web-b'}));
  await h.controller.checkNow();
  assert.equal(h.reloads, 1);
});

test('editing defers reload and rechecks server safety after the field loses focus', async () => {
  let editing = true;
  const h = harness({isEditing: () => editing});
  h.setStatus(status({web_revision: 'web-b'}));
  await h.controller.start();
  assert.equal(h.phase, 'editing');
  assert.equal(h.reloads, 0);
  editing = false;
  h.setStatus(status({web_revision: 'web-b', busy: true}));
  await h.controller.checkNow();
  assert.equal(h.reloads, 0);
  h.setStatus(status({web_revision: 'web-b'}));
  await h.controller.checkNow();
  assert.equal(h.reloads, 1);
});

test('a state-saving veto keeps the page and retries safely on the next poll', async () => {
  let saved = false, attempts = 0;
  const h = harness({beforeReload: () => { attempts++; return saved; }});
  h.setStatus(status({web_revision: 'web-b'}));
  await h.controller.start();
  assert.equal(h.phase, 'blocked');
  assert.equal(h.reloads, 0);
  assert.equal(h.timers.size, 1);
  saved = true;
  await h.controller.checkNow();
  assert.equal(attempts, 2);
  assert.equal(h.reloads, 1);
  assert.equal(h.timers.size, 0);
});

test('unexpected errors saving state also preserve the page until saving succeeds', async () => {
  let fail = true;
  const h = harness({beforeReload: () => { if (fail) throw new Error('storage unavailable'); }});
  h.setStatus(status({instance_id: 'server-b'}));
  await h.controller.start();
  assert.equal(h.phase, 'blocked');
  assert.equal(h.reloads, 0);
  fail = false;
  await h.controller.checkNow();
  assert.equal(h.reloads, 1);
});

test('polls cannot overlap; stopping aborts and ignores an old response after restart', async () => {
  let requests = 0, resolveRequest, signal;
  const h = harness({readStatus: options => {
    requests++; signal = options.signal;
    return new Promise(resolve => { resolveRequest = resolve; });
  }});
  const first = h.controller.start();
  await Promise.resolve();
  assert.equal(requests, 1);
  assert.equal(h.controller.checkNow(), first);
  h.controller.stop();
  assert.equal(signal.aborted, true);
  h.controller.start();
  assert.equal(requests, 1);
  resolveRequest(status({web_revision: 'stale-revision'}));
  await first;
  assert.equal(h.reloads, 0);
  assert.equal(h.reports.length, 0);
  assert.equal(h.timers.size, 1);
  const second = h.controller.checkNow();
  await Promise.resolve();
  assert.equal(requests, 2);
  resolveRequest(status());
  await second;
  assert.equal(h.phase, 'ready');
  h.controller.stop();
  assert.equal(h.timers.size, 0);
});

test('request timeout aborts the fetch and schedules a reconnect', async () => {
  let signal;
  const h = harness({readStatus: options => new Promise((resolve, reject) => {
    signal = options.signal;
    signal.addEventListener('abort', () => reject(new Error('aborted')));
  })});
  const poll = h.controller.start();
  await Promise.resolve();
  const timeout = [...h.timers.values()].find(item => item.delay === 5000);
  assert.ok(timeout);
  timeout.callback();
  await poll;
  assert.equal(signal.aborted, true);
  assert.equal(h.phase, 'reconnecting');
  assert.equal([...h.timers.values()][0].delay, 1000);
  h.controller.stop();
});

test('disabled or invalid responses cannot trigger a reload', async () => {
  const h = harness();
  h.setStatus({enabled: false});
  await h.controller.start();
  assert.equal(h.phase, 'disabled');
  h.setStatus({enabled: true, instance_id: 'server-b'});
  await h.controller.checkNow();
  assert.equal(h.phase, 'reconnecting');
  assert.equal(h.reloads, 0);
  h.controller.stop();
});

test('status fetch bypasses caches and uses the caller abort signal', async () => {
  const abort = new AbortController();
  let request;
  const result = await fetchLiveReloadStatus({signal: abort.signal, fetchImpl: async (...args) => {
    request = args;
    return {ok: true, json: async () => status()};
  }});
  assert.equal(result.instance_id, 'server-a');
  assert.equal(request[0], '/api/live-reload');
  assert.equal(request[1].cache, 'no-store');
  assert.equal(request[1].signal, abort.signal);
  await assert.rejects(fetchLiveReloadStatus({fetchImpl: async () => ({ok: false, status: 503})}), /503/);
  await assert.rejects(fetchLiveReloadStatus({fetchImpl: async () => ({ok: true, json: async () => ({})})}), /Invalid/);
});

test('editing includes numeric drafts, selectors and rich text but excludes buttons and read-only fields', () => {
  for (const element of [{tagName: 'INPUT', type: 'number'}, {tagName: 'TEXTAREA'},
    {tagName: 'SELECT'}, {tagName: 'DIV', isContentEditable: true}]) assert.equal(isEditableElement(element), true);
  for (const element of [null, {tagName: 'BUTTON'}, {tagName: 'INPUT', type: 'submit'},
    {tagName: 'INPUT', type: 'text', readOnly: true}, {tagName: 'INPUT', disabled: true}]) {
    assert.equal(isEditableElement(element), false);
  }
});
