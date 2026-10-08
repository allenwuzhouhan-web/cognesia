'use strict';
// The native shell installs this marker only on its trusted main-frame origin.
(() => {
  if (!window.__COGNESIA_RESEARCH_DESKTOP__) return;
  const buttons = {connect:'connect',run:'start',stop:'stop',export:'export','export-pdf':'download-pdf',
    'start-model':'launch-model','unload-model':'unload-model'};
  const publish = () => {
    const enabled = Object.fromEntries(Object.entries(buttons).map(([action,id]) => {
      const button = document.getElementById(id);
      return [action, Boolean(button && !button.disabled)];
    }));
    window.dispatchEvent(new CustomEvent('cognesia-research-state', {detail:{ready:true,enabled,
      status:document.getElementById('connection-state')?.textContent || ''}}));
  };
  window.addEventListener('cognesia-agent-updated', publish);
  window.addEventListener('cognesia-research-command', event => {
    const {action, value} = event.detail || {};
    const button = buttons[action] && document.getElementById(buttons[action]);
    if (button && !button.disabled) { event.preventDefault(); button.click(); return; }
    if (action === 'focus-prompt') {
      event.preventDefault(); window.dispatchEvent(new CustomEvent('cognesia-show-editor')); document.getElementById('prompt')?.focus(); return;
    }
    if (action === 'model-setup' || action === 'model-file' || action === 'runtime-file') {
      if (action !== 'model-setup' && (typeof value !== 'string' || value.length > 8192)) return;
      const details = document.querySelector('details.setup');
      if (!details) return;
      event.preventDefault(); details.open = true;
      const connection = document.getElementById('connection-panel'); if (connection) connection.open = true;
      const field = document.getElementById(action === 'runtime-file' ? 'llama-executable' : 'model-file');
      if (action !== 'model-setup') field.value = value;
      field.focus(); return;
    }
    if (action === 'load-instructions' && typeof value === 'string' && value.length <= 16000) {
      event.preventDefault(); window.dispatchEvent(new CustomEvent('cognesia-show-editor')); const field = document.getElementById('prompt'); field.value = value; field.focus(); return;
    }
    if (['audit','replicates','chemistry'].includes(action)) {
      const template = document.querySelector(`[data-template="${action}"]`);
      if (template) { event.preventDefault(); template.click(); document.getElementById('prompt')?.focus(); }
    }
  });
})();
