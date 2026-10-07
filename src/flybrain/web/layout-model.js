export const LAYOUT_VERSION=2;
export const PANEL_LIMIT=24;
export const OVERVIEW_REVISION=3;
export const PRIMARY_PANELS=['inputs','brain','fly','analysis'];
export const EDITING_DEFAULTS=Object.freeze({leftWidth:320,rightWidth:300,timelineFraction:.52});
const bounded=(value,min,max,fallback)=>Math.max(min,Math.min(max,Number.isFinite(value)?value:fallback));
export function normalizeEditingSizes(saved={}){return{leftWidth:bounded(saved?.leftWidth,180,560,EDITING_DEFAULTS.leftWidth),rightWidth:bounded(saved?.rightWidth,180,600,EDITING_DEFAULTS.rightWidth),timelineFraction:bounded(saved?.timelineFraction,.2,.72,EDITING_DEFAULTS.timelineFraction),...(saved?.timelineUserSized===true?{timelineUserSized:true}:{})};}
export function overviewViewportHeight({innerHeight,visualHeight,documentTop=0,bottomMargin=18}) {
  const heights=[innerHeight,visualHeight].filter(value=>Number.isFinite(value)&&value>0);
  const viewport=heights.length?Math.min(...heights):800;
  return Math.round(Math.max(532,Math.min(1200,viewport-Math.max(0,documentTop)-bottomMargin)));
}
/** Immediate measurements also work while a native view defers animation frames. */
export function createOverviewMeasureScheduler({measure,requestFrame,cancelFrame}) {
  let pending=null,disposed=false,measuring=false;
  const run=()=>{if(disposed||measuring)return;measuring=true;try{measure();}finally{measuring=false;}};
  const queue=()=>{if(disposed||measuring||pending!==null)return;pending=requestFrame(()=>{pending=null;run();});};
  return{queue,refresh(event){if(disposed||measuring||event?.workspaceLayoutResize)return;run();queue();},dispose(){disposed=true;if(pending!==null)cancelFrame(pending);pending=null;}};
}
/** Clamp rendered sizes to the available viewport without changing stored preferences. */
export function editingGeometry(width,height,saved={}){
  const preference=normalizeEditingSizes(saved),w=Math.max(0,Number.isFinite(width)?width:0),h=Math.max(0,Number.isFinite(height)?height:0);
  const divider=Math.min(8,w/4,h/4),availableWidth=Math.max(0,w-divider),availableHeight=Math.max(0,h-divider);
  const sideMin=Math.min(180,availableWidth*.25),brainMin=Math.min(260,availableWidth*.6);
  const leftWidth=Math.max(sideMin,Math.min(preference.leftWidth,availableWidth-brainMin));
  const roomy=!preference.timelineUserSized&&availableHeight>=720;
  const timelineMin=roomy?390:Math.min(180,availableHeight*.45),topMin=Math.min(220,availableHeight*.55);
  const timelineHeight=Math.max(timelineMin,Math.min(availableHeight-topMin,availableHeight*preference.timelineFraction));
  // rightWidth remains a saved legacy preference; the fly now overlays the brain.
  return{leftWidth,rightWidth:0,brainWidth:availableWidth-leftWidth,topHeight:availableHeight-timelineHeight,timelineHeight,divider};
}
export const cloneLayout=value=>structuredClone(value);
export function panelIds(tree){if(!tree)return[];return tree.type==="panel"?[tree.id]:[...panelIds(tree.first),...panelIds(tree.second)];}
export function overviewPanelGroups(ids){const present=new Set(ids);return{primary:PRIMARY_PANELS.filter(id=>present.has(id)),secondary:ids.filter(id=>!PRIMARY_PANELS.includes(id))};}
export function editingPanelGroups(ids){const inset=ids.includes('brain')&&ids.includes('fly')?'fly':null;return{panels:ids.filter(id=>id!==inset),inset};}
/** Metadata-only signal snapshots can resolve only against their own recording. */
export function canRestoreChart(card,runId){return Array.isArray(card?.signals)&&card.signals.length>0&&card.signals.every(signal=>Array.isArray(signal.timeMs)&&Array.isArray(signal.values)||runId!=null&&(signal.runId==null||signal.runId===runId));}
export function minimumLayoutSize(tree){if(tree.type==="panel")return{width:240,height:260};const a=minimumLayoutSize(tree.first),b=minimumLayoutSize(tree.second);return tree.axis==="horizontal"?{width:a.width+b.width+7,height:Math.max(a.height,b.height)}:{width:Math.max(a.width,b.width),height:a.height+b.height+7};}
export function validateLayout(tree,allowedIds=null){
  const seen=new Set();
  const visit=(node,depth)=>{
    if(!node||depth>32)throw new Error("Workspace layout is missing or too deeply nested.");
    if(node.type==="panel"){
      if(typeof node.id!=="string"||!node.id||seen.has(node.id)||allowedIds&&!allowedIds.has(node.id))throw new Error("Workspace layout contains an unknown or duplicate panel.");
      seen.add(node.id);if(seen.size>PANEL_LIMIT)throw new Error(`A workspace supports up to ${PANEL_LIMIT} panels.`);return{type:"panel",id:node.id};
    }
    if(node.type!=="split"||!["horizontal","vertical"].includes(node.axis)||!Number.isFinite(node.ratio))throw new Error("Workspace split is invalid.");
    return{type:"split",axis:node.axis,ratio:Math.max(.1,Math.min(.9,node.ratio)),first:visit(node.first,depth+1),second:visit(node.second,depth+1)};
  };
  return visit(tree,0);
}
export function removePanel(tree,id){
  if(!tree)return null;if(tree.type==="panel")return tree.id===id?null:cloneLayout(tree);
  const first=removePanel(tree.first,id),second=removePanel(tree.second,id);return first&&second?{...tree,first,second}:first||second;
}
export function splitPanel(tree,targetId,newId,edge="right"){
  if(!["left","right","top","bottom"].includes(edge))throw new Error("Choose a valid panel edge.");
  if(newId===targetId)return cloneLayout(tree);
  if(!tree)return{type:"panel",id:newId};
  if(!panelIds(tree).includes(targetId))throw new Error("The destination panel no longer exists.");
  tree=removePanel(tree,newId);
  const visit=node=>{if(node.type==="panel"){if(node.id!==targetId)return node;const added={type:"panel",id:newId},before=["left","top"].includes(edge);return{type:"split",axis:["left","right"].includes(edge)?"horizontal":"vertical",ratio:.5,first:before?added:node,second:before?node:added};}return{...node,first:visit(node.first),second:visit(node.second)};};
  return visit(tree);
}
export function swapPanels(tree,a,b){if(!panelIds(tree).includes(a)||!panelIds(tree).includes(b))return cloneLayout(tree);const visit=node=>node.type==="panel"?{...node,id:node.id===a?b:node.id===b?a:node.id}:{...node,first:visit(node.first),second:visit(node.second)};return visit(tree);}
export function defaultPanelLayout(ids){
  if(!ids.length)return null;
  if(ids.length===1)return{type:"panel",id:ids[0]};
  const groups=overviewPanelGroups(ids);
  if(groups.primary.length===4){
    const panel=id=>({type:'panel',id});
    // Keep fly addressable in the tree for custom tiling; editing docks it inside brain.
    const top={type:'split',axis:'horizontal',ratio:.65,first:panel('brain'),second:panel('fly')};
    const stage={type:'split',axis:'vertical',ratio:1-EDITING_DEFAULTS.timelineFraction,first:top,second:panel('analysis')};
    const primary={type:'split',axis:'horizontal',ratio:.22,first:panel('inputs'),second:stage};
    return groups.secondary.length?{type:'split',axis:'vertical',ratio:.75,first:primary,second:defaultPanelLayout(groups.secondary)}:primary;
  }
  // The primary brain remains between input controls and measurements.
  let tree={type:"panel",id:ids[0]};
  for(let i=1;i<Math.min(3,ids.length);i++)tree={type:"split",axis:"horizontal",ratio:i===1?.28:.76,first:tree,second:{type:"panel",id:ids[i]}};
  for(let i=3;i<ids.length;i++)tree={type:"split",axis:"vertical",ratio:.75,first:tree,second:{type:"panel",id:ids[i]}};
  return tree;
}
export function migrateLegacyLayout(saved,ids){
  const tree=defaultPanelLayout(ids);
  if(!saved||saved.version!==1)return tree;
  if(overviewPanelGroups(ids).primary.length===4)return tree;
  // Old pixel widths only inform the starting three-pane proportions.
  const input=Number(saved.widths?.wide?.input),readout=Number(saved.widths?.wide?.readout);
  if(ids.length>=3&&Number.isFinite(input)&&Number.isFinite(readout)){
    let base=tree;while(base.type==="split"&&base.axis==="vertical")base=base.first;
    if(base.type==="split"&&base.first.type==="split"){const total=input+640+readout;base.ratio=Math.max(.1,Math.min(.9,(input+640)/total));base.first.ratio=Math.max(.1,Math.min(.9,input/(input+640)));}
  }
  return tree;
}

