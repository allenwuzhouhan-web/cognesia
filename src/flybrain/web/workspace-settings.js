const KEY='cognesia.workspace.preferences.v1';
const defaults={density:'comfortable',quality:'balanced',brainLabels:false,bodyLabels:false,motion:false};
export function initializeWorkspaceSettings({toolbar,onLayout,onParameters}) {
  let prefs={...defaults};try{prefs={...prefs,...JSON.parse(localStorage.getItem(KEY)||'{}')};}catch{}
  const dialog=document.createElement('dialog');dialog.className='workspace-settings-dialog';dialog.setAttribute('aria-label','Workspace settings');
  dialog.innerHTML='<header><div><span class="settings-eyebrow">WORKSPACE</span><h2>Settings</h2></div><button type="button" data-close aria-label="Close settings">×</button></header><div class="settings-body"><section><h3>Interface</h3><p>Display preferences.</p><label>Control density<select data-density><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label></section><section><h3>Rendering</h3><label>Render quality<select data-quality><option value="balanced">Balanced · 1× resolution</option><option value="high">High · display resolution</option></select></label><label class="settings-toggle"><input data-brain-labels type="checkbox"> Show brain region labels</label><label class="settings-toggle"><input data-body-labels type="checkbox"> Show fly body labels</label><label class="settings-toggle"><input data-motion type="checkbox"> Automatic brain rotation</label><p>Drag to orbit · scroll to zoom. Colors show recorded activity.</p></section><section><h3>Scientific configuration</h3><button type="button" data-parameters>Model parameters ↗</button><button type="button" data-layout>Arrange workspace…</button><p>Model settings are on Parameters. Retiling does not run simulations.</p></section></div><footer><button type="button" data-reset>Reset display settings</button><button type="button" data-done>Done</button></footer>';
  document.body.append(dialog);
  const q=s=>dialog.querySelector(s),button=document.createElement('button');button.type='button';button.className='workspace-settings-toggle';button.setAttribute('aria-label','Workspace settings');button.innerHTML='<span aria-hidden="true">⚙</span> Settings';toolbar.append(button);
  function apply(){
    document.body.dataset.density=prefs.density==='compact'?'compact':'comfortable';
    window.dispatchEvent(new CustomEvent('cognesia-render-quality',{detail:{pixelRatio:prefs.quality==='high'?Math.min(devicePixelRatio||1,2):1}}));
    for(const[selector,key]of [['#region-label-toggle','brainLabels'],['[data-fly-labels]','bodyLabels']]){const input=document.querySelector(selector);if(input&&input.checked!==prefs[key]){input.checked=!!prefs[key];input.dispatchEvent(new Event('change',{bubbles:true}));}}
    document.body.classList.toggle('allow-auto-rotation',!!prefs.motion);
    const rotate=document.querySelector('#rotate-button');if(rotate){if(!prefs.motion&&rotate.classList.contains('active'))rotate.click();rotate.disabled=!prefs.motion;rotate.title=prefs.motion?'Rotate the brain automatically':'Enable automatic rotation in Settings';}
  }
  function save(){try{localStorage.setItem(KEY,JSON.stringify(prefs));}catch{}apply();}
  function controls(){q('[data-density]').value=prefs.density;q('[data-quality]').value=prefs.quality;q('[data-brain-labels]').checked=!!prefs.brainLabels;q('[data-body-labels]').checked=!!prefs.bodyLabels;q('[data-motion]').checked=!!prefs.motion;}
  const close=()=>{dialog.close();button.focus();};
  q('[data-close]').addEventListener('click',close);q('[data-done]').addEventListener('click',close);
  q('[data-reset]').addEventListener('click',()=>{prefs={...defaults};controls();save();});
  for(const[selector,key]of [['[data-density]','density'],['[data-quality]','quality'],['[data-brain-labels]','brainLabels'],['[data-body-labels]','bodyLabels'],['[data-motion]','motion']])q(selector).addEventListener('change',event=>{prefs[key]=event.target.type==='checkbox'?event.target.checked:event.target.value;save();});
  q('[data-layout]').addEventListener('click',()=>{dialog.close();onLayout?.();});q('[data-parameters]').addEventListener('click',()=>{dialog.close();onParameters?.();});
  function open(){controls();if(!dialog.open)dialog.showModal();}button.addEventListener('click',open);apply();
  return{open,apply,dispose(){dialog.remove();button.remove();}};
}
