/* Timeline geometry uses model milliseconds and original recorded samples. */
export const SEQUENCE_KINDS = ['visual','rest','electrode','chemical','enzyme','intervention','checkpoint','recording'];
export const SEQUENCE_LABELS = {visual:'Sensory input',rest:'Rest',electrode:'Electrodes',chemical:'Chemical inputs',enzyme:'Enzymes',intervention:'Interventions',checkpoint:'Checkpoints',recording:'Recording windows'};
const copy = value => JSON.parse(JSON.stringify(value));
const number = (value,name) => {if(typeof value!=='number'||!Number.isFinite(value)||value<0)throw Error(`${name} must be finite and nonnegative.`);return value;};

export function checkedTimeline(value) {
  if(!value||value.schema_version!==1||!Array.isArray(value.blocks)||value.blocks.length>512)throw Error('Expected a version 1 timeline with at most 512 events.');
  const timeline=copy(value);
  timeline.blocks.forEach(block=>{
    if(!SEQUENCE_KINDS.includes(block.kind))throw Error('Unknown experiment event kind.');
    number(block.start_ms,'Start');number(block.duration_ms,'Duration');
    if(block.kind!=='checkpoint'&&block.duration_ms===0)throw Error('An event needs a positive duration.');
    if(block.kind==='checkpoint')block.duration_ms=0;
  });
  const repeat=timeline.repeat??1,count=typeof repeat==='object'?repeat.count:repeat;
  if(!Number.isInteger(count)||count<1||count>100)throw Error('Repeat count must be an integer from 1 to 100.');
  if(typeof repeat==='object'){number(repeat.interval_ms,'Repeat interval');if(repeat.interval_ms===0)throw Error('Repeat interval must be positive.');}
  if(count*timeline.blocks.length>4096)throw Error('Expanded timeline exceeds 4096 events.');
  return timeline;
}

export function expandTimeline(value) {
  const timeline=checkedTimeline(value),repeat=timeline.repeat??1,count=typeof repeat==='object'?repeat.count:repeat;
  const span=Math.max(0,...timeline.blocks.map(b=>b.start_ms+b.duration_ms));
  const interval=typeof repeat==='object'?repeat.interval_ms:span;
  return Array.from({length:count},(_,repetition)=>timeline.blocks.map((block,index)=>({...block,
    sourceIndex:index,repetition,start_ms:block.start_ms+repetition*interval,end_ms:block.start_ms+block.duration_ms+repetition*interval}))).flat();
}

export function editTimelineEvent(value,index,patch,{quantumMs=1}={}) {
  const timeline=checkedTimeline(value);
  if(!Number.isInteger(index)||!timeline.blocks[index])throw Error('This event no longer exists.');
  if(!Number.isFinite(quantumMs)||quantumMs<=0)throw Error('Invalid timeline clock.');
  const block={...timeline.blocks[index],...copy(patch)};
  block.start_ms=Math.max(0,Math.round(number(block.start_ms,'Start')/quantumMs)*quantumMs);
  block.duration_ms=block.kind==='checkpoint'?0:Math.max(quantumMs,Math.round(number(block.duration_ms,'Duration')/quantumMs)*quantumMs);
  timeline.blocks[index]=block;
  return checkedTimeline(timeline);
}

export function nearestSampleIndex(times,timeMs) {
  if(!times?.length||!Number.isFinite(timeMs))return -1;
  let low=0,high=times.length;
  while(low<high){const mid=(low+high)>>>1;if(times[mid]<timeMs)low=mid+1;else high=mid;}
  if(!low)return 0;if(low===times.length)return low-1;
  return timeMs-times[low-1]<=times[low]-timeMs?low-1:low;
}

export function recordedTimes(summary) {
  const times=summary?.frames?.time_ms;
  if(!Array.isArray(times)&&!ArrayBuffer.isView(times))return [];
  for(let i=0;i<times.length;i++)if(!Number.isFinite(times[i])||(i&&times[i]<=times[i-1]))throw Error('The recording has invalid sample times.');
  return times;
}

export function rulerTicks(start,end,count=8) {
  if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start)return [];
  const ideal=(end-start)/Math.max(2,count),power=10**Math.floor(Math.log10(ideal));
  const step=([1,2,5,10].find(n=>n*power>=ideal)||10)*power,ticks=[];
  for(let t=Math.ceil(start/step)*step;t<=end+step*1e-8;t+=step)ticks.push(Number(t.toPrecision(12)));
  return ticks;
}