/** Activate each new editing revision once, retaining the prior active arrangement. */
export function upgradeOverviewPresets(saved,coreIds){
  const result=saved?.version===2?cloneLayout(saved):{version:2,activeName:'Default',presets:{}};
  if(!result.presets||typeof result.presets!=='object'||Array.isArray(result.presets))result.presets={};
  const previous=result.presets.Default,active=result.presets[result.activeName],firstUpgrade=result.editing_revision!==OVERVIEW_REVISION;
  const backup=(name,preset)=>{let key=`Previous ${name}`,suffix=2;while(result.presets[key])key=`Previous ${name} ${suffix++}`;result.presets[key]={...cloneLayout(preset),mode:preset.mode||'custom'};};
  if(previous?.overview_revision!==OVERVIEW_REVISION){
    if(previous)backup('Default',previous);
    const ids=[...new Set([...coreIds,...(previous?.tree?panelIds(previous.tree):[])])];
    result.presets.Default={...previous,tree:defaultPanelLayout(ids),mode:'editing',editing:normalizeEditingSizes(),overview_revision:OVERVIEW_REVISION,height:previous?.height||1000,panels:previous?.panels||[]};
  }
  if(firstUpgrade){
    // A previously active named layout must not hide the requested redesign.
    // Keep both its named copy and a frozen backup before activating the new default.
    if(active&&(result.activeName!=='Default'||previous?.overview_revision===OVERVIEW_REVISION&&active.mode!=='editing'))backup(result.activeName||'Default',active);
    const defaults=result.presets.Default;
    const ids=[...new Set([...coreIds,...(active?.tree?panelIds(active.tree):[]),...panelIds(defaults.tree)])].slice(0,PANEL_LIMIT);
    const descriptors=new Map([...(defaults.panels||[]),...(active?.panels||[])].map(panel=>[panel.id,panel]));
    result.presets.Default={...defaults,tree:defaultPanelLayout(ids),mode:'editing',editing:normalizeEditingSizes(),panels:ids.filter(id=>descriptors.has(id)).map(id=>descriptors.get(id))};
    result.activeName='Default';
    result.editing_revision=OVERVIEW_REVISION;
  }
  // Old automatic defaults predate rectangular charts. Migrate only that
  // recognizable Default, preserving named/custom layouts and explicit drags.
  if(result.chart_sizing_revision!==1){
    const preset=result.presets.Default,sizes=preset?.editing;
    if(preset?.mode==='editing'&&sizes&&!sizes.timelineUserSized){
      const legacy=[.34,.40].some(fraction=>Math.abs((sizes.timelineFraction??NaN)-fraction)<1e-8);
      if(legacy&&sizes.leftWidth===260&&sizes.rightWidth===300){backup('Default before chart sizing',preset);preset.editing=normalizeEditingSizes();}
      else if(Number.isFinite(sizes.timelineFraction)&&sizes.timelineFraction!==EDITING_DEFAULTS.timelineFraction)preset.editing={...sizes,timelineUserSized:true};
    }
    result.chart_sizing_revision=1;
  }
  return result;
}
