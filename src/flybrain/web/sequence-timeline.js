import {SEQUENCE_KINDS,SEQUENCE_LABELS,checkedTimeline,expandTimeline,editTimelineEvent,nearestSampleIndex,recordedTimes,rulerTicks,timeAtPixel,curveCardId,signalSegments,recordedProtocol,eventLabel,regionResponseClips,clipReplayBounds,formatSignalValue} from './sequence-model.js';

import {regionLabel} from './brain-region-names.js';

const LABEL_WIDTH=172;
const MODEL_NAMES={'paralimbo-v0-1-0':'ParaLimbo 0.1 · BANC × FlyWire','banc-888':'BANC','cognesia-fused-v1':'Cognesia','flywire-783':'FlyWire'};
const recordedModelName=summary=>{const id=summary?.model_id||summary?.metadata?.model_id||summary?.anatomy?.model_id;return MODEL_NAMES[id]||id||'Model unspecified';};
const COLORS=['#64d9e6','#b7a5f7','#efbb76','#8bd7a6','#ee9bbf','#86b6ff'];
const element=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;};
const button=(text,action,title)=>{const node=element('button',text);node.type='button';if(title)node.title=title;node.addEventListener('click',action);return node;};
const select=(pairs,value,action)=>{const node=element('select');for(const [key,label] of pairs)node.add(new Option(label,key));node.value=value;node.addEventListener('change',()=>action(node.value));return node;};
const format=value=>Number.isFinite(value)?Number(value.toFixed(3)).toLocaleString():'—';
const compact=value=>Number.isFinite(value)?Number(value.toPrecision(4)).toString():'—';

export function defaultResponseSignals(catalog) {
  const voltage=catalog.filter(item=>item.unit==='mV'&&item.id.endsWith(':raw'));
  const populations=voltage.filter(item=>item.id.startsWith('trace:')||item.kind==='population');
  const result=[],add=item=>{if(item&&result.length<2&&!result.some(prior=>prior.id===item.id))result.push(item);};
  add(populations.find(item=>/^Motor\s*(?:·|$)/i.test(item.label)));
  add(populations.find(item=>/\b(?:T4|T5|LPLC|LC)\w*/i.test(item.label)));
  populations.forEach(add);voltage.forEach(add);
  catalog.filter(item=>/^eye:(left|right):mean$/.test(item.id)).forEach(add);
  if(!result.length)add(catalog[0]);
  return result;
}

