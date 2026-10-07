import {initializeSensoryMaps} from './sensory-maps.js';

/** Keep one copy of each real control, organized by the experiment workflow. */
export function initializeWorkspaceOverview({host, experimentControls, sensoryOptions={}, onSettings}) {
  const q=selector=>document.querySelector(selector);
  const el=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;};
  function group(parent,id,title,nodes,open=false){
    const details=el('details',undefined,'editor-tool-group');details.id=id;details.open=open;
    const content=el('div',undefined,'editor-tool-content');content.append(...nodes.filter(Boolean));
    details.append(el('summary',title),content);parent.append(details);
    details.addEventListener('toggle',()=>{if(details.open)window.dispatchEvent(new Event('resize'));});return details;
  }
  const panel=el('section',undefined,'panel overview-settings editor-inspector');panel.setAttribute('aria-label','Experiment setup');
  panel.innerHTML='<div class="inspector-tabs" role="tablist" aria-label="Experiment workflow"><button type="button" role="tab" data-inspector="experiment">Experiment</button><button type="button" role="tab" data-inspector="sensory">Sensory map</button><button type="button" role="tab" data-inspector="presimulation">Pre-simulation</button></div><div class="inspector-pane" data-inspector-page="experiment"></div><div class="inspector-pane" data-inspector-page="sensory"></div><div class="inspector-pane" data-inspector-page="presimulation"></div><div class="inspector-run-footer"></div>';
  host.append(panel);
  const page=name=>panel.querySelector(`[data-inspector-page="${name}"]`);
  const nodes=experimentControls.elements;
  page('experiment').append(nodes.model,q('.stimulus-panel'));
  page('presimulation').append(nodes.preSimulation);
  group(page('presimulation'),'overview-design-tools','Advanced settings',[nodes.advanced]);
  const sensoryHost=el('div');page('sensory').append(sensoryHost);
  const sensory=initializeSensoryMaps({host:sensoryHost,eyePanel:q('.eye-section'),...sensoryOptions});
  group(page('sensory'),'overview-organ-inputs','Organ inputs',[nodes.organs]);
  // Preserve the execution host observed by both the browser and native menus.
  const session=q('#session-controls');session.querySelector('.experiment-editor')?.remove();
  panel.querySelector('.inspector-run-footer').append(session);
  const setupLink=el('button','Review & configure','preflight-link');setupLink.type='button';
  setupLink.addEventListener('click',()=>showInspector('presimulation'));session.prepend(setupLink);

  function dialog(title){
    const node=el('dialog',undefined,'workspace-tool-dialog');node.setAttribute('aria-label',title);
    const header=el('header'),close=el('button','×');close.type='button';close.setAttribute('aria-label',`Close ${title.toLowerCase()}`);
    close.addEventListener('click',()=>node.close());header.append(el('h2',title),close);
    const body=el('div',undefined,'workspace-tool-dialog-body');node.append(header,body);document.body.append(node);return{node,body,open:()=>{if(!node.open)node.showModal();window.dispatchEvent(new Event('resize'));}};
  }
  const anatomy=dialog('Anatomy & display');
  group(anatomy.body,'overview-brain-tools','Regions & cross-sections',[q('.morphology-toolbar'),q('#morphology-controls'),q('#region-atlas-controls')],true);
  const flyTools=q('.fly-body-tools'),flyInspectorTools=el('div',undefined,'fly-body-tools');
  for(const control of [...(flyTools?.children||[])])if(!control.matches('[data-fly-focus],[data-fly-reset]'))flyInspectorTools.append(control);
  const provenance=q('.fly-body-provenance');if(provenance)provenance.querySelector('summary').textContent='Geometry & alignment';
  group(anatomy.body,'overview-fly-controls','Fly display',[flyInspectorTools,provenance]);
  const chemicalDisplay=group(anatomy.body,'overview-chemical-display','Chemical display',[q('.chemical-selectors')]);
  const recordings=dialog('Saved experiments');recordings.body.append(q('.recordings'));
  const diagnostics=dialog('Run details');
  for(const node of [q('.chemical-readout'),q('.run-diagnostics'),q('.lab-strip')])if(node)diagnostics.body.append(node);
  const toolbar=q('.view-tools');
  for(const [title,action]of [['Anatomy',anatomy.open],['Saved experiments',recordings.open],['Run details',diagnostics.open]]){
    const button=el('button',title,'workspace-tool-link');button.type='button';button.addEventListener('click',action);toolbar.prepend(button);
  }
  const settings=el('button','Settings','workspace-tool-link');settings.type='button';settings.addEventListener('click',()=>onSettings?.());toolbar.append(settings);

  function showInspector(name){
    name=({recordings:'sensory',inspect:'presimulation'})[name]||name;
    for(const item of panel.querySelectorAll('[data-inspector]')){const active=item.dataset.inspector===name;item.setAttribute('aria-selected',String(active));item.tabIndex=active?0:-1;}
    for(const item of panel.querySelectorAll('[data-inspector-page]'))item.hidden=item.dataset.inspectorPage!==name;
    setupLink.hidden=name==='presimulation';
    if(name==='sensory')sensory.refresh();
    window.dispatchEvent(new Event('resize'));
  }
  const tabs=[...panel.querySelectorAll('[data-inspector]')];
  for(const tab of tabs){const name=tab.dataset.inspector,item=page(name);tab.id=`inspector-${name}-tab`;tab.setAttribute('aria-controls',`inspector-${name}-page`);item.id=`inspector-${name}-page`;item.setAttribute('role','tabpanel');item.setAttribute('aria-labelledby',tab.id);}
  tabs.forEach((tab,i)=>{
    tab.addEventListener('click',()=>showInspector(tab.dataset.inspector));
    tab.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const n=event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;showInspector(tabs[n].dataset.inspector);tabs[n].focus();});
  });
  showInspector('experiment');
  return{panel,secondary:null,sensory,showInspector,
    showChemicalInspector(){chemicalDisplay.open=true;anatomy.open();chemicalDisplay.scrollIntoView({block:'nearest'});},
    openDesign(){showInspector('presimulation');q('#overview-design-tools').open=true;},
    refresh(){sensory.refresh();}};
}
