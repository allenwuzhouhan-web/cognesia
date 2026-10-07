import { initializeAnalysis } from "./analysis.js";
import { createInstrumentPanel } from "./instrument-viewers.js";
import { createAnatomyPanel, createBodyView } from "./anatomy-panel.js";
import { createChemistryView, createSpikeView, createConnectivityView, createBranchComparisonView } from "./research-panels.js";
import { cloneLayout, panelIds, validateLayout, splitPanel, removePanel, swapPanels, defaultPanelLayout, migrateLegacyLayout, minimumLayoutSize, overviewPanelGroups, editingPanelGroups, upgradeOverviewPresets, canRestoreChart, normalizeEditingSizes, editingGeometry, overviewViewportHeight, createOverviewMeasureScheduler, EDITING_DEFAULTS, OVERVIEW_REVISION, PANEL_LIMIT } from "./layout-model.js";

const STORAGE_KEY="cognesia.workspace.layout.v2";
const CATALOG={chart:"Signal chart",brain:"Brain cross section",body:"Whole fly",spikes:"Spike raster",chemistry:"Chemistry / enzymes",connectivity:"Connections",comparison:"Branch comparison",eeg:"EEG recording",mri:"MRI volume",fmri:"fMRI time series"};
const el=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;};

/** Actual panels are independently scoped; the miniature edits a draft layout. */
export function initializeLayoutWorkbench({host=document.querySelector("#experiment-view"),toolbar=document.querySelector(".page-heading"),panels=[],secondaryContent=null,analysisOptions={},getContext=()=>({}),onStatus}) {
  if(!host||!panels.length)throw new Error("Layout workbench needs a host and at least one existing panel.");
  let layoutStylesheet=document.querySelector('link[data-layout-workbench]');
  if(!layoutStylesheet){layoutStylesheet=document.createElement("link");layoutStylesheet.rel="stylesheet";layoutStylesheet.href=new URL("./layout-workbench.css",import.meta.url).href;layoutStylesheet.dataset.layoutWorkbench="";document.head.append(layoutStylesheet);}
  const core=new Map(panels.map(panel=>[panel.id,{...panel,kind:panel.kind||"core",core:true}])),instances=new Map(),originals=new Map(),parking=el("div","layout-parking"),root=el("div","dock-root"),button=el("button","layout-workbench-toggle");
  button.type="button";button.title="Retile workspace";button.setAttribute("aria-label","Retile workspace");button.innerHTML='<svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true"><rect x="2" y="3" width="8" height="18" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="13" y="3" width="9" height="8" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="13" y="14" width="9" height="7" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/></svg><span>Layout</span>';
  (toolbar||host).append(button);host.classList.add("layout-workbench-host");parking.hidden=true;host.append(parking,root);
  for(const panel of panels){const marker=document.createComment(`layout origin: ${panel.id}`);panel.element.before(marker);originals.set(panel.id,{marker,element:panel.element});instances.set(panel.id,{element:panel.element,controller:panel.controller||null,core:true});}
  let descriptors=new Map(core),tree,workspaceHeight=1000,activeName="Default",presets={},draft=null,draftDescriptors=null,draftHeight=1000,selected=null,disposed=false,counter=0,layoutMode='editing',draftMode='editing',editing=normalizeEditingSizes(),draftEditing=normalizeEditingSizes();
  const defaultIds=panels.map(panel=>panel.id);
  const presetEditing=(preset,name)=>normalizeEditingSizes({...preset?.editing,...(name!=='Default'&&preset?.editing?.timelineUserSized===undefined?{timelineUserSized:true}:{})});
  try{const saved=upgradeOverviewPresets(JSON.parse(localStorage.getItem(STORAGE_KEY)||"null"),defaultIds);presets=saved.presets;activeName=typeof saved.activeName==="string"?saved.activeName:"Default";const current=presets[activeName];if(current){for(const item of current.panels||[])if(core.has(item.id)||Object.hasOwn(CATALOG,item.kind))descriptors.set(item.id,core.has(item.id)?{...core.get(item.id),state:item.state}:item);tree=validateLayout(current.tree,new Set(descriptors.keys()));workspaceHeight=Math.max(600,Math.min(2400,Number(current.height)||1000));layoutMode=current.mode==='editing'?'editing':'custom';editing=presetEditing(current,activeName);}}catch{onStatus?.("Saved layout was invalid; the default workspace was restored.");}
  if(!tree){let legacy=null;try{legacy=JSON.parse(localStorage.getItem("cognesia.workspace.layout.v1")||"null");}catch{}tree=migrateLegacyLayout(legacy,defaultIds);}
  for(const[id,instance]of instances){const saved=descriptors.get(id)?.state;if(Array.isArray(saved)&&instance.controller?.restoreState)instance.pendingState=saved;}
  function snapshotState(id,item){const instance=instances.get(id),controller=instance?.controller;if(!controller?.exportState)return item.state;return[...controller.exportState({includeSamples:false}),...(instance.pendingState||[])];}
  async function restorePending(instance){
    if(instance.restoring||!instance.pendingState?.length||!instance.controller?.restoreState)return;
    instance.restoring=true;
    try{for(const card of [...instance.pendingState]){if(!canRestoreChart(card,getContext().summary?.id))continue;const current=instance.controller.exportState({includeSamples:false});
      // Default charts may already have loaded for this recording. Do not add duplicates.
      const sameSignals=saved=>saved.signals?.length===card.signals.length&&saved.signals.every((source,index)=>source.id===card.signals[index].id&&source.runId===card.signals[index].runId);
      const alreadyPresent=current.some(saved=>sameSignals(saved)&&saved.mode===card.mode&&saved.harmonics===card.harmonics&&!!saved.demean===!!card.demean&&!!saved.hann===!!card.hann&&JSON.stringify(saved.interval??null)===JSON.stringify(card.interval??null));
      if(!alreadyPresent)await instance.controller.restoreState([card]);
      if(alreadyPresent||instance.controller.exportState({includeSamples:false}).length>current.length)instance.pendingState=instance.pendingState.filter(item=>item!==card);
    }}finally{instance.restoring=false;}
  }
  function persist(){
    const ids=panelIds(tree);presets[activeName]={tree:cloneLayout(tree),height:workspaceHeight,mode:layoutMode,editing:{...editing},overview_revision:OVERVIEW_REVISION,panels:ids.map(id=>{const item=descriptors.get(id),state=snapshotState(id,item);return{id,title:item.title,kind:item.kind,...(state?{state}:{})};})};
    try{localStorage.setItem(STORAGE_KEY,JSON.stringify({version:2,editing_revision:OVERVIEW_REVISION,chart_sizing_revision:1,activeName,presets}));}catch{onStatus?.("Layout changed, but this browser could not save it.");}
  }
  function chartFromSignal(source){if(panelIds(tree).length>=PANEL_LIMIT){onStatus?.(`Close a panel before adding another (limit ${PANEL_LIMIT}).`);return;}const id=`chart-${Date.now()}-${++counter}`;descriptors.set(id,{id,kind:"chart",title:source.label||"Signal chart",initialSignal:source});tree=splitPanel(tree,panelIds(tree).at(-1),id,"bottom");render();persist();}
  function ensureInstance(id){
    if(instances.has(id))return instances.get(id);
    const descriptor=descriptors.get(id),element=el("section","dock-added-panel");element.dataset.panelId=id;const options={host:element,getContext,analysisOptions,onStatus,onSignal:chartFromSignal};let controller;
    try{
      if(descriptor.kind==="chart"){controller=initializeAnalysis({...analysisOptions,host:element,autoDefaults:false});controller.refresh();if(descriptor.initialSignal)controller.addSignalSnapshot(descriptor.initialSignal);}
      else if(["eeg","mri","fmri"].includes(descriptor.kind))controller=createInstrumentPanel({...options,kind:descriptor.kind,initialState:descriptor.instrumentState});
      else if(descriptor.kind==="brain")controller=createAnatomyPanel(options);
      else if(descriptor.kind==="body")controller=createBodyView(options);
      else if(descriptor.kind==="chemistry")controller=createChemistryView(options);
      else if(descriptor.kind==="spikes")controller=createSpikeView(options);
      else if(descriptor.kind==="connectivity")controller=createConnectivityView(options);
      else if(descriptor.kind==="comparison")controller=createBranchComparisonView(options);
      else throw new Error("This panel type is unavailable.");
      if(descriptor.state&&controller.restoreState&&descriptor.kind!=="chart")controller.restoreState(descriptor.state);
    }catch(error){element.textContent=`Panel could not initialize: ${error.message}`;onStatus?.(error.message);}
    const instance={element,controller,core:false,pendingState:descriptor.kind==='chart'&&Array.isArray(descriptor.state)?descriptor.state:[]};instances.set(id,instance);restorePending(instance);return instance;
  }
  function resizeNotice(){const event=new Event("resize");event.workspaceLayoutResize=true;window.dispatchEvent(event);}
  function editingDimensions(container,mini=false){const actual=mini?root.querySelector('.dock-primary-grid'):container;return{width:actual?.clientWidth||1200,height:actual?.clientHeight||640};}
  function setDimension(container,key,value){if(container.style.getPropertyValue(key)!==value)container.style.setProperty(key,value);}
  function applyEditingGeometry(container,preference,mini=false){
    if(!container)return;const dimensions=editingDimensions(container,mini),geometry=editingGeometry(dimensions.width,dimensions.height,preference);
    setDimension(container,'--editing-left',mini?`${geometry.leftWidth/dimensions.width*100}%`:`${geometry.leftWidth}px`);
    setDimension(container,'--editing-sequence',mini?`${geometry.timelineHeight/dimensions.height*100}%`:`${geometry.timelineHeight}px`);
    setDimension(container,'--editing-divider',`${mini?7:geometry.divider}px`);
    for(const handle of container.querySelectorAll('.dock-editing-divider')){
      const key=handle.dataset.resize,dimension=key==='timelineFraction'?'timelineHeight':key,value=geometry[dimension];
      const low=key==='timelineFraction'?.2:180,high=key==='timelineFraction'?.72:key==='leftWidth'?560:600;
      const min=editingGeometry(dimensions.width,dimensions.height,{...preference,[key]:low,timelineUserSized:true})[dimension],max=editingGeometry(dimensions.width,dimensions.height,{...preference,[key]:high,timelineUserSized:true})[dimension];
      handle.setAttribute('aria-valuenow',String(Math.round(value)));handle.setAttribute('aria-valuetext',`${Math.round(value)} pixels`);handle.setAttribute('aria-valuemin',String(Math.round(min)));handle.setAttribute('aria-valuemax',String(Math.round(max)));
    }
  }
  function editingDivider(key,container,mini=false){
    const handle=el('div',`dock-editing-divider dock-editing-${key}`),horizontal=key==='timelineFraction';handle.tabIndex=0;handle.dataset.resize=key;handle.setAttribute('role','separator');handle.setAttribute('aria-orientation',horizontal?'horizontal':'vertical');handle.setAttribute('aria-label',`Resize ${key==='leftWidth'?'simulation settings':key==='rightWidth'?'fly view':'sequence area'}`);handle.title='Drag to resize · arrow keys to adjust · Enter to reset';
    const get=()=>mini?draftEditing:editing;
    const update=(value,reset=false)=>{const preference=normalizeEditingSizes({...get(),[key]:value,...(horizontal?{timelineUserSized:!reset}:{})});if(mini)draftEditing=preference;else editing=preference;applyEditingGeometry(container,preference,mini);if(!mini)resizeNotice();};
    handle.addEventListener('keydown',event=>{const relevant=horizontal?['ArrowUp','ArrowDown']:['ArrowLeft','ArrowRight'];let next=get()[key];if(relevant.includes(event.key)){const direction=['ArrowRight','ArrowDown'].includes(event.key)?1:-1;next+=direction*(key==='leftWidth'?1:-1)*(horizontal?(event.shiftKey?.05:.02):(event.shiftKey?40:10));}else if(event.key==='Home')next=horizontal?.2:180;else if(event.key==='End')next=horizontal?.6:key==='leftWidth'?560:600;else if(event.key==='Enter')next=EDITING_DEFAULTS[key];else return;event.preventDefault();update(next,event.key==='Enter');if(!mini)persist();});
    handle.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();handle.focus({preventScroll:true});handle.setPointerCapture(event.pointerId);const original={...get()};let ended=false;
      const move=e=>{const rect=container.getBoundingClientRect(),dimensions=editingDimensions(container,mini),geometry=editingGeometry(dimensions.width,dimensions.height,get());if(!rect.width||!rect.height)return;const x=(e.clientX-rect.left)/rect.width*dimensions.width,y=(e.clientY-rect.top)/rect.height*dimensions.height;update(key==='leftWidth'?x-geometry.divider/2:key==='rightWidth'?dimensions.width-x-geometry.divider/2:(dimensions.height-y-geometry.divider/2)/(dimensions.height-geometry.divider));};
      const finish=cancelled=>{if(ended)return;ended=true;handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',up);handle.removeEventListener('pointercancel',cancel);window.removeEventListener('keydown',escape);if(cancelled){if(mini)draftEditing=original;else editing=original;applyEditingGeometry(container,original,mini);if(!mini)resizeNotice();}try{handle.releasePointerCapture(event.pointerId);}catch{}if(!mini&&!cancelled)persist();};
      const up=()=>finish(false),cancel=()=>finish(true),escape=e=>{if(e.key==='Escape'){e.preventDefault();finish(true);}};handle.addEventListener('pointermove',move);handle.addEventListener('pointerup',up);handle.addEventListener('pointercancel',cancel);window.addEventListener('keydown',escape);
    });return handle;
  }
  function renderEditingGrid(ids,mini=false){
    const grid=el('div',mini?'layout-mini-primary dock-editing-grid':'dock-primary-grid dock-editing-grid'),groups=editingPanelGroups(ids);
    for(const id of groups.panels){
      const panel=renderNode({type:'panel',id},mini);
      if(id==='brain'&&groups.inset){
        const body=renderNode({type:'panel',id:groups.inset},mini);
        if(mini){const group=el('div','layout-mini-brain-group');body.classList.add('layout-mini-body-inset');body.textContent=`${draftDescriptors.get(groups.inset)?.title||'Fly'} inset`;group.append(panel,body);grid.append(group);continue;}
        body.classList.add('dock-body-inset');(panel.querySelector('.brain-stage')||panel).append(body);
      }
      grid.append(panel);
    }
    for(const key of ['leftWidth','timelineFraction'])grid.append(editingDivider(key,grid,mini));return grid;
  }
  function divider(node,container,mini=false){
    const handle=el("div","dock-divider");handle.tabIndex=0;handle.setAttribute("role","separator");handle.setAttribute("aria-orientation",node.axis==="horizontal"?"vertical":"horizontal");handle.setAttribute("aria-label",`Resize ${node.axis} split`);handle.setAttribute("aria-valuemin","10");handle.setAttribute("aria-valuemax","90");handle.setAttribute("aria-valuenow",Math.round(node.ratio*100));
    const update=()=>{container.style.setProperty("--split-ratio",`${node.ratio*100}%`);handle.setAttribute("aria-valuenow",Math.round(node.ratio*100));if(!mini)resizeNotice();};
    handle.addEventListener("keydown",event=>{let next=node.ratio;if(["ArrowLeft","ArrowUp"].includes(event.key))next-=event.shiftKey?.1:.02;else if(["ArrowRight","ArrowDown"].includes(event.key))next+=event.shiftKey?.1:.02;else if(event.key==="Home")next=.1;else if(event.key==="End")next=.9;else if(event.key==="Enter")next=.5;else return;event.preventDefault();node.ratio=Math.max(.1,Math.min(.9,next));update();if(!mini)persist();});
    handle.addEventListener("pointerdown",event=>{if(event.button!==0)return;event.preventDefault();const original=node.ratio;handle.setPointerCapture(event.pointerId);let ended=false;const move=e=>{const rect=container.getBoundingClientRect(),fraction=node.axis==="horizontal"?(e.clientX-rect.left)/rect.width:(e.clientY-rect.top)/rect.height;node.ratio=Math.max(.1,Math.min(.9,fraction));update();};const finish=(cancel=false)=>{if(ended)return;ended=true;handle.removeEventListener("pointermove",move);handle.removeEventListener("pointerup",up);handle.removeEventListener("pointercancel",cancelled);window.removeEventListener("keydown",escape);if(cancel){node.ratio=original;update();}try{handle.releasePointerCapture(event.pointerId);}catch{}if(!mini&&!cancel)persist();};const up=()=>finish(),cancelled=()=>finish(true),escape=e=>{if(e.key==="Escape")finish(true);};handle.addEventListener("pointermove",move);handle.addEventListener("pointerup",up);handle.addEventListener("pointercancel",cancelled);window.addEventListener("keydown",escape);});return handle;
  }
  function renderNode(node,mini=false){
    if(node.type==="split"){const box=el("div",`dock-split dock-${node.axis}${mini?" dock-mini-split":""}`);box.style.setProperty("--split-ratio",`${node.ratio*100}%`);if(!mini){const minimum=minimumLayoutSize(node),a=minimumLayoutSize(node.first),b=minimumLayoutSize(node.second);box.style.minWidth=`${minimum.width}px`;box.style.minHeight=`${minimum.height}px`;box.style.setProperty("--first-min",`${node.axis==="horizontal"?a.width:a.height}px`);box.style.setProperty("--second-min",`${node.axis==="horizontal"?b.width:b.height}px`);}box.append(renderNode(node.first,mini),divider(node,box,mini),renderNode(node.second,mini));return box;}
    const descriptor=(mini?draftDescriptors:descriptors).get(node.id);
    if(mini){const box=el("button",`dock-mini-panel${selected===node.id?" selected":""}`,descriptor.title||descriptor.id);box.type="button";box.draggable=true;box.dataset.panelId=node.id;box.addEventListener("click",()=>{selected=node.id;renderMini();});box.addEventListener("dragstart",event=>event.dataTransfer.setData("application/cognesia-panel",node.id));box.addEventListener("dragover",event=>{event.preventDefault();box.classList.add("drag-over");});box.addEventListener("dragleave",()=>box.classList.remove("drag-over"));box.addEventListener("drop",event=>{event.preventDefault();const from=event.dataTransfer.getData("application/cognesia-panel");if(!panelIds(draft).includes(from)||from===node.id)return;const rect=box.getBoundingClientRect(),x=(event.clientX-rect.left)/rect.width,y=(event.clientY-rect.top)/rect.height;const edge=x<.22?"left":x>.78?"right":y<.22?"top":y>.78?"bottom":null;draft=edge?splitPanel(draft,node.id,from,edge):swapPanels(draft,from,node.id);draftMode='custom';selected=from;renderMini();});return box;}
    const shell=el("section","dock-panel-shell"),heading=el("div","dock-panel-heading"),title=el("span","",descriptor.title||descriptor.id),edit=el("button","","⋮");edit.title="Arrange this panel";edit.setAttribute("aria-label",`Arrange ${title.textContent}`);edit.addEventListener("click",()=>open(node.id));heading.append(title,edit);shell.dataset.panelId=node.id;shell.append(heading,ensureInstance(node.id).element);return shell;
  }
  function render(){
    for(const instance of instances.values())parking.append(instance.element);
    // Parking extracts the live fly element; remove its old empty wrapper before retiling.
    instances.get('brain')?.element.querySelectorAll('.dock-body-inset').forEach(inset=>inset.remove());
    root.classList.toggle('dock-overview',layoutMode==='editing');host.classList.toggle('workspace-overview-mode',layoutMode==='editing');host.classList.toggle('workspace-editing-mode',layoutMode==='editing');
    if(layoutMode==='editing'){
      const groups=overviewPanelGroups(panelIds(tree)),primary=renderEditingGrid(groups.primary);primary.setAttribute('aria-label','Editing workspace');
      root.replaceChildren(primary);root.style.height='auto';if(secondaryContent)root.append(secondaryContent);
      if(groups.secondary.length){const section=el('section','dock-secondary-section'),heading=el('h2','dock-section-title','Additional tools'),secondary=el('div','dock-secondary-grid');section.setAttribute('aria-label','Additional workspace tools');for(const id of groups.secondary)secondary.append(renderNode({type:'panel',id}));section.append(heading,secondary);root.append(section);}
      observeOverviewGrid(primary);scheduleOverviewSize();
    }else{root.replaceChildren(renderNode(tree));root.style.height=`${workspaceHeight}px`;if(secondaryContent)host.append(secondaryContent);}
    const active=new Set(panelIds(tree));for(const[id,instance]of instances)if(!active.has(id)&&!instance.core){instance.controller?.dispose?.();instance.element.remove();instances.delete(id);}
    resizeNotice();
  }
  let measuringOverview=false,observedGrid=null;
  function sizeOverview(){
    if(measuringOverview||disposed||layoutMode!=='editing'||host.hidden)return;
    const grid=root.querySelector('.dock-primary-grid');if(!grid)return;
    measuringOverview=true;
    try{const documentTop=grid.getBoundingClientRect().top+window.scrollY,height=overviewViewportHeight({innerHeight:window.innerHeight,visualHeight:window.visualViewport?.height,documentTop});
      setDimension(grid,'--overview-height',`${height}px`);applyEditingGeometry(grid,editing);
    }finally{measuringOverview=false;}
  }
  // Native WebKit can defer animation frames while its view is attaching. The
  // meaningful triggers measure synchronously, then settle once on a frame.
  const overviewSizer=createOverviewMeasureScheduler({measure:sizeOverview,requestFrame:callback=>requestAnimationFrame(callback),cancelFrame:id=>cancelAnimationFrame(id)});
  const scheduleOverviewSize=overviewSizer.refresh;
  const overviewObserver=typeof ResizeObserver==='undefined'?null:new ResizeObserver(overviewSizer.queue);
  function observeOverviewGrid(grid){if(observedGrid===grid)return;if(observedGrid)overviewObserver?.unobserve(observedGrid);observedGrid=grid;overviewObserver?.observe(grid);}
  overviewObserver?.observe(host);overviewObserver?.observe(document.documentElement);
  const visibilityObserver=typeof MutationObserver==='undefined'?null:new MutationObserver(scheduleOverviewSize);
  visibilityObserver?.observe(host,{attributes:true,attributeFilter:['hidden']});visibilityObserver?.observe(document.documentElement,{attributes:true,attributeFilter:['class']});visibilityObserver?.observe(document.body,{attributes:true,attributeFilter:['class']});
  window.addEventListener('resize',scheduleOverviewSize);
  window.addEventListener('pageshow',scheduleOverviewSize);window.visualViewport?.addEventListener('resize',scheduleOverviewSize);
  document.addEventListener('visibilitychange',scheduleOverviewSize);layoutStylesheet.addEventListener('load',scheduleOverviewSize);
  const dialog=el("dialog","layout-workbench-dialog");dialog.setAttribute("aria-label","Retile workspace");dialog.innerHTML='<div class="layout-dialog-heading"><div><h2>Retile workspace</h2><p>Drag tiles to swap them. Drop near an edge to split. Drag dividers to resize.</p></div><button data-cancel aria-label="Cancel layout changes">×</button></div><div class="layout-editor-controls"><label>Saved layout<select data-presets></select></label><label>Layout name<input data-name maxlength="64" placeholder="My research layout"></label><button data-save>Save named layout</button><label>Workspace height<input data-height type="number" min="600" max="2400" step="100"></label></div><div class="layout-minimap" aria-label="Simplified workspace layout"></div><div class="layout-editor-controls"><label>Add panel<select data-add-type></select></label><label>Place<select data-edge><option value="right">Right of selection</option><option value="left">Left of selection</option><option value="bottom">Below selection</option><option value="top">Above selection</option></select></label><button data-add>Add</button><button data-duplicate>Duplicate selected</button><button data-remove>Close selected</button><button data-reset>Reset layout</button></div><p class="layout-editor-status" role="status"></p><div class="layout-dialog-actions"><button data-cancel>Cancel</button><button data-apply class="primary-button">Apply layout</button></div>';
  document.body.append(dialog);const $=s=>dialog.querySelector(s),status=$(".layout-editor-status");
  const modeLabel=el('label','', 'Layout style'),modeSelect=el('select');modeSelect.dataset.layoutMode='';modeSelect.add(new Option('Editing workspace','editing'));modeSelect.add(new Option('Custom tiling','custom'));modeLabel.append(modeSelect);$('.layout-editor-controls').prepend(modeLabel);
  modeSelect.addEventListener('change',()=>{draftMode=modeSelect.value;if(draftMode==='editing'){for(const id of overviewPanelGroups(defaultIds).primary)draftDescriptors.set(id,core.get(id));draft=defaultPanelLayout([...new Set([...overviewPanelGroups(defaultIds).primary,...panelIds(draft)])]);}renderMini();});
  function updatePresetOptions(){$("[data-presets]").replaceChildren(...Object.keys(presets).map(name=>new Option(name,name)));if(presets[activeName])$("[data-presets]").value=activeName;}
  function renderMini(){if(!draft)return;const ids=panelIds(draft),map=$('.layout-minimap');map.classList.toggle('layout-overview-minimap',draftMode==='editing');if(draftMode==='editing'){const groups=overviewPanelGroups(ids),primary=renderEditingGrid(groups.primary,true);map.replaceChildren(primary);if(groups.secondary.length){const secondary=el('div','layout-mini-secondary');secondary.append(el('span','', 'Below the main workspace'));for(const id of groups.secondary)secondary.append(renderNode({type:'panel',id},true));map.append(secondary);}requestAnimationFrame(()=>applyEditingGeometry(primary,draftEditing,true));}else map.replaceChildren(renderNode(draft,true));modeSelect.value=draftMode;$("[data-height]").disabled=draftMode==='editing';$("[data-edge]").disabled=draftMode==='editing';$("[data-remove]").disabled=ids.length<=1;$("[data-duplicate]").disabled=!selected||ids.length>=PANEL_LIMIT;$("[data-add]").disabled=ids.length>=PANEL_LIMIT;const type=$("[data-add-type]"),prior=type.value;type.replaceChildren();for(const[id,item]of core)if(!ids.includes(id))type.add(new Option(`Restore ${item.title}`,`core:${id}`));for(const[kind,title]of Object.entries(CATALOG))type.add(new Option(title,kind));if([...type.options].some(o=>o.value===prior))type.value=prior;status.textContent=`${ids.length} panels · selected: ${draftDescriptors.get(selected)?.title||"none"}. ${draftMode==='editing'?'Inputs on the left, brain with a fly inset, sequence below. Drag the two dividers to resize. Added tools appear below.':'Custom tiling: drag tiles and dividers to arrange your workspace.'} Imported files remain in memory.`;}
  function open(id=null){if(disposed)return;draft=cloneLayout(tree);draftDescriptors=new Map([...descriptors].map(([key,value])=>[key,{...value}]));draftHeight=workspaceHeight;draftMode=layoutMode;draftEditing={...editing};selected=id||panelIds(draft)[0];$("[data-height]").value=draftHeight;$("[data-name]").value=activeName;updatePresetOptions();renderMini();if(!dialog.open)dialog.showModal();}
  const cancel=()=>{draft=null;draftDescriptors=null;dialog.close();button.focus();};
  for(const cancelButton of dialog.querySelectorAll("[data-cancel]"))cancelButton.addEventListener("click",cancel);dialog.addEventListener("cancel",event=>{event.preventDefault();cancel();});button.addEventListener("click",()=>open());
  $("[data-add]").addEventListener("click",()=>{const kind=$("[data-add-type]").value,edge=$("[data-edge]").value;let id;if(kind.startsWith("core:")){id=kind.slice(5);draftDescriptors.set(id,core.get(id));}else{id=`${kind}-${Date.now()}-${++counter}`;draftDescriptors.set(id,{id,kind,title:CATALOG[kind]});}draft=splitPanel(draft,selected||panelIds(draft).at(-1),id,edge);selected=id;renderMini();});
  $("[data-duplicate]").addEventListener("click",()=>{const source=draftDescriptors.get(selected);let kind=source.kind;if(kind==="core")kind=/brain/i.test(source.id)?"brain":/fly/i.test(source.id)?"body":/analysis|chart/i.test(source.id)?"chart":"chart";const id=`${kind}-${Date.now()}-${++counter}`,controller=instances.get(selected)?.controller;draftDescriptors.set(id,{id,kind,title:`${source.title} copy`,state:controller?.exportState?.()||source.state,instrumentState:controller?.exportInstrumentState?.()});draft=splitPanel(draft,selected,id,$("[data-edge]").value);selected=id;renderMini();});
  $("[data-remove]").addEventListener("click",()=>{if(panelIds(draft).length<2)return;if(overviewPanelGroups([selected]).primary.length)draftMode='custom';draft=removePanel(draft,selected);selected=panelIds(draft)[0];renderMini();});
  $("[data-reset]").addEventListener("click",()=>{draft=defaultPanelLayout(defaultIds);draftDescriptors=new Map(core);draftMode='editing';draftEditing=normalizeEditingSizes();selected=defaultIds[0];draftHeight=1000;$("[data-height]").value=draftHeight;renderMini();});
  $("[data-presets]").addEventListener("change",()=>{const saved=presets[$("[data-presets]").value];if(!saved)return;try{const available=new Map(core);for(const descriptor of saved.panels||[])if(core.has(descriptor.id)||Object.hasOwn(CATALOG,descriptor.kind))available.set(descriptor.id,core.has(descriptor.id)?{...core.get(descriptor.id),state:descriptor.state}:descriptor);draft=validateLayout(saved.tree,new Set(available.keys()));draftDescriptors=available;draftMode=saved.mode==='editing'?'editing':'custom';draftEditing=presetEditing(saved,$('[data-presets]').value);selected=panelIds(draft)[0];draftHeight=saved.height||1000;$("[data-height]").value=draftHeight;$("[data-name]").value=$("[data-presets]").value;renderMini();}catch(error){status.textContent=error.message;}});
  $("[data-save]").addEventListener("click",()=>{const name=$("[data-name]").value.trim();if(!name){status.textContent="Give this layout a name.";return;}presets[name]={tree:cloneLayout(draft),mode:draftMode,editing:{...draftEditing},overview_revision:OVERVIEW_REVISION,height:Math.max(600,Math.min(2400,Number($("[data-height]").value)||1000)),panels:panelIds(draft).map(id=>{const item=draftDescriptors.get(id),state=snapshotState(id,item);return{id,kind:item.kind,title:item.title,...(state?{state}:{})};})};try{localStorage.setItem(STORAGE_KEY,JSON.stringify({version:2,editing_revision:OVERVIEW_REVISION,chart_sizing_revision:1,activeName,presets}));updatePresetOptions();$("[data-presets]").value=name;status.textContent=`Saved “${name}”. Apply to use this arrangement.`;}catch{status.textContent="The browser could not save this layout.";}});
  $("[data-apply]").addEventListener("click",()=>{try{tree=validateLayout(draft,new Set(draftDescriptors.keys()));descriptors=draftDescriptors;layoutMode=draftMode;editing={...draftEditing};workspaceHeight=Math.max(600,Math.min(2400,Number($("[data-height]").value)||1000));activeName=$("[data-name]").value.trim()||"Default";render();persist();cancel();onStatus?.(`Applied ${activeName} layout.`);}catch(error){status.textContent=error.message;}});
  render();persist();
  return{open,refresh(){scheduleOverviewSize();for(const[id,instance]of instances)if(panelIds(tree).includes(id))Promise.resolve(instance.controller?.refresh?.()).then(()=>restorePending(instance)).catch(error=>onStatus?.(error.message));},setTime(ms){for(const[id,instance]of instances)if(panelIds(tree).includes(id))instance.controller?.setTime?.(ms);},addSignal:chartFromSignal,dispose(){disposed=true;overviewSizer.dispose();overviewObserver?.disconnect();visibilityObserver?.disconnect();layoutStylesheet.removeEventListener('load',scheduleOverviewSize);window.removeEventListener('pageshow',scheduleOverviewSize);window.visualViewport?.removeEventListener('resize',scheduleOverviewSize);document.removeEventListener('visibilitychange',scheduleOverviewSize);window.removeEventListener('resize',scheduleOverviewSize);for(const[id,instance]of instances){if(!instance.core)instance.controller?.dispose?.();else{const origin=originals.get(id);origin.marker.replaceWith(origin.element);}}instances.get('brain')?.element.querySelectorAll('.dock-body-inset').forEach(inset=>inset.remove());instances.clear();dialog.remove();button.remove();parking.remove();root.remove();host.classList.remove("layout-workbench-host","workspace-overview-mode","workspace-editing-mode");}};
}
