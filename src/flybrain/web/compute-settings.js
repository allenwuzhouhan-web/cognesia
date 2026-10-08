// Hardware inventory requires a deliberate opt-in; loading this module is read-only.
const dialog = document.createElement('dialog');
dialog.className = 'compute-permissions';
dialog.setAttribute('aria-label', 'Compute permissions');
dialog.innerHTML = `<header><div><small>COGNESIA · LOCAL COMPUTE</small><h2>Choose your compute budget</h2></div><button data-close aria-label="Close compute settings">×</button></header>
  <p>Allow a hardware check to recommend a tier, or choose a budget manually.</p>
  <p class="compute-scope">Reads CPU architecture and core count, RAM totals, OS and free disk space. No personal files, serial numbers or installed apps are read. Nothing is uploaded.</p>
  <div class="compute-consent"><button data-scan>Allow hardware check</button><button data-decline>Skip / revoke access</button></div>
  <p data-hardware role="status">Hardware has not been checked.</p>
  <div class="compute-tier-grid" role="group" aria-label="Compute tiers"></div>
  <div class="compute-budget-fields"><label>Simulation memory ceiling (GB)<input data-memory type="number" min="0.1" step="0.1"></label><label>Neural CPU threads<input data-threads type="number" min="1" step="1"></label><label>Reserve for local GPT-OSS (GB)<input data-reserve type="number" min="0" max="256" step="1" value="0"></label></div>
  <p data-limit></p><p class="compute-scope">These are resource limits. Ultra and Super increase available memory; the current CPU solver and recording limits still apply. Finer sampling does not establish biological accuracy.</p>
  <label class="compute-resolution"><input data-resolution type="checkbox"> Also use this tier’s suggested time step and optical samples for the next experiment</label>
  <p data-message role="status"></p><footer><button data-done>Done</button><button data-apply>Apply budget</button></footer>`;
document.body.append(dialog);
const q = selector => dialog.querySelector(selector);
let policy, selected;

async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}

function setFields() {
  const tier = policy.tiers.find(item => item.id === selected);
  const hardwareLimit = policy.hardware ? policy.hardware.ram_gb * .8 - Number(q('[data-reserve]').value || 0) : Infinity;
  q('[data-memory]').value = Math.floor(Math.min(tier.memory_gb, policy.operator_limit_gb, hardwareLimit) * 10) / 10;
  q('[data-threads]').value = Math.min(tier.threads, policy.hardware?.logical_cpus || tier.threads);
  for (const button of dialog.querySelectorAll('[data-tier]')) button.setAttribute('aria-pressed', String(button.dataset.tier === selected));
}

function render() {
  selected = policy.tier;
  q('[data-reserve]').value = policy.agent_reserve_gb;
  q('[data-hardware]').textContent = policy.hardware
    ? `${policy.hardware.ram_gb} GB RAM · ${policy.hardware.logical_cpus} logical CPUs · ${policy.hardware.free_disk_gb} GB free disk. Recommended: ${policy.recommended.toUpperCase()}.`
    : 'Hardware has not been checked. You can select a conservative budget manually.';
  q('[data-limit]').textContent = `Service ceiling: ${policy.operator_limit_gb} GB. Changes apply when all experiments and preparation are stopped. RAM is checked cooperatively; threads are capped at launch.`;
  q('.compute-tier-grid').replaceChildren(...policy.tiers.map(tier => {
    const button = document.createElement('button'); button.dataset.tier = tier.id;
    button.type = 'button'; button.setAttribute('aria-pressed', String(tier.id === selected));
    const title = document.createElement('strong'); title.textContent = tier.label;
    const details = document.createElement('span'); details.textContent = `${tier.memory_gb} GB · up to ${tier.threads} threads`;
    const description = document.createElement('small'); description.textContent = tier.description;
    button.append(title, details, description);
    button.addEventListener('click', () => { selected = tier.id; setFields(); });
    return button;
  }));
  q('[data-memory]').value = policy.memory_gb; q('[data-threads]').value = policy.threads;
  q('[data-scan]').textContent = policy.consent ? 'Refresh hardware check' : 'Allow hardware check';
}

async function action(work) {
  q('[data-message]').textContent = '';
  for (const button of dialog.querySelectorAll('button')) button.disabled = true;
  try { await work(); } catch (error) { q('[data-message]').textContent = error.message; }
  finally { for (const button of dialog.querySelectorAll('button')) button.disabled = false; }
}

function notifyLab(resolution = false) {
  const tier = policy.tiers.find(item => item.id === policy.tier);
  window.dispatchEvent(new CustomEvent('cognesia-compute-policy', {detail: {
    threads: policy.threads, ...(resolution ? {dt_ms: tier.dt_ms, visual_overrides: {optics_samples: tier.optics_samples}} : {}),
  }}));
}
q('[data-scan]').addEventListener('click', () => action(async () => { policy = await request('/api/compute/consent', {granted:true}); render(); notifyLab(); }));
q('[data-decline]').addEventListener('click', () => action(async () => { policy = await request('/api/compute/consent', {granted:false}); render(); notifyLab(); q('[data-message]').textContent = 'Hardware inventory removed. Manual budgets remain available.'; }));
q('[data-reserve]').addEventListener('input', () => { if (policy) setFields(); });
q('[data-apply]').addEventListener('click', () => action(async () => {
  policy = await request('/api/compute/profile', {tier:selected, memory_gb:Number(q('[data-memory]').value), threads:Number(q('[data-threads]').value), agent_reserve_gb:Number(q('[data-reserve]').value)});
  render(); notifyLab(q('[data-resolution]').checked);
  q('[data-message]').textContent = `${policy.tier.toUpperCase()} applied: ${policy.memory_gb} GB and up to ${policy.threads} neural threads.`;
}));
for (const selector of ['[data-close]', '[data-done]']) q(selector).addEventListener('click', () => dialog.close());
document.querySelector('#compute-permissions-button')?.addEventListener('click', () => action(async () => {
  policy = await request('/api/compute'); render(); dialog.showModal();
}));
request('/api/compute').then(value => { policy = value; render(); if (policy.consent === null) dialog.showModal(); })
  .catch(error => { q('[data-message]').textContent = error.message; });
