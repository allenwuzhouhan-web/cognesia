import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const swift = readFileSync(new URL('./Sources/ResearchWorkspace.swift', import.meta.url), 'utf8');
const bootstrap = swift.match(/let researchBootstrap = """\n([\s\S]*?)\n\s*"""/)[1].replaceAll('\\(port)', '8797');
const bridge = readFileSync(new URL('../src/flybrain/web/agent-desktop.js', import.meta.url), 'utf8');
function page(options = {}) {
  const listeners = new Map(), messages = [], elements = new Map();
  for (const id of ['connect','start','stop','export','download-pdf','launch-model','unload-model','prompt','model-file','llama-executable','connection-state','setup','audit','replicates','chemistry']) {
    elements.set(id, {disabled:false, value:'', textContent:'Connected', clicks:0, focus(){this.focused=true;}, click(){this.clicks++;}});
  }
  const window = {addEventListener:(name,handler) => listeners.set(name,handler),
    dispatchEvent:event => {listeners.get(event.type)?.(event); return !event.defaultPrevented;},
    webkit:{messageHandlers:{cognesiaResearch:{postMessage:message => messages.push(message)}}}};
  const document = {getElementById:id => elements.get(id), querySelector:selector => selector === 'details.setup'
    ? elements.get('setup') : elements.get(selector.match(/data-template="(.*?)"/)?.[1])};
  const context = {window, document, location:{protocol:'http:', hostname:'127.0.0.1',port:'8797',...options},
    CustomEvent:class {constructor(type,options){this.type=type;this.detail=options?.detail;}}};
  vm.runInNewContext(bootstrap,context); vm.runInNewContext(bridge,context);
  const command = (action, value) => {
    const event={type:'cognesia-research-command',detail:{action,value},defaultPrevented:false,preventDefault(){this.defaultPrevented=true;}};
    window.dispatchEvent(event); return event.defaultPrevented;
  };
  return {window,listeners,messages,elements,command};
}
test('research bridge is installed only for the configured loopback origin', () => {
  for (const options of [{hostname:'evil.example'},{port:'8794'},{protocol:'https:'}]) {
    const p=page(options);assert.equal(p.listeners.size,0);assert.equal(p.window.__COGNESIA_RESEARCH_DESKTOP__,undefined);
  }
  assert.equal(page().window.__COGNESIA_RESEARCH_DESKTOP__,true);
});
test('native run and stop obey current button state', () => {
  const p=page();p.elements.get('start').disabled=true;
  assert.equal(p.command('run'),false);assert.equal(p.elements.get('start').clicks,0);
  p.elements.get('start').disabled=false;assert.equal(p.command('run'),true);assert.equal(p.elements.get('start').clicks,1);
  assert.equal(p.command('stop'),true);assert.equal(p.elements.get('stop').clicks,1);
  assert.equal(p.command('exec-shell'),false);
});
test('native file selection preserves literal paths and never launches the model', () => {
  const p=page(), path='/path/with spaces/"model".gguf';
  assert.equal(p.command('model-file',path),true);assert.equal(p.elements.get('model-file').value,path);
  assert.equal(p.elements.get('setup').open,true);assert.equal(p.elements.get('launch-model').clicks,0);
  assert.equal(p.command('runtime-file', '/opt/homebrew/bin/llama-server'),true);
  assert.equal(p.command('model-file', {}),false);
});
test('importing instructions is bounded and does not execute them', () => {
  const p=page();assert.equal(p.command('load-instructions','Inspect readiness\nDo not run.'),true);
  assert.equal(p.elements.get('prompt').value,'Inspect readiness\nDo not run.');assert.equal(p.elements.get('start').clicks,0);
  assert.equal(p.command('load-instructions','x'.repeat(16001)),false);
});
test('native menu state contains availability and status, never connection passwords', () => {
  const p=page();p.elements.set('api-password',{value:'private-secret'});p.elements.get('stop').disabled=true;
  p.window.dispatchEvent({type:'cognesia-agent-updated'});
  assert.equal(p.messages.length,1);assert.equal(p.messages[0].enabled.stop,false);
  assert.equal(p.messages[0].enabled.run,true);assert.equal(JSON.stringify(p.messages).includes('private-secret'),false);
});
test('native templates focus the editor without starting a study', () => {
  const p=page();assert.equal(p.command('replicates'),true);assert.equal(p.elements.get('replicates').clicks,1);
  assert.equal(p.elements.get('prompt').focused,true);assert.equal(p.elements.get('start').clicks,0);
});
test('native PDF export is available only after a report is ready', () => {
  const p=page(); p.elements.get('download-pdf').disabled=true;
  assert.equal(p.command('export-pdf'),false);
  p.elements.get('download-pdf').disabled=false;
  assert.equal(p.command('export-pdf'),true);
  assert.equal(p.elements.get('download-pdf').clicks,1);
});