export function timeAtPixel(pixel,width,start,end) {
  return start+Math.max(0,Math.min(1,pixel/Math.max(1,width)))*(end-start);
}

export function curveCardGeometry(width,height=184) {
  const left=46,right=12,top=10,bottom=24; width=Math.max(120,width);
  return{width,height,left,right,top,bottom,plotWidth:Math.max(1,width-left-right),plotHeight:Math.max(1,height-top-bottom)};
}

export function curveCardTime(pixel,geometry,endMs) {
  return timeAtPixel(pixel-geometry.left,geometry.plotWidth,0,endMs);
}

export function curveCardId(runId,signalId) {
  return 'seq-curve-'+Array.from(`${runId}\u0000${signalId}`,character=>character.codePointAt(0).toString(16)).join('-');
}

export function signalSegments(timeMs,values,start,end,pixels) {
  if(timeMs.length!==values.length||!timeMs.length)return [];
  const intervals=[];for(let i=1;i<timeMs.length;i++)intervals.push(timeMs[i]-timeMs[i-1]);
  intervals.sort((a,b)=>a-b);const gap=(intervals[Math.floor(intervals.length/2)]||Infinity)*2.5;
  const groups=[];let current=[],previous=-1;
  for(let i=0;i<timeMs.length;i++){
    if(timeMs[i]<start||timeMs[i]>end)continue;
    if(!Number.isFinite(values[i])){if(current.length)groups.push(current);current=[];previous=-1;continue;}
    if(previous>=0&&timeMs[i]-timeMs[previous]>gap){groups.push(current);current=[];}
    current.push(i);previous=i;
  }
  if(current.length)groups.push(current);
  return groups.map(indices=>{
    if(indices.length<=pixels*2)return indices;
    const bins=new Map();
    for(const i of indices){const bin=Math.floor((timeMs[i]-start)/Math.max(Number.EPSILON,end-start)*Math.max(1,pixels));const bucket=bins.get(bin)||[];bucket.push(i);bins.set(bin,bucket);}
    const kept=new Set([indices[0],indices.at(-1)]);
    for(const bucket of bins.values()){
      let min=bucket[0],max=min;for(const i of bucket){if(values[i]<values[min])min=i;if(values[i]>values[max])max=i;}kept.add(min);kept.add(max);
    }
    return [...kept].sort((a,b)=>a-b);
  });
}

export function recordedProtocol(summary) {
  if(!summary)return [];
  const metadata=summary.metadata||{},duration=Number(summary.stimulus?.duration_ms)||Number(summary.frames?.time_ms?.at(-1))||0;
  const saved=metadata.session?.timeline;
  let events=[];
  if(saved)events=expandTimeline({schema_version:1,...saved,blocks:saved.blocks.map(b=>({...b,start_ms:b.start_ms??b.t_ms??0,duration_ms:b.duration_ms??b.dur_ms??0}))}).map(b=>({...b,provenance:'saved protocol'}));
  if(duration>0&&summary.stimulus?.type!=='partial')events.unshift({kind:'visual',start_ms:0,end_ms:duration,duration_ms:duration,
    label:`${summary.stimulus?.type||summary.stimulus?.stimulus||'Input'} · saved base input`,baseInput:true,provenance:'saved input parameters'});
  const origin=Number(metadata.input_origin_ms)||0;
  for(const e of summary.stimulation?.definitions||[]){
    const start=Math.max(0,Number(e.start_ms)-origin),end=Math.min(duration,Number(e.end_ms)-origin);
    const sameTarget=b=>JSON.stringify(b.electrode?.target)===JSON.stringify(e.target)&&['frequency_hz','duty_percent','phase_deg'].every(key=>(b.electrode?.[key]??(key==='duty_percent'?50:0))===(e[key]??(key==='duty_percent'?50:0)));
    if(end>start&&!events.some(b=>b.kind==='electrode'&&b.start_ms===start&&b.end_ms===end&&sameTarget(b)&&b.electrode?.voltage_mv===e.voltage_mv))events.push({kind:'electrode',start_ms:start,end_ms:end,duration_ms:end-start,electrode:e,label:e.label||e.id||'Saved electrode',provenance:'saved electrode waveform definition'});
  }
  for(const e of metadata.session?.interventions||[])events.push({kind:'intervention',start_ms:e.start_ms||0,end_ms:e.end_ms??duration,duration_ms:(e.end_ms??duration)-(e.start_ms||0),intervention:e,provenance:'saved intervention'});
  const offset=(Number(metadata.pre_equilibration_ms)||0)+origin;
  for(const e of metadata.session_events||[]){const t=e.model_time_ms-offset;
    if(e.phase==='stimulus'&&e.checkpoint_id&&Number.isFinite(t)&&t>=0&&t<=duration)events.push({kind:'checkpoint',start_ms:t,end_ms:t,duration_ms:0,label:e.action==='pause'?'Paused checkpoint':'Saved checkpoint',checkpoint_id:e.checkpoint_id,provenance:'recorded checkpoint event'});
  }
  return events;
}