/** Shared model-time view. Only onSeek changes playback; editing never starts a run. */
export function initializeSequenceTimeline({host,experimentControls,listSignals,resolveSignal,getTime,getCurrentRunId,getState,onSeek,onPlay,onAnalyzeSignal,onStatus}) {
  let summary=null,times=[],runId=null,cursor=Number(getTime?.())||0,duration=1000,zoom=1,mode='curves',selected=null,modeChosen=false;
  let liveActive=false,liveTime=0,livePhase='';
  let responseAreas=[],thresholdMv=.1,showAllAreas=false,replay=null,clipIn=null,clipOut=null,savedClips=[];
  let curves=[],catalog=[],disposed=false,generation=0,raf=0,rendering=false,lastWidth=0,lastDraft='',bootstrappedRun=null;
  const root=element('section',undefined,'sequence-timeline');root.setAttribute('aria-label','Experiment sequence and recorded signals');host.append(root);
  const toolbar=element('div',undefined,'seq-toolbar'),title=element('strong','Timeline'),recordLabel=element('span','No results','seq-record-label');
  const transport=element('div',undefined,'seq-transport');
  const play=button('▶',()=>togglePlay(),'Play or pause the loaded recording');play.setAttribute('aria-label','Play recorded activity');
  const previous=button('‹',()=>step(-1),'Previous recorded sample'),next=button('›',()=>step(1),'Next recorded sample');
  previous.setAttribute('aria-label','Previous recorded sample');next.setAttribute('aria-label','Next recorded sample');
  const timeLabel=element('output','0 ms','seq-time');transport.append(previous,play,next,timeLabel);
  const modePicker=select([['curves','Results'],['draft','Next run'],['both','Compare setup']],mode,value=>{mode=value;modeChosen=true;selected=null;viewport.scrollTop=0;render();});modePicker.setAttribute('aria-label','Sequence layers');
  const zoomLabel=element('label',undefined,'seq-zoom');zoomLabel.append(element('span','Zoom'));
  const zoomSlider=element('input');zoomSlider.type='range';zoomSlider.min='1';zoomSlider.max='8';zoomSlider.step='.25';zoomSlider.value='1';zoomSlider.setAttribute('aria-label','Timeline zoom');
  zoomSlider.addEventListener('input',()=>{const fraction=viewport.scrollLeft/Math.max(1,plane.clientWidth);zoom=Number(zoomSlider.value);renderTracks();viewport.scrollLeft=fraction*plane.clientWidth;});
  zoomLabel.append(zoomSlider,button('Fit',()=>{zoom=1;zoomSlider.value='1';viewport.scrollLeft=0;renderTracks();}));
  const editTools=button('＋',()=>{toolsRow.hidden=!toolsRow.hidden;editTools.setAttribute('aria-expanded',String(!toolsRow.hidden));},'Add stimuli, curves, or replay clips');editTools.setAttribute('aria-label','Timeline tools');editTools.setAttribute('aria-expanded','false');
  toolbar.append(title,transport,modePicker,recordLabel,zoomLabel,editTools);root.append(toolbar);

  const toolsRow=element('div',undefined,'seq-tools');toolsRow.hidden=true;
  const kindPicker=select(SEQUENCE_KINDS.map(kind=>[kind,SEQUENCE_LABELS[kind]]),'visual',()=>{});kindPicker.setAttribute('aria-label','New stimulus type');
  const addEvent=button('+ Stimulus',async()=>{try{
    const index=await experimentControls.addTimelineEvent(kindPicker.value,{start_ms:Math.max(0,Math.round(cursor)),duration_ms:100});
    mode='draft';modeChosen=true;modePicker.value=mode;selected={source:'draft',index};viewport.scrollTop=0;render();
    announce('Stimulus added to the next run.');
  }catch(error){fail(error);}});
  const search=element('input');search.type='search';search.placeholder='Find signal…';search.setAttribute('aria-label','Find recorded signal');search.addEventListener('input',renderSignalPicker);
  const signalPicker=element('select');signalPicker.setAttribute('aria-label','Recorded signal to add');
  const addCurve=button('+ Curve',()=>addSignal(signalPicker.value));
  const repeatInput=element('input');repeatInput.type='number';repeatInput.min='1';repeatInput.max='100';repeatInput.step='1';repeatInput.setAttribute('aria-label','Stimulus repetitions');
  repeatInput.addEventListener('change',()=>{try{const doc=draft();doc.repeat=typeof doc.repeat==='object'?{...doc.repeat,count:Number(repeatInput.value)}:Number(repeatInput.value);experimentControls.setTimeline(checkedTimeline(doc));}catch(error){fail(error);}});
  const repeatLabel=element('label',undefined,'seq-repeat');repeatLabel.append(element('span','Repeat'),repeatInput);
  const threshold=element('input');threshold.type='number';threshold.min='.000001';threshold.step='.05';threshold.value=String(thresholdMv);threshold.setAttribute('aria-label','Brain response threshold in mV');
  threshold.addEventListener('change',()=>{const next=Number(threshold.value);if(!Number.isFinite(next)||next<=0){threshold.value=String(thresholdMv);fail(Error('Response threshold must be positive, in mV.'));return;}thresholdMv=next;responseAreas=regionResponseClips(summary,{thresholdMv});renderTracks();});
  const thresholdLabel=element('label',undefined,'seq-threshold');thresholdLabel.append(element('span','Response |ΔV| ≥'),threshold,element('span','mV'));
  const markIn=button('In',()=>markClip('in'),'Set clip start at playhead (I)'),markOut=button('Out',()=>markClip('out'),'Set clip end at playhead (O)'),saveClip=button('+ Clip',saveMarkedClip,'Save marked interval for replay');
  toolsRow.append(kindPicker,addEvent,repeatLabel,search,signalPicker,addCurve,thresholdLabel,markIn,markOut,saveClip);root.append(toolsRow);

  const workspace=element('div',undefined,'seq-workspace'),viewport=element('div',undefined,'seq-viewport'),plane=element('div',undefined,'seq-plane'),curveGrid=element('div',undefined,'seq-curve-grid');
  curveGrid.setAttribute('aria-label','Recorded signal charts');
  viewport.tabIndex=0;viewport.setAttribute('aria-label','Sequence tracks; left and right arrows seek recorded samples');viewport.append(plane);workspace.append(viewport);root.append(workspace);
  const inspector=element('div',undefined,'seq-inspector');inspector.hidden=true;root.append(inspector);
  const status=element('p','Drag to seek · double-click a clip to replay · Space to play','seq-status');status.setAttribute('role','status');root.append(status);
  const playhead=element('div',undefined,'seq-playhead');playhead.setAttribute('aria-hidden','true');
  viewport.addEventListener('keydown',event=>{if(event.target!==viewport)return;if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();step(event.key==='ArrowLeft'?-1:1);}if(event.code==='Space'){event.preventDefault();event.stopPropagation();if(times.length&&!liveActive)togglePlay();}if(event.key?.toLowerCase()==='i')markClip('in');if(event.key?.toLowerCase()==='o')markClip('out');});

  function fail(error){announce(error?.message||String(error),true);}
  function announce(message,isError=false){status.textContent=message;status.classList.toggle('seq-error',isError);onStatus?.(message);}
  function draft(){return checkedTimeline(experimentControls.getTimeline());}
  function safeDraft(){try{return draft();}catch(error){fail(error);return{schema_version:1,blocks:[]};}}
  function plotWidth(){return Math.max(300,Math.round(Math.max(300,viewport.clientWidth-LABEL_WIDTH)*zoom));}
  function toX(time){return time/Math.max(1,duration)*plotWidth();}
  function step(delta){if(!times.length)return;const i=nearestSampleIndex(times,cursor);seek(times[Math.max(0,Math.min(times.length-1,i+delta))]);}
  function seek(time){
    replay=null;
    if(times.length){const index=nearestSampleIndex(times,time);cursor=times[index];onSeek?.(cursor);}
    else cursor=Math.max(0,Math.min(duration,time));
    setTime(cursor);
  }
  function attachScrub(surface){surface.addEventListener('pointerdown',event=>{
    if(event.button!==0||event.target.closest('button,input,select'))return;
    event.preventDefault();surface.setPointerCapture(event.pointerId);
    const move=point=>{const rect=surface.getBoundingClientRect();seek(timeAtPixel(point.clientX-rect.left,rect.width,0,duration));};
    const finish=()=>{surface.removeEventListener('pointermove',move);surface.removeEventListener('pointerup',finish);surface.removeEventListener('pointercancel',finish);};
    surface.addEventListener('pointermove',move);surface.addEventListener('pointerup',finish);surface.addEventListener('pointercancel',finish);move(event);
  });}
  function renderSignalPicker(){
    const query=search.value.trim().toLowerCase(),old=signalPicker.value;
    const matches=catalog.filter(item=>!curves.some(curve=>curve.id===item.id)&&`${item.label} ${item.group||''} ${item.unit||''}`.toLowerCase().includes(query));
    signalPicker.replaceChildren(...matches.slice(0,250).map(item=>new Option(`${item.group?item.group+' · ':''}${item.label}${item.unit?' ('+item.unit+')':''}`,item.id)));
    if(matches.some(item=>item.id===old))signalPicker.value=old;
    if(!matches.length)signalPicker.add(new Option(times.length?'No matching signal':'Load a recording first',''));
    addCurve.disabled=!matches.length||curves.length>=8;signalPicker.disabled=!matches.length;
    signalPicker.title=matches.length>250?`${matches.length} matches · narrow your search`:'Signals from the loaded recording';
  }
  async function addSignal(id,{quiet=false}={}){
    if(!id||curves.some(curve=>curve.id===id)||curves.length>=8)return;
    const expectedRun=runId,ticket=generation,entry={id,loading:true,color:COLORS[curves.length%COLORS.length]};curves.push(entry);renderSignalPicker();renderTracks();
    try{
      const signal=await resolveSignal(id);
      if(disposed||ticket!==generation||expectedRun!==runId||!curves.includes(entry))return;
      if(signal.runId!==expectedRun)throw Error('The signal belongs to a different recording.');
      if(signal.timeMs.length!==signal.values.length)throw Error('Signal sample times and values do not match.');
      Object.assign(entry,signal,{loading:false});renderTracks();if(!quiet)announce(`${signal.label} added · saved sample times.`);
    }catch(error){if(ticket!==generation||disposed)return;curves=curves.filter(curve=>curve!==entry);renderTracks();renderSignalPicker();fail(error);}
  }
  function groupHeading(label,detail,className){const row=element('div',undefined,`seq-group ${className}`);row.append(element('strong',label),element('span',detail));plane.append(row);}
  function makeRow(label,subtitle,className=''){
    const row=element('div',undefined,`seq-row ${className}`),name=element('div',undefined,'seq-track-name'),body=element('div',undefined,'seq-track-body');
    name.append(element('strong',label));if(subtitle)name.append(element('small',subtitle));row.append(name,body);plane.append(row);attachScrub(body);return{row,name,body};
  }
  function togglePlay(){if(liveActive)return;replay=null;onPlay?.(!getState?.()?.playing);}
  function playClip(clip,context=false){
    if(liveActive)return;
    const bounds=clipReplayBounds(times,clip.start_ms,clip.end_ms,{context});if(!bounds)return;
    replay=null;onPlay?.(false);seek(bounds.start_ms);replay=bounds;
    if(bounds.end_ms>bounds.start_ms)onPlay?.(true);
    announce(`${clip.label||'Clip'} · ${format(bounds.start_ms)}–${format(bounds.end_ms)} ms${context?' · one sample context per side':''}`);
  }
  function markClip(edge){if(!times.length||liveActive)return;const time=times[nearestSampleIndex(times,cursor)];if(edge==='in')clipIn=time;else clipOut=time;announce(`Clip ${edge==='in'?'start':'end'}: ${format(time)} ms`);renderTracks();}
  function clipKey(){return `cognesia.timeline.clips.v1:${runId}`;}
  function saveMarkedClip(){
    if(liveActive||!times.length||clipIn===null||clipOut===null||clipOut<=clipIn){announce('Set In and Out at two different saved frames, in that order.');return;}
    const clip={id:`clip-${Date.now()}-${savedClips.length}`,label:`Clip ${savedClips.length+1}`,start_ms:clipIn,end_ms:clipOut};savedClips.push(clip);
    let persisted=true;try{localStorage.setItem(clipKey(),JSON.stringify(savedClips));}catch{persisted=false;}
    clipIn=clipOut=null;renderTracks();announce(persisted?'Clip saved. Double-click it to replay.':'Clip added for this session. Double-click it to replay.');
  }
  function clipBar(body,clip,{className='',context=false,top=4,source='clip'}={}){
    const bar=button(clip.label||'Response',()=>{selected={source,event:clip};renderInspector();});
    bar.className=`seq-event seq-replay-clip ${className}`;bar.style.left=`${toX(clip.start_ms)}px`;bar.style.width=`${Math.max(8,toX(clip.end_ms-clip.start_ms))}px`;bar.style.top=`${top}px`;
    bar.title=`${clip.label||'Response'} · ${format(clip.start_ms)}–${format(clip.end_ms)} ms · double-click to replay${context?' with one sample context per side':''}`;bar.setAttribute('aria-label',bar.title);bar.dataset.source=source;
    bar.addEventListener('dblclick',event=>{event.preventDefault();playClip(clip,context);});bar.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();playClip(clip,context);}});body.append(bar);return bar;
  }
  function clipLane(){
    if(!times.length)return;
    const {body}=makeRow('Replay clips','','seq-clips');
    clipBar(body,{label:summary.label||'Complete run',start_ms:times[0],end_ms:times.at(-1),provenance:'Complete saved model-time interval'},{className:'seq-run-clip'});
    savedClips.forEach((clip,i)=>clipBar(body,clip,{top:31+i*27}));body.style.height=`${32+savedClips.length*27}px`;
    if(clipIn!==null||clipOut!==null){const selection=element('span',undefined,'seq-marked-range');selection.style.left=`${toX(clipIn??0)}px`;selection.style.width=`${Math.max(2,toX((clipOut??duration)-(clipIn??0)))}px`;body.append(selection);}
  }
  function responseLanes(){
    if(!summary)return;
    const group=element('div',undefined,'seq-group seq-response-group');
    const population=responseAreas[0]?.kind==='type'||(!summary.region_traces?.length&&summary.traces?.length),reference=responseAreas[0]?.reference;
    const heading=element('strong',population?'Cell-type responses':'Brain responses');group.append(heading,element('span',`|ΔV| ≥ ${compact(thresholdMv)} mV${reference==='first saved sample'?' · vs first sample':reference?' · vs baseline':''}`));
    group.title='Threshold crossings in saved region mean voltage; these do not establish causal propagation.';
    if(responseAreas.length>4)group.append(button(showAllAreas?'Show fewer':`All ${responseAreas.length} ${population?'types':'areas'}`,()=>{showAllAreas=!showAllAreas;renderTracks();}));
    plane.append(group);
    if(!responseAreas.length){const {body}=makeRow('Area activity','','seq-response-empty');body.append(element('span',summary.region_traces?.length||summary.traces?.length?'No saved population crosses this threshold.':'No area or population voltage samples saved.','seq-empty'));return;}
    for(const area of showAllAreas?responseAreas:responseAreas.slice(0,4)){
      const label=area.kind==='type'?area.name:regionLabel(area.name),{body,name}=makeRow(label,'','seq-response');name.title=`${label} · relative to ${area.reference}`;
      for(const clip of area.clips){const event={...clip,label,reference:area.reference,threshold_mv:area.threshold_mv,signalId:area.signalId,provenance:`Saved ${area.kind==='type'?'cell-type':'region'} mean voltage relative to ${area.reference}. Threshold crossing, not a causal pathway.`};
        const bar=clipBar(body,event,{className:'seq-response-clip',context:true,source:'response'});bar.title+=` · peak ΔV ${compact(clip.peak_mv)} mV vs ${area.reference}`;
      }
    }
  }
  function eventLanes(events,source){
    for(const kind of SEQUENCE_KINDS){const list=events.filter(event=>event.kind===kind);if(!list.length)continue;
      const {body}=makeRow(SEQUENCE_LABELS[kind],'',`seq-${source}`),ends=[];
      const sorted=[...list].sort((a,b)=>a.start_ms-b.start_ms);
      for(const event of sorted){let lane=ends.findIndex(end=>end<=event.start_ms);if(lane<0)lane=ends.length;ends[lane]=Math.max(event.end_ms,event.start_ms+duration/plotWidth()*16);
        const bar=button(eventLabel(event),()=>{selected={source,index:event.sourceIndex,event};renderInspector();highlightSelection();});bar.className=`seq-event seq-kind-${kind}${kind==='checkpoint'?' seq-point':''}${event.baseInput?' seq-base-event':''}`;
        bar.style.left=`${toX(event.start_ms)}px`;bar.style.top=`${lane*28+(kind==='checkpoint'?9:4)}px`;bar.style.width=`${kind==='checkpoint'?14:Math.max(14,toX(event.duration_ms))}px`;
        bar.title=`${eventLabel(event)} · ${format(event.start_ms)}–${format(event.end_ms)} ms · ${source==='draft'?'next run':event.provenance}`;
        bar.dataset.source=source;if(Number.isInteger(event.sourceIndex))bar.dataset.index=event.sourceIndex;
        bar.setAttribute('aria-label',bar.title);
        if(source==='recorded')bar.addEventListener('dblclick',()=>playClip(event));
        if(source==='draft'){
          const resize=element('span','', 'seq-resize');resize.title='Drag to change duration';if(kind!=='checkpoint')bar.append(resize);
          attachEventDrag(bar,resize,event);bar.addEventListener('keydown',e=>{
            if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();removeEvent(event.sourceIndex);}
            if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();const doc=draft(),start=doc.blocks[event.sourceIndex].start_ms+(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?10:1);commit(event.sourceIndex,{start_ms:Math.max(0,start)});}
          });
        }
        body.append(bar);
      }
      body.style.height=`${Math.max(1,ends.length)*28+8}px`;
    }
  }
  function attachEventDrag(bar,handle,event){bar.addEventListener('pointerdown',pointer=>{
    if(pointer.button!==0)return;pointer.preventDefault();pointer.stopPropagation();bar.setPointerCapture(pointer.pointerId);
    const doc=draft(),original=doc.blocks[event.sourceIndex],origin=pointer.clientX,resizing=pointer.target===handle;
    const repeatOffset=event.start_ms-original.start_ms;let patch=null;
    const move=point=>{const delta=Math.round((point.clientX-origin)*duration/plotWidth());patch=resizing?{duration_ms:Math.max(1,original.duration_ms+delta)}:{start_ms:Math.max(0,original.start_ms+delta)};
      bar.style.left=`${toX((patch.start_ms??original.start_ms)+repeatOffset)}px`;bar.style.width=`${event.kind==='checkpoint'?14:Math.max(14,toX(patch.duration_ms??original.duration_ms))}px`;
      status.textContent=`${eventLabel(original)} · ${format(patch.start_ms??original.start_ms)} ms start · ${format(patch.duration_ms??original.duration_ms)} ms duration${event.repetition?' · editing every repetition':''}`;
    };
    const finish=point=>{bar.removeEventListener('pointermove',move);bar.removeEventListener('pointerup',finish);bar.removeEventListener('pointercancel',finish);selected={source:'draft',index:event.sourceIndex};if(point.type!=='pointercancel'&&patch)commit(event.sourceIndex,patch);else render();};
    bar.addEventListener('pointermove',move);bar.addEventListener('pointerup',finish);bar.addEventListener('pointercancel',finish);
  });}
  function commit(index,patch){try{experimentControls.setTimeline(editTimelineEvent(draft(),index,patch));renderInspector();}catch(error){fail(error);}}
  function removeEvent(index){try{const doc=draft();doc.blocks.splice(index,1);selected=null;experimentControls.setTimeline(doc);renderInspector();}catch(error){fail(error);}}
  function highlightSelection(){for(const bar of plane.querySelectorAll('.seq-event'))bar.classList.toggle('selected',selected?.source===bar.dataset.source&&selected?.source==='draft'&&String(selected.index)===bar.dataset.index);}
  function renderTracks(){
    if(disposed||rendering)return;rendering=true;const left=viewport.scrollLeft,top=viewport.scrollTop;
    try{
      const doc=safeDraft(),draftEvents=expandTimeline(doc),savedEvents=recordedProtocol(summary),context=experimentControls.getTimelineContext?.()||{};
      root.classList.add('seq-compact');repeatLabel.hidden=mode==='curves'||mode==='recording';
      duration=Math.max(1,liveActive?liveTime:0,summary&&mode!=='draft'?0:Number(context.duration_ms)||1000,Number(summary?.stimulus?.duration_ms)||0,times.at(-1)||0,...(['recording','curves'].includes(mode)?[]:draftEvents.map(e=>e.end_ms)),...savedEvents.map(e=>e.end_ms));
      plane.style.width=`${plotWidth()+LABEL_WIDTH}px`;plane.replaceChildren();curveGrid.replaceChildren();
      const ruler=makeRow('TIME · ms','','seq-ruler');ruler.body.setAttribute('role','slider');ruler.body.tabIndex=0;ruler.body.setAttribute('aria-label','Recorded activity playhead');ruler.body.setAttribute('aria-valuemin','0');ruler.body.setAttribute('aria-valuemax',String(duration));
      ruler.body.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();step(e.key==='ArrowLeft'?-1:1);}});
      for(const t of rulerTicks(0,duration,Math.max(4,plotWidth()/90))){const tick=element('span',format(t),'seq-tick');tick.style.left=`${toX(t)}px`;ruler.body.append(tick);}
      if(liveActive){const {body}=makeRow('Simulation','','seq-live');body.append(element('span','Running · response clips and curves appear when the run is saved.','seq-empty'));plane.append(playhead);updateTime();return;}
      if(mode!=='draft'){
        if(mode==='both')groupHeading('RESULTS',summary?.label||'No results loaded','seq-recorded-group');
        eventLanes(savedEvents,'recorded');clipLane();responseLanes();
      }
      if(mode==='draft'||mode==='both'){
        if(mode==='both')groupHeading('NEXT RUN',doc.name||'Experiment','seq-draft-group');
        eventLanes(draftEvents,'draft');
        if(!draftEvents.length){const empty=makeRow('Stimuli','','seq-draft');empty.body.append(element('span','Use + to add timed stimuli. The experiment settings supply the continuous input.','seq-empty'));}
      }
      plane.append(curveGrid);
      for(const curve of curves)renderCurve(curve);
      if(!curves.length)curveGrid.append(element('p',summary?'Choose a signal to add a chart.':'Load a recording to add charts.','seq-empty'));
      plane.append(playhead);highlightSelection();viewport.scrollLeft=left;viewport.scrollTop=top;updateTime();
    }catch(error){fail(error);}finally{rendering=false;}
  }
  function renderCurve(curve){
    const label=curve.label||catalog.find(item=>item.id===curve.id)?.label||'Loading signal';
    const row=element('article',undefined,'seq-row seq-curve-row seq-curve-card'),name=element('div',undefined,'seq-track-name'),body=element('div',undefined,'seq-track-body seq-curve-plot');
    row.dataset.signalId=curve.id;row.dataset.runId=curve.runId||runId||'';row.id=curveCardId(row.dataset.runId,curve.id);
    row.style.setProperty('--curve-color',curve.color);name.append(element('strong',label));row.append(name,body);curveGrid.append(row);attachScrub(body);
    const value=element('output','—','seq-curve-value');name.append(value);curve.valueNode=value;
    if(onAnalyzeSignal){const analyze=button('Analyze',()=>Promise.resolve(onAnalyzeSignal(curve.id)).catch(fail),'Interval, frequency, and curve analysis');analyze.className='seq-analyze';name.append(analyze);}
    const remove=button('×',()=>{curves=curves.filter(item=>item!==curve);renderSignalPicker();renderTracks();},'Remove this curve');remove.className='seq-remove';remove.setAttribute('aria-label',`Remove ${label}`);name.append(remove);
    if(curve.loading){body.append(element('span','Loading samples…','seq-empty'));return;}
    const canvas=element('canvas');canvas.setAttribute('aria-label',`${label}, ${curve.values.length} saved samples in ${curve.unit}`);body.append(canvas);
    const width=plotWidth(),height=86,ratio=Math.min(2,window.devicePixelRatio||1),range=duration;
    canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);canvas.style.width=`${width}px`;canvas.style.height=`${height}px`;
    const ctx=canvas.getContext('2d');if(!ctx)return;ctx.scale(ratio,ratio);ctx.fillStyle='#15181d';ctx.fillRect(0,0,width,height);
    if(curve.rangeCache?.duration!==range){let min=Infinity,max=-Infinity;for(let i=0;i<curve.values.length;i++)if(curve.timeMs[i]>=0&&curve.timeMs[i]<=range&&Number.isFinite(curve.values[i])){min=Math.min(min,curve.values[i]);max=Math.max(max,curve.values[i]);}curve.rangeCache={duration:range,min,max};}
    const {min,max}=curve.rangeCache;if(!Number.isFinite(min)){body.append(element('span','No samples in this interval','seq-empty'));return;}
    const pad=min===max?Math.max(1,Math.abs(min)*.05):(max-min)*.12,lo=min-pad,hi=max+pad,x=time=>time/range*width,y=value=>10+(hi-value)/(hi-lo)*(height-20);
    ctx.strokeStyle='#2c3440';ctx.lineWidth=.7;ctx.font='9px system-ui';ctx.fillStyle='#8d99ab';ctx.beginPath();
    for(const t of rulerTicks(0,range,Math.max(4,width/90))){ctx.moveTo(x(t),0);ctx.lineTo(x(t),height);}
    for(const v of rulerTicks(lo,hi,3)){ctx.moveTo(0,y(v));ctx.lineTo(width,y(v));ctx.textAlign='left';ctx.fillText(formatSignalValue(v,hi-lo),5,y(v)-3);}
    ctx.stroke();
    if(lo<=0&&hi>=0){ctx.strokeStyle='#495666';ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(0,y(0));ctx.lineTo(width,y(0));ctx.stroke();ctx.setLineDash([]);}
    ctx.strokeStyle=curve.color;ctx.fillStyle=curve.color;ctx.lineWidth=1.3;
    if(curve.segmentCache?.duration!==range||curve.segmentCache?.width!==width)curve.segmentCache={duration:range,width,segments:signalSegments(curve.timeMs,curve.values,0,range,width)};
    for(const indices of curve.segmentCache.segments){ctx.beginPath();indices.forEach((i,j)=>{if(j)ctx.lineTo(x(curve.timeMs[i]),y(curve.values[i]));else ctx.moveTo(x(curve.timeMs[i]),y(curve.values[i]));});ctx.stroke();
      if(indices.length===1){const i=indices[0];ctx.beginPath();ctx.arc(x(curve.timeMs[i]),y(curve.values[i]),2,0,2*Math.PI);ctx.fill();}}
    row.title=`${curve.description||label} · scale ${formatSignalValue(lo,hi-lo)}–${formatSignalValue(hi,hi-lo)} ${curve.unit||''}`;
  }
  function formField(label,value,handler,{type='number',min,step='.1'}={}){
    const field=element('label',undefined,'seq-field');field.append(element('span',label));const input=element('input');input.type=type;input.value=value??'';if(min!=null)input.min=min;if(type==='number')input.step=step;
    input.addEventListener('change',()=>{const next=type==='number'?Number(input.value):input.value;if(type==='number'&&!Number.isFinite(next)){fail(Error('Enter a finite number.'));return;}handler(next);});field.append(input);return field;
  }
  function targetField(label,target,onChange,{optional=false}={}){
    const field=element('label',undefined,'seq-field seq-target-field');field.append(element('span',label));
    const kind=target?.kind||'indices',text=element('input');text.type='text';text.setAttribute('aria-label',label+' identifiers');
    text.value=(target?.indices||target?.root_ids||target?.entity_ids||target?.values)?.join(', ')??target?.name??'';
    const picker=select([['indices','Simulated neuron indices'],['root_ids','Exact neuron IDs'],['entity_ids','Source-qualified IDs'],['group','Cell types'],['region','Brain region'],['body_zone','Body afferents']],kind,()=>{text.placeholder=['region','body_zone'].includes(picker.value)?'Exact region name':'Comma-separated identifiers';apply();});picker.setAttribute('aria-label',label+' selection method');
    const apply=()=>{try{const key=picker.value,values=text.value.split(',').map(v=>v.trim()).filter(Boolean);if(!values.length){if(optional){onChange(undefined);return;}throw Error('Enter at least one target identifier.');}
      if(key==='indices'&&values.some(v=>!/^\d+$/.test(v)))throw Error('Neuron indices must be nonnegative integers.');
      onChange(key==='indices'?{kind:key,indices:values.map(Number)}:['root_ids','entity_ids'].includes(key)?{kind:key,[key]:values}:key==='group'?{kind:key,field:'cell_type',values}:{kind:key,name:text.value.trim()});
    }catch(error){fail(error);}};
    text.addEventListener('change',apply);field.append(picker,text);return field;
  }
  function renderInspector(){
    inspector.replaceChildren();inspector.hidden=!selected;if(!selected)return;
    if(['recorded','clip','response'].includes(selected.source)){
      const event=selected.event;inspector.append(element('strong',eventLabel(event)),element('span',`${format(event.start_ms)}–${format(event.end_ms)} ms${event.provenance?' · '+event.provenance:''}`),button('Close',()=>{selected=null;renderInspector();}));
      inspector.append(button('Replay',()=>playClip(event,selected.source==='response')));
      if(selected.source==='response')inspector.append(button('+ Curve',()=>addSignal(event.signalId)));
      if(selected.source==='clip'&&event.id)inspector.append(button('Remove clip',()=>{savedClips=savedClips.filter(clip=>clip.id!==event.id);try{localStorage.setItem(clipKey(),JSON.stringify(savedClips));}catch{}selected=null;render();}));
      const details=element('details');details.append(element('summary','Saved event details'),element('pre',JSON.stringify(event,null,2)));inspector.append(details);return;
    }
    const doc=safeDraft(),index=selected.index,event=doc.blocks[index];if(!event){selected=null;inspector.hidden=true;return;}
    inspector.append(element('strong',`Next run · ${SEQUENCE_LABELS[event.kind]}`),formField('Start · ms',event.start_ms,v=>commit(index,{start_ms:v}),{min:0,step:'1'}));
    if(event.kind!=='checkpoint')inspector.append(formField('Duration · ms',event.duration_ms,v=>commit(index,{duration_ms:v}),{min:1,step:'1'}));
    inspector.append(formField('Label',event.label||'',v=>commit(index,{label:v}),{type:'text'}));
    if(event.kind==='visual'){
      const chooser=select([['grating','Moving grating'],['flash','Flash'],['edge','Moving edge'],['looming','Looming disc'],['dark','Dark']],event.options?.stimulus||'grating',v=>commit(index,{options:{...event.options,stimulus:v}}));chooser.setAttribute('aria-label','Visual stimulus');inspector.append(chooser,formField('Contrast',event.options?.contrast??1,v=>commit(index,{options:{...event.options,contrast:v}}),{min:0,step:'.05'}));
    }
    if(event.kind==='chemical'){
      const chooser=select(['DA','OA','5HT','NO','sNPF','peptide_pool','TA','ACh'].map(v=>[v,v]),event.species,v=>commit(index,{species:v}));chooser.setAttribute('aria-label','Chemical species');inspector.append(chooser,formField('Held level · a.u.',event.level,v=>commit(index,{level:v}),{min:0}));
    }
    if(event.kind==='enzyme'){
      const chooser=select(['AChE','ChAT','Tbh'].map(v=>[v,v]),event.enzyme_id,v=>commit(index,{enzyme_id:v}));chooser.setAttribute('aria-label','Enzyme');inspector.append(chooser,formField('Relative activity',event.activity,v=>commit(index,{activity:v}),{min:0}));
    }
    if(event.kind==='electrode')inspector.append(targetField('Target',event.electrode?.target,v=>commit(index,{electrode:{...event.electrode,target:v}})),formField('Drive · mV',event.electrode?.voltage_mv,v=>commit(index,{electrode:{...event.electrode,voltage_mv:v}})),formField('Frequency · Hz',event.electrode?.frequency_hz||0,v=>commit(index,{electrode:{...event.electrode,frequency_hz:v}}),{min:0}));
    if(event.kind==='intervention'){
      const effect=event.intervention||{kind:'silence'},patch=value=>commit(index,{intervention:{...effect,...value}});
      const picker=select([['silence','Silence future output'],['edge_scale','Scale connections'],['receptor_block','Block receptor']],effect.kind,kind=>commit(index,{intervention:kind==='silence'?{kind,target:effect.target||effect.pre||{kind:'indices',indices:[0]}}:kind==='edge_scale'?{kind,pre:effect.target||effect.pre||{kind:'indices',indices:[0]},factor:0}:{kind,receptor_id:'',factor:0}}));picker.setAttribute('aria-label','Intervention effect');inspector.append(picker);
      if(effect.kind==='silence')inspector.append(targetField('Target',effect.target,target=>patch({target})));
      if(effect.kind==='edge_scale')inspector.append(targetField('From neurons',effect.pre,pre=>patch({pre})),targetField('To neurons (blank = all)',effect.post,post=>patch({post}),{optional:true}),formField('Strength multiplier',effect.factor??0,factor=>patch({factor}),{min:0}));
      if(effect.kind==='receptor_block')inspector.append(formField('Receptor identifier',effect.receptor_id,v=>patch({receptor_id:v}),{type:'text'}),formField('Remaining gain',effect.factor??0,factor=>patch({factor}),{min:0}));
    }
    inspector.append(button('Remove event',()=>removeEvent(index)),button('Close',()=>{selected=null;renderInspector();highlightSelection();}));
    const details=element('details',undefined,'seq-advanced');details.append(element('summary','Targets and all event parameters'));
    const editor=element('textarea');editor.value=JSON.stringify(event,null,2);editor.rows=8;editor.spellcheck=false;editor.setAttribute('aria-label','Event parameters as JSON');
    details.append(element('p','Edit event fields. Timing and conflicts are checked before Run.'),editor,button('Apply parameters',()=>{try{const next=JSON.parse(editor.value),updated=draft();updated.blocks[index]=next;experimentControls.setTimeline(checkedTimeline(updated));announce('Event parameters saved.');}catch(error){fail(error);}}));inspector.append(details);
  }
  function updateTime(){
    const hasRecording=times.length>0&&!liveActive;previous.disabled=next.disabled=play.disabled=!hasRecording;play.textContent=getState?.()?.playing?'Ⅱ':'▶';play.setAttribute('aria-label',getState?.()?.playing?'Pause recorded activity':'Play recorded activity');markIn.disabled=markOut.disabled=saveClip.disabled=!hasRecording;addCurve.disabled=liveActive||!signalPicker.value||curves.length>=8;
    timeLabel.textContent=`${format(cursor)} ms`;timeLabel.title=liveActive?`Live model time · ${livePhase}`:hasRecording?`Recorded sample ${nearestSampleIndex(times,cursor)+1} of ${times.length}`:'Next run cursor · no saved results';
    playhead.style.left=`${LABEL_WIDTH+toX(cursor)}px`;playhead.hidden=cursor<0||cursor>duration;
    const slider=plane.querySelector('[role="slider"]');if(slider){slider.setAttribute('aria-valuenow',String(cursor));slider.setAttribute('aria-valuetext',timeLabel.textContent);}
    for(const curve of curves){if(curve.loading||!curve.valueNode)continue;const i=nearestSampleIndex(curve.timeMs,cursor),outside=i<0||cursor<curve.timeMs[0]||cursor>curve.timeMs.at(-1);curve.valueNode.textContent=outside?'—':`${formatSignalValue(curve.values[i],(curve.rangeCache?.max??0)-(curve.rangeCache?.min??0))} ${curve.unit||''}`;curve.valueNode.title=outside?'No sample at this time':`Nearest saved sample: ${format(curve.timeMs[i])} ms`;
    }
  }
  function setTime(time){if(Number.isFinite(time))cursor=liveActive?liveTime:time;if(replay&&!getState?.()?.playing)replay=null;if(replay&&cursor>=replay.end_ms){const stop=replay.end_ms;replay=null;onPlay?.(false);if(cursor!==stop){cursor=stop;onSeek?.(stop);}}if(raf||disposed)return;raf=requestAnimationFrame(()=>{raf=0;updateTime();});}
  function setLiveFrame(frame){
    if(!frame){liveActive=false;livePhase='';refresh();return;}
    const changed=!liveActive||livePhase!==frame.phase;liveActive=true;livePhase=frame.phase||'simulation';liveTime=Number(frame.model_time_ms)||0;cursor=liveTime;replay=null;selected=null;if(changed&&getState?.()?.playing)onPlay?.(false);
    recordLabel.textContent='Running';recordLabel.title=`Live ${livePhase}; saved clips will be available after completion`;if(changed||liveTime>duration){render();}else setTime(liveTime);
  }
  function render(){renderTracks();renderInspector();}
  async function refresh(){
    if(disposed)return;const state=getState?.()||{},nextSummary=state.summary||null,nextId=getCurrentRunId?.()||nextSummary?.id||null;
    try{times=recordedTimes(nextSummary);}catch(error){times=[];fail(error);}summary=nextSummary;liveActive=!!(state.submitting||state.job);if(liveActive){if(state.liveFrame){liveTime=Number(state.liveFrame.model_time_ms)||0;livePhase=state.liveFrame.phase||'simulation';}else if(!livePhase){liveTime=0;livePhase='preparing';}}
    const changed=runId!==nextId;if(changed){generation++;curves=[];bootstrappedRun=null;selected=null;replay=null;clipIn=clipOut=null;runId=nextId;savedClips=[];try{const stored=JSON.parse(localStorage.getItem(clipKey())||'[]');if(Array.isArray(stored))savedClips=stored.filter(clip=>typeof clip.id==='string'&&typeof clip.label==='string'&&Number.isFinite(clip.start_ms)&&Number.isFinite(clip.end_ms)&&clip.end_ms>clip.start_ms&&clip.start_ms>=times[0]&&clip.end_ms<=times.at(-1));}catch{}}
    cursor=liveActive?liveTime:Number(getTime?.())||0;catalog=listSignals?.()||[];responseAreas=times.length?regionResponseClips(summary,{thresholdMv}):[];
    if(!modeChosen){mode=summary?'curves':'draft';modePicker.value=mode;}
    recordLabel.textContent=liveActive?'Running':summary?`${recordedModelName(summary)} · ${summary.label||runId||'Results'}`:'No results';recordLabel.title=liveActive?`Live ${livePhase}; saved clips will be available after completion`:summary?`${recordedModelName(summary)} · ${times.length.toLocaleString()} saved neural samples`:'Choose stimuli and review the next run';
    const doc=safeDraft();repeatInput.value=doc.repeat?.count||doc.repeat||1;renderSignalPicker();render();
    if(runId&&bootstrappedRun!==runId&&catalog.length){bootstrappedRun=runId;await Promise.all(defaultResponseSignals(catalog).map(item=>addSignal(item.id,{quiet:true})));}
  }
  const unsubscribe=experimentControls.subscribeTimeline?.(()=>{const doc=experimentControls.getTimeline(),signature=JSON.stringify(doc);if(signature===lastDraft)return;lastDraft=signature;repeatInput.value=doc.repeat?.count||doc.repeat||1;render();});
  const resizeObserver=typeof ResizeObserver==='undefined'?null:new ResizeObserver(()=>{const width=viewport.clientWidth;if(width&&width!==lastWidth){lastWidth=width;renderTracks();}});resizeObserver?.observe(viewport);
  refresh();
  return{refresh,setTime,setLiveFrame,dispose(){disposed=true;generation++;unsubscribe?.();resizeObserver?.disconnect();if(raf)cancelAnimationFrame(raf);root.remove();}};
}
