/* Keep this module independent of app.js so a broken app import can recover. */
const POLL_INTERVAL_MS = 1000;
const REQUEST_TIMEOUT_MS = 5000;

function revision(status) {
  if (!status || typeof status.instance_id !== 'string' || !status.instance_id ||
      !['string', 'number'].includes(typeof status.web_revision)) return null;
  return {instance: status.instance_id, web: status.web_revision};
}

export async function fetchLiveReloadStatus({signal, fetchImpl = globalThis.fetch} = {}) {
  const response = await fetchImpl('/api/live-reload', {cache: 'no-store', signal});
  if (!response.ok) throw new Error(`Live update status: HTTP ${response.status}`);
  const status = await response.json();
  if (typeof status?.enabled !== 'boolean' || (status.enabled && !revision(status))) {
    throw new Error('Invalid live update status');
  }
  return status;
}

/** Independent polling controller; injected functions also make lifecycle races testable. */
export function createLiveReloadController({
  initialStatus = null,
  readStatus = fetchLiveReloadStatus,
  reload,
  beforeReload = () => true,
  onStatus = () => {},
  isEditing = () => false,
  schedule = setTimeout,
  cancel = clearTimeout,
  pollIntervalMs = POLL_INTERVAL_MS,
  timeoutMs = REQUEST_TIMEOUT_MS,
} = {}) {
  let baseline = initialStatus?.enabled ? revision(initialStatus) : null;
  let running = false, reloading = false, generation = 0;
  let timer = null, inFlight = null, request = null;

  const report = (phase, text) => onStatus({phase, text});
  function clearPollTimer() {
    if (timer !== null) cancel(timer);
    timer = null;
  }
  function stop() {
    running = false;
    generation++;
    clearPollTimer();
    request?.abort();
  }
  function accept(status) {
    if (status?.enabled === false) {
      report('disabled', 'Live updates disabled');
      return;
    }
    const current = revision(status);
    if (status?.enabled !== true || !current) throw new Error('Invalid live update status');
    // Never advance this baseline while work or editing delays a refresh.
    baseline ||= current;
    const changed = current.instance !== baseline.instance || current.web !== baseline.web;
    if (status.error) {
      report('error', `Live update paused: ${String(status.error).replace(/\s+/g, ' ').slice(0, 180)}`);
    } else if (status.pending || status.restart_pending || (changed && status.busy)) {
      report(status.busy ? 'waiting' : 'updating', status.busy
        ? 'Changes waiting for experiment completion'
        : 'Updating from the app folder…');
    } else if (changed && isEditing()) {
      report('editing', 'Update ready · finish editing to refresh');
    } else if (changed) {
      let saved = false;
      try { saved = beforeReload() !== false; } catch {}
      if (!saved) {
        report('blocked', 'Live update paused · unable to save current controls');
        return;
      }
      report('updating', 'Applying app changes…');
      reloading = true;
      stop();
      reload();
    } else {
      report('ready', 'Live updates enabled');
    }
  }
  function checkNow() {
    if (!running || reloading) return Promise.resolve();
    if (inFlight) return inFlight;
    clearPollTimer();
    const started = generation;
    const abortController = new AbortController();
    request = abortController;
    const timeout = schedule(() => abortController.abort(), timeoutMs);
    // The microtask ensures inFlight is assigned even if readStatus throws synchronously.
    inFlight = Promise.resolve().then(() => readStatus({signal: abortController.signal}))
      .then(status => {
        if (running && generation === started) accept(status);
      })
      .catch(() => {
        if (running && generation === started) report('reconnecting', 'Reconnecting to live updates…');
      })
      .finally(() => {
        cancel(timeout);
        inFlight = null;
        request = null;
        if (running && !reloading) timer = schedule(checkNow, pollIntervalMs);
      });
    return inFlight;
  }
  function start() {
    if (reloading) return Promise.resolve();
    if (!running) {
      running = true;
      generation++;
    }
    return checkNow();
  }
  return {start, stop, checkNow};
}

export function isEditableElement(element) {
  if (!element || element.disabled || element.readOnly) return false;
  if (element.isContentEditable) return true;
  if (element.tagName === 'TEXTAREA' || element.tagName === 'SELECT') return true;
  return element.tagName === 'INPUT' &&
    !['button', 'submit', 'reset', 'image', 'hidden'].includes(element.type);
}

export function installLiveReload(windowObject, documentObject) {
  let indicator = documentObject.getElementById('live-reload-state');
  if (!indicator) {
    indicator = documentObject.createElement('span');
    indicator.id = 'live-reload-state';
    indicator.setAttribute('role', 'status');
    indicator.setAttribute('aria-live', 'polite');
    (documentObject.querySelector('footer') || documentObject.body).append(indicator);
  }
  const controller = createLiveReloadController({
    initialStatus: windowObject.__COGNESIA_LIVE_RELOAD__,
    readStatus: ({signal}) => fetchLiveReloadStatus({signal, fetchImpl: windowObject.fetch.bind(windowObject)}),
    beforeReload: () => windowObject.dispatchEvent(new windowObject.CustomEvent(
      'cognesia:before-live-reload', {cancelable: true},
    )),
    reload: () => windowObject.location.reload(),
    isEditing: () => isEditableElement(documentObject.activeElement),
    onStatus: ({phase, text}) => {
      indicator.dataset.state = phase;
      if (indicator.textContent !== text) indicator.textContent = text;
    },
  });
  let focusTimer = null;
  const afterEditing = () => {
    if (focusTimer !== null) windowObject.clearTimeout(focusTimer);
    // Native change/blur handlers save drafts first; never dispatch synthetic input
    // changes here, since some controls may have effects beyond draft persistence.
    focusTimer = windowObject.setTimeout(() => {
      focusTimer = null;
      controller.checkNow();
    }, 0);
  };
  windowObject.addEventListener('pagehide', () => {
    if (focusTimer !== null) windowObject.clearTimeout(focusTimer);
    focusTimer = null;
    controller.stop();
  });
  windowObject.addEventListener('pageshow', () => controller.start());
  documentObject.addEventListener('focusout', afterEditing);
  controller.start();
  return controller;
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  installLiveReload(window, document);
}
