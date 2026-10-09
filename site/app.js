'use strict';

(() => {
  const $ = id => document.getElementById(id);
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const capabilityLink = $('capability-docs');
  const docsBase = capabilityLink.getAttribute('href').replace(/docs\/model-sources\.md$/, 'docs/');
  const capabilities = {
    anatomy: { kicker: 'ANATOMICAL CONTEXT', title: 'See where a question begins.', copy: 'Explore 3D anatomy, regions and source pathways across FlyWire and BANC-based models. Keep measured connections distinguishable from inferred relationships.', features: ['Region and neuron inspection', 'Source-linked model identity', 'Connectivity and morphology views'], document: 'model-sources.md', link: 'Read the anatomy guide', panel: 'Brain / connectivity', stage: 'Anatomy in context', subtitle: 'Explore sources, regions and connections', readout: 'Keep the source attached.', evidence: 'Inspect model identity and anatomical context before interpreting a signal.' },
    chemistry: { kicker: 'MESSENGERS & MODEL ASSUMPTIONS', title: 'Put chemistry in context.', copy: 'Inspect chemical fields, receptor assumptions and the evidence behind each messenger. Keep implemented dynamics separate from candidates that are currently annotations.', features: ['Evidence-tagged messenger catalog', 'Chemical fields and interventions', 'Receptor and enzyme assumptions'], document: 'wholebrain_chemistry.md', link: 'Explore chemical modeling', panel: 'Brain / chemical fields', stage: 'Chemistry with provenance', subtitle: 'Implemented dynamics and research candidates', readout: 'An annotation is not a simulation.', evidence: 'Chemical messenger evidence and modeled receptor effects remain distinct layers.' },
    experiments: { kicker: 'CONTROLLED & RECORDED', title: 'Make every run inspectable.', copy: 'Configure visual stimuli, virtual electrodes and timeline interventions. Use matched controls, independent seeds and supported checkpoints to keep comparisons reproducible.', features: ['Paired stimulus and control', 'Pause and checkpoint branches', 'Recorded signals and run identity'], document: 'experiment-workspace.md', link: 'Open the experiment guide', panel: 'Experiment / selected model', stage: 'A controlled comparison', subtitle: 'Stimulus, controls and interventions', readout: 'Keep the failures, too.', evidence: 'Preserve the options, seeds, warnings and numerical diagnostics for every experiment.' },
    research: { kicker: 'LOCAL GPT-OSS-20B', title: 'Delegate the work. Inspect the evidence.', copy: 'Use a dedicated local research app to coordinate Cognesia tools. Review the calls, reopen saved research chats and export structured reports with their recorded evidence.', features: ['Local GPT-OSS-20B inference', 'Visible tools and saved chats', 'Research reports and PDF export'], document: 'local-agent.md', link: 'Meet the research workspace', panel: 'Research / evidence context', stage: 'Tools connected to the workbench', subtitle: 'Local inference with an inspectable tool record', readout: 'A conclusion needs a record.', evidence: 'Generated interpretations still need scientific review. More model runs do not establish biological validity.' }
  };

  function chooseCapability(name, focus = false) {
    const item = capabilities[name];
    if (!item) return;
    for (const button of document.querySelectorAll('[data-capability]')) {
      const selected = button.dataset.capability === name;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
      if (selected && focus) button.focus();
    }
    $('capability-panel').setAttribute('aria-labelledby', `tab-${name}`);
    for (const [id, value] of [['capability-kicker', item.kicker], ['capability-title', item.title], ['capability-copy', item.copy], ['demo-panel-title', item.panel], ['demo-stage-title', item.stage], ['demo-stage-subtitle', item.subtitle], ['demo-readout-title', item.readout], ['demo-readout-copy', item.evidence]]) $(id).textContent = value;
    $('capability-features').replaceChildren(...item.features.map(text => {
      const li = document.createElement('li'); li.textContent = text; return li;
    }));
    capabilityLink.href = docsBase + item.document;
    capabilityLink.textContent = item.link + ' ↗';
    $('workspace-demo').dataset.mode = name;
  }

  function tabKeyboard(event, buttons, select) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const current = buttons.indexOf(event.currentTarget);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
    select(buttons[next]);
    buttons[next].focus();
  }
  const featureButtons = [...document.querySelectorAll('[data-capability]')];
  for (const button of featureButtons) {
    button.addEventListener('click', () => chooseCapability(button.dataset.capability));
    button.addEventListener('keydown', event => tabKeyboard(event, featureButtons, item => chooseCapability(item.dataset.capability)));
  }
  const apiTabs = [...document.querySelectorAll('[data-api-tab]')];
  function selectApiTab(tab) {
    for (const button of apiTabs) {
      const active = button === tab;
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
      $(button.dataset.apiTab + '-panel').hidden = !active;
    }
  }
  for (const button of apiTabs) {
    button.addEventListener('click', () => selectApiTab(button));
    button.addEventListener('keydown', event => tabKeyboard(event, apiTabs, selectApiTab));
  }

  // A deterministic illustration, intentionally unrelated to measured anatomical data.
  let seed = 241107;
  const random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  const nodes = [];
  const regions = [[143, 173, 63, 82, 52], [242, 141, 58, 76, 51], [282, 213, 45, 50, 31]];
  for (const [x, y, rx, ry, count] of regions) {
    for (let i = 0; i < count; i++) {
      const angle = random() * Math.PI * 2, radius = Math.sqrt(random());
      const point = { x: x + Math.cos(angle) * radius * rx, y: y + Math.sin(angle) * radius * ry };
      nodes.push(point, { x: 660 - point.x + (random() - .5) * 6, y: point.y + (random() - .5) * 7 });
    }
  }
  for (let i = 0; i < 20; i++) nodes.push({ x: 310 + random() * 40, y: 160 + random() * 135 });
  const links = document.createDocumentFragment(), dots = document.createDocumentFragment();
  nodes.forEach((node, index) => {
    const closest = nodes.map((other, otherIndex) => ({ other, otherIndex, distance: Math.hypot(node.x - other.x, node.y - other.y) })).filter(item => item.otherIndex > index && item.distance < 63).sort((a, b) => a.distance - b.distance).slice(0, 3);
    for (const { other } of closest) {
      const line = document.createElementNS(SVG_NS, 'line');
      for (const [key, value] of Object.entries({ x1: node.x.toFixed(1), y1: node.y.toFixed(1), x2: other.x.toFixed(1), y2: other.y.toFixed(1), class: 'brain-link' })) line.setAttribute(key, value);
      links.append(line);
    }
    const circle = document.createElementNS(SVG_NS, 'circle');
    for (const [key, value] of Object.entries({ cx: node.x.toFixed(1), cy: node.y.toFixed(1), r: (index % 17 === 0 ? 2.5 : 1.1 + random() * .7).toFixed(1), class: index % 17 === 0 ? 'brain-node bright' : 'brain-node' })) circle.setAttribute(key, value);
    dots.append(circle);
  });
  $('brain-links').append(links); $('brain-nodes').append(dots);

  // The public static site offers installation links and never accepts keys.
  if (!$('access-form')) return;

  const READ_TOOLS = new Set(['cognesia_bootstrap', 'cognesia_models', 'cognesia_model', 'cognesia_messengers', 'cognesia_resources', 'cognesia_neuron', 'cognesia_region', 'cognesia_peripheral', 'cognesia_eyes', 'cognesia_connectivity', 'cognesia_preview', 'cognesia_sessions', 'cognesia_session', 'cognesia_frame', 'cognesia_checkpoints', 'cognesia_runs', 'cognesia_run_summary', 'cognesia_analyze_interval', 'cognesia_morphology_status', 'cognesia_morphology_neuron', 'cognesia_morphology_overview', 'cognesia_read_asset']);
  const ENDPOINTS = new Set(['/v1/access', '/v1/tools', '/v1/tools/call']);
  const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
  const IDLE_LIMIT = 15 * 60 * 1000;
  const controllers = new Set();
  let accessKey = '', generation = 0, tools = [], busy = false, lastActivity = 0;
  class PortalError extends Error { constructor(message, status = 0) { super(message); this.status = status; } }

  function scrub(value, credential, depth = 0) {
    if (depth > 40) return '[nested output omitted]';
    if (typeof value === 'string') return credential ? value.split(credential).join('[credential redacted]') : value;
    if (Array.isArray(value)) return value.map(item => scrub(item, credential, depth + 1));
    if (value && typeof value === 'object') {
      const output = Object.create(null);
      for (const [key, item] of Object.entries(value)) output[scrub(key, credential)] = /^(authorization|api_key|access_key|api_password|password|password_hash|password_verifier|backend_url|key_verifier|secret)$/i.test(key) ? '[private field redacted]' : scrub(item, credential, depth + 1);
      return output;
    }
    return value;
  }
  function setStatus(message, tone = '') { $('api-status').textContent = message; $('api-status').className = `api-status${tone ? ' ' + tone : ''}`; }
  function badge(text, state = '') { $('connection-label').textContent = text; $('connection-badge').className = `connection-badge${state ? ' ' + state : ''}`; }
  function setBusy(value) {
    busy = value;
    $('connect-button').disabled = value;
    $('access-key').disabled = value;
    $('call-button').disabled = value || !tools.length;
    $('tool-select').disabled = value || !tools.length;
    $('tool-arguments').disabled = value || !tools.length;
  }
  function disconnect(message = 'Disconnected. Your key and the displayed response have been cleared.') {
    generation++;
    for (const controller of controllers) controller.abort();
    controllers.clear();
    accessKey = ''; tools = []; lastActivity = 0;
    $('access-key').value = '';
    $('customer-name').textContent = ''; $('workspace-name').textContent = '';
    $('tool-select').replaceChildren(); $('tool-description').textContent = '';
    $('tool-arguments').value = '{}'; $('tool-response').textContent = 'Select a tool to inspect your workspace.';
    $('response-status').textContent = 'No request yet';
    $('access-panel').hidden = false; $('connected-panel').hidden = true;
    badge('Not connected'); setBusy(false); setStatus(message);
  }

  async function api(path, credential, epoch, payload) {
    if (!ENDPOINTS.has(path)) throw new PortalError('This console only calls its own Cognesia API routes.');
    if (window.location.protocol !== 'https:' && !(window.location.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname))) throw new PortalError('Open this workspace over HTTPS before entering an API access key. Localhost previews are also supported.');
    if (epoch !== generation) throw new DOMException('Connection changed', 'AbortError');
    if (payload !== undefined && !crypto.randomUUID) throw new PortalError('Use HTTPS or localhost to make authenticated tool calls.');
    const controller = new AbortController(); controllers.add(controller);
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 30000);
    const headers = { 'Authorization': `Bearer ${credential}`, 'Accept': 'application/json' };
    if (payload !== undefined) {
      headers['Content-Type'] = 'application/json'; headers['Idempotency-Key'] = crypto.randomUUID();
    }
    try {
      const response = await fetch(path, { method: payload === undefined ? 'GET' : 'POST', headers, body: payload === undefined ? undefined : JSON.stringify(payload), signal: controller.signal, credentials: 'omit', cache: 'no-store', redirect: 'error', mode: 'same-origin', referrerPolicy: 'no-referrer' });
      if (!response.headers.get('Content-Type')?.toLowerCase().includes('application/json')) throw new PortalError('This address is serving a website without the expected API. Open the API-enabled website provided by your workspace administrator.');
      const advertised = Number(response.headers.get('Content-Length'));
      if (advertised > MAX_RESPONSE_BYTES) throw new PortalError('The response is too large for this console. Use a smaller selection or an API client.');
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let bytes = 0, raw = '';
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        bytes += chunk.value.byteLength;
        if (bytes > MAX_RESPONSE_BYTES) { await reader.cancel(); throw new PortalError('The response is too large for this console. Use a smaller selection or an API client.'); }
        raw += decoder.decode(chunk.value, { stream: true });
      }
      raw += decoder.decode();
      if (epoch !== generation) throw new DOMException('Connection changed', 'AbortError');
      let result;
      try { result = scrub(JSON.parse(raw), credential); } catch { throw new PortalError('The API returned an unreadable response. Contact your workspace administrator.'); }
      if (!response.ok) {
        const detail = typeof result?.error === 'string' ? result.error : result?.error?.message;
        const fallback = response.status === 401 ? 'Your key was not accepted. Check it with your workspace administrator.' : response.status === 403 ? 'Your key does not allow this operation.' : response.status === 429 ? 'The workspace is receiving too many requests. Try again shortly.' : `The API returned an error (${response.status}).`;
        throw new PortalError(detail ? String(detail).slice(0, 400) : fallback, response.status);
      }
      return result;
    } catch (error) {
      if (timedOut) throw new PortalError('The request timed out after 30 seconds. Its outcome is unknown; inspect the workspace before retrying.');
      if (error instanceof PortalError || error.name === 'AbortError') throw error;
      throw new PortalError('The API could not be reached. Check this website and your connection; no request will be retried automatically.');
    } finally {
      clearTimeout(timeout); controllers.delete(controller);
    }
  }

  function exampleValue(spec, depth = 0) {
    if (!spec || depth > 5) return null;
    if (Object.hasOwn(spec, 'default')) return spec.default;
    if (Array.isArray(spec.enum) && spec.enum.length) return spec.enum[0];
    if (spec.type === 'object') return Object.fromEntries((spec.required || []).map(key => [key, exampleValue(spec.properties?.[key], depth + 1)]));
    if (spec.type === 'array') return [];
    if (spec.type === 'integer' || spec.type === 'number') return spec.minimum ?? 0;
    if (spec.type === 'boolean') return false;
    return '';
  }
  function selectTool() {
    const tool = tools.find(item => item.function.name === $('tool-select').value);
    $('tool-description').textContent = tool?.function.description || '';
    $('tool-arguments').value = JSON.stringify(tool ? exampleValue(tool.function.parameters) || {} : {}, null, 2);
    $('call-button').disabled = busy || !tool;
  }
  $('access-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    let candidate = $('access-key').value.trim();
    if (!candidate) { setStatus('Enter the personal API access key issued for your workspace.', 'error'); return; }
    if (candidate.length > 1024 || /[\r\n]/.test(candidate)) { $('access-key').value = ''; setStatus('The key format is invalid. Paste only the key provided by your administrator.', 'error'); return; }
    disconnect('Checking your key and workspace permissions…');
    const epoch = generation;
    setBusy(true); badge('Connecting', 'loading');
    try {
      const identity = await api('/v1/access', candidate, epoch);
      if (identity?.authenticated !== true || identity?.authentication !== 'customer_key' || typeof identity?.customer?.id !== 'string') throw new PortalError('This connection did not confirm a personal customer key. Ask your administrator for a personal API access key.');
      const discovery = await api('/v1/tools', candidate, epoch);
      if (!Array.isArray(discovery?.tools)) throw new PortalError('The API did not return a valid tool catalog.');
      if (epoch !== generation) return;
      tools = discovery.tools.filter(tool => tool?.type === 'function' && typeof tool?.function?.name === 'string' && READ_TOOLS.has(tool.function.name) && discovery.tool_scopes?.[tool.function.name] === 'read');
      accessKey = candidate; lastActivity = Date.now();
      $('customer-name').textContent = typeof identity.customer.name === 'string' ? identity.customer.name : identity.customer.id;
      $('workspace-name').textContent = typeof identity.workspace?.id === 'string' ? `Workspace / ${identity.workspace.id}` : 'Authorized workspace';
      $('tool-select').replaceChildren(...tools.map(tool => { const option = document.createElement('option'); option.value = tool.function.name; option.textContent = tool.function.name; return option; }));
      $('access-panel').hidden = true; $('connected-panel').hidden = false;
      badge('Connected', 'connected'); selectTool();
      setStatus(tools.length ? `${tools.length} inspection tools available. The key is held only in this page's memory and is cleared after 15 minutes of inactivity.` : 'Connected, but this key exposes no inspection tools supported by the website console.', 'success');
    } catch (error) {
      if (epoch !== generation) return;
      disconnect();
      setStatus(error.name === 'AbortError' ? 'Connection cancelled.' : error.message, 'error');
    } finally {
      candidate = '';
      if (epoch === generation) setBusy(false);
    }
  });
  $('disconnect-button').addEventListener('click', () => disconnect());
  $('tool-select').addEventListener('change', selectTool);
  $('tool-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !accessKey) return;
    const tool = tools.find(item => item.function.name === $('tool-select').value);
    if (!tool) return;
    let args;
    try {
      if ($('tool-arguments').value.length > 50000) throw new Error();
      args = JSON.parse($('tool-arguments').value);
      if (!args || typeof args !== 'object' || Array.isArray(args)) throw new Error();
    } catch { setStatus('Arguments must be a JSON object of at most 50,000 characters.', 'error'); return; }
    const epoch = generation;
    setBusy(true); $('response-status').textContent = 'Waiting…';
    $('tool-response').textContent = 'Calling the selected inspection tool…';
    setStatus('Request sent. Nothing will be retried automatically.');
    try {
      const response = await api('/v1/tools/call', accessKey, epoch, { name: tool.function.name, arguments: args });
      if (epoch !== generation) return;
      $('tool-response').textContent = JSON.stringify(response.result ?? response, null, 2);
      $('response-status').textContent = 'Received'; setStatus('Inspection response received from your workspace.', 'success');
    } catch (error) {
      if (epoch !== generation) return;
      if (error.status === 401) { disconnect('The key is no longer accepted. Reconnect with a valid key.'); return; }
      $('response-status').textContent = 'Request failed'; $('tool-response').textContent = error.message;
      setStatus(error.name === 'AbortError' ? 'Request cancelled.' : error.message, 'error');
    } finally { if (epoch === generation) setBusy(false); }
  });

  async function copyText(value, destination, success) {
    try { await navigator.clipboard.writeText(value); $(destination).textContent = success; }
    catch { $(destination).textContent = 'Clipboard access was unavailable. Select and copy the text manually.'; }
  }
  $('copy-sample').addEventListener('click', () => copyText($('request-example').textContent, 'copy-status', 'Example copied. It contains placeholders, not your personal key.'));
  $('copy-access-request').addEventListener('click', () => copyText('Please issue a personal Cognesia API access key for my research workspace and share its API-enabled website address, allowed permissions and expiry.', 'api-status', 'Access-request text copied. Send it to your workspace administrator through your usual contact channel.'));
  for (const type of ['pointerdown', 'keydown', 'touchstart']) document.addEventListener(type, () => { if (accessKey) lastActivity = Date.now(); }, { passive: true });
  setInterval(() => { if (accessKey && Date.now() - lastActivity >= IDLE_LIMIT) disconnect('Disconnected after 15 minutes of inactivity. Your key and displayed response have been cleared.'); }, 30000);
  window.addEventListener('pagehide', () => disconnect('Connection cleared when leaving this page.'));
  // Authentication stays disabled until the complete script has initialized.
  setBusy(false);
})();