export function eventLabel(event) {
  if(event.label)return event.label;
  if(event.kind==='visual')return event.options?.stimulus||'Visual input';
  if(event.kind==='chemical')return `${event.species||'Chemical'} · ${event.level??'?'} a.u.`;
  if(event.kind==='enzyme')return `${event.enzyme_id||'Enzyme'} · ${event.activity??'?'}×`;
  if(event.kind==='electrode')return `${event.electrode?.voltage_mv??'?'} mV · electrode`;
  if(event.kind==='intervention')return (event.intervention?.kind||'Intervention').replaceAll('_',' ');
  return SEQUENCE_LABELS[event.kind]||event.kind;
}


/** Thresholded saved region means. These are response intervals, not causal paths. */
export function regionResponseClips(summary,{thresholdMv=.1}={}) {
  if(!Number.isFinite(thresholdMv)||thresholdMv<=0)throw Error('Response threshold must be positive, in mV.');
  const times=recordedTimes(summary);
  if(!times.length)return [];
  const hasBaseline=!!summary?.activity?.baseline_url;
  const intervals=Array.from(times).slice(1).map((t,i)=>t-times[i]).sort((a,b)=>a-b);
  const maximumGap=(intervals[Math.floor(intervals.length/2)]||Infinity)*2.5;
  const kind=summary.region_traces?.length?'region':'type',source=kind==='region'?summary.region_traces:summary.traces||[];
  return source.flatMap((trace,index)=>{
    const raw=trace.raw||trace.raw_mv;
    const paired=trace.values||trace.delta_mv;
    const reference=hasBaseline&&paired?'matched baseline':'first saved sample';
    const values=reference==='matched baseline'?paired:raw;
    if(!values||values.length!==times.length||(reference==='first saved sample'&&!Number.isFinite(values[0])))return [];
    const offset=reference==='matched baseline'?0:values[0],clips=[];
    let current=null;
    for(let i=0;i<times.length;i++){
      const value=values[i]-offset,active=Number.isFinite(value)&&Math.abs(value)>=thresholdMv;
      if(current&&(!active||(i&&times[i]-times[i-1]>maximumGap))){clips.push(current);current=null;}
      if(!active)continue;
      if(!current)current={start_ms:times[i],end_ms:times[i],peak_mv:value,sample_count:0};
      current.end_ms=times[i];current.sample_count++;
      if(Math.abs(value)>Math.abs(current.peak_mv))current.peak_mv=value;
    }
    if(current)clips.push(current);
    if(!clips.length)return [];
    return [{index,kind,name:trace.name||trace.label||`Area ${index+1}`,threshold_mv:thresholdMv,reference,
      signalId:`trace:${kind}:${index}:${reference==='matched baseline'?'delta':'raw'}`,clips:clips.map((clip,i)=>({...clip,id:`region-${index}-${i}`,duration_ms:clip.end_ms-clip.start_ms}))}];
  }).sort((a,b)=>a.clips[0].start_ms-b.clips[0].start_ms||a.name.localeCompare(b.name));
}

/** Clip bounds always resolve to saved frames; context is one saved frame on each side. */
export function clipReplayBounds(times,startMs,endMs,{context=false}={}) {
  if(!times.length||!Number.isFinite(startMs)||!Number.isFinite(endMs)||endMs<startMs)return null;
  let start=nearestSampleIndex(times,startMs),end=nearestSampleIndex(times,endMs);
  if(context){start=Math.max(0,start-1);end=Math.min(times.length-1,end+1);}
  return {start_ms:times[start],end_ms:times[end]};
}


/** Retain small changes around a large offset without rounding every tick alike. */
export function formatSignalValue(value,span=0) {
  if(!Number.isFinite(value))return '—';
  const width=Number.isFinite(span)?Math.abs(span):0;
  const relative=width>0?Math.ceil(Math.log10(Math.max(Math.abs(value),width))-Math.log10(width))+3:7;
  return Number(value.toPrecision(Math.max(7,Math.min(15,relative)))).toString();
}
