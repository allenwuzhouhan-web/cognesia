/** Keep source anatomy independent from recorded subsets and camera transforms. */
export function centeredAnatomy(positions, visibleIndices = null) {
  if (!positions || positions.length % 3) throw Error('Anatomy requires complete XYZ coordinates.');
  const count = positions.length / 3;
  const candidates = visibleIndices || Uint32Array.from({length:count}, (_,i)=>i);
  const visible = [], low = [Infinity,Infinity,Infinity], high = [-Infinity,-Infinity,-Infinity];
  for (const index of candidates) {
    if (!Number.isInteger(index) || index < 0 || index >= count) throw Error('Anatomical index is outside the source table.');
    const p = [0,1,2].map(k=>positions[3*index+k]);
    if (!p.every(Number.isFinite)) continue;
    visible.push(index);
    for (let k=0;k<3;k++) { low[k]=Math.min(low[k],p[k]); high[k]=Math.max(high[k],p[k]); }
  }
  if (!visible.length) throw Error('This source has no finite anatomical positions.');
  const offset = low.map((v,k)=>(v+high[k])/2), output = new Float32Array(positions.length);
  let radius = 0;
  for (const i of visible) {
    const p = offset.map((v,k)=>positions[i*3+k]-v);
    output.set(p, i*3); radius=Math.max(radius,Math.hypot(...p));
  }
  return {positions:output,visibleIndices:Uint32Array.from(visible),offset,radius:Math.max(radius,.01),
    bounds:[low.map((v,k)=>v-offset[k]),high.map((v,k)=>v-offset[k])]};
}

const unit = a => {const n=Math.hypot(...a);if(!(n>0))throw Error('Camera direction must be nonzero.');return a.map(v=>v/n);};
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const dot = (a,b) => a.reduce((s,v,i)=>s+v*b[i],0);
export function fittedCameraDistance(bounds, direction, up, fovDegrees, aspect, padding=1.12) {
  if (!(aspect>0) || !(fovDegrees>0&&fovDegrees<180)) throw Error('Camera viewport must have a positive aspect and valid field of view.');
  const forward=unit(direction),right=unit(cross(up,forward)),vertical=cross(forward,right);
  const tanY=Math.tan(fovDegrees*Math.PI/360)/padding,tanX=tanY*aspect;
  let distance=.01;
  for(let i=0;i<8;i++) {
    const p=[bounds[i&1][0],bounds[(i>>1)&1][1],bounds[(i>>2)&1][2]],depth=dot(p,forward);
    distance=Math.max(distance,Math.abs(dot(p,right))/tanX+depth,Math.abs(dot(p,vertical))/tanY+depth);
  }
  return distance;
}

export function recordingRowMap({fullCount,recordedCount,fullIdentities,recordedIdentities,
  fullModelHash,recordedModelHash,recordedIndices,parentIndices,allowReleasedOrder=false}) {
  if (fullModelHash && recordedModelHash && fullModelHash!==recordedModelHash) throw Error('Recording and anatomy use different source versions.');
  if (!Number.isInteger(fullCount)||!Number.isInteger(recordedCount)||fullCount<1||recordedCount<1) throw Error('Anatomy and recording counts must be positive integers.');
  let rows;
  if (fullIdentities && recordedIdentities) {
    if(fullIdentities.length!==fullCount||recordedIdentities.length!==recordedCount)throw Error('Source identity table length differs from its recording.');
    const key=item=>{if(typeof item.entity_id!=='string'||!item.entity_id)throw Error('Source-qualified neuron identity is required.');return item.entity_id;};
    const lookup=new Map(fullIdentities.map((item,i)=>[key(item),i]));
    if(lookup.size!==fullCount)throw Error('Full anatomy contains duplicate neuron identities.');
    rows=recordedIdentities.map(item=>lookup.get(key(item)));
  } else if (recordedIndices) rows=Array.from(recordedIndices,i=>parentIndices?parentIndices[i]:i);
  else if (allowReleasedOrder && fullCount===recordedCount) rows=Array.from({length:fullCount},(_,i)=>i);
  else throw Error('This recording has no verified mapping to the complete anatomy.');
  if(rows.length!==recordedCount||rows.some(i=>!Number.isInteger(i)||i<0||i>=fullCount)||new Set(rows).size!==rows.length)throw Error('Recorded neurons do not map uniquely to the complete anatomy.');
  const recordedToAnatomy=Int32Array.from(rows),anatomyToRecorded=new Int32Array(fullCount).fill(-1);
  rows.forEach((row,i)=>{anatomyToRecorded[row]=i;});
  return {recordedToAnatomy,anatomyToRecorded};
}

export function projectRecordingFrame(values, frame, recordedToAnatomy, fullCount, output=new Float32Array(fullCount)) {
  const width=recordedToAnatomy.length;
  if(output.length!==fullCount||!Number.isInteger(frame)||frame<0||!width||!values||values.length%width||frame>=values.length/width)throw Error('Recorded frame does not match its anatomical mapping.');
  output.fill(NaN);
  for(let i=0;i<width;i++) {
    const target=recordedToAnatomy[i],value=values[frame*width+i];
    if(!Number.isInteger(target)||target<0||target>=fullCount)throw Error('Recorded target is outside full anatomy.');
    if(Number.isFinite(value))output[target]=value;
  }
  return output;
}

/** Class means describe recorded members only; absent samples never become zero. */
export function recordedClassTraces({groups,groupIds,mapping,frameCount,activity}) {
  const countByGroup=new Map();
  for(const row of mapping)countByGroup.set(groupIds[row],(countByGroup.get(groupIds[row])||0)+1);
  const traces=groups.filter(g=>countByGroup.has(g.id)).map(g=>({name:g.name,color:g.color,
    n_recorded:countByGroup.get(g.id),n_total:g.count,description:'Annotated cell class · mean of recorded neurons',
    values:activity.delta?Array(frameCount).fill(NaN):null,raw:activity.raw?Array(frameCount).fill(NaN):null,baseline:activity.baseline?Array(frameCount).fill(NaN):null}));
  const used=groups.filter(g=>countByGroup.has(g.id)),lookup=new Map(used.map((g,i)=>[g.id,i]));
  for(const [input,output] of [['delta','values'],['raw','raw'],['baseline','baseline']]) {
    const data=activity[input];if(!data)continue;
    if(data.length!==frameCount*mapping.length)throw Error('Class trace dimensions differ from the recording.');
    for(let frame=0;frame<frameCount;frame++) {
      const sums=new Float64Array(traces.length),counts=new Uint32Array(traces.length);
      for(let i=0;i<mapping.length;i++){const value=data[frame*mapping.length+i],target=lookup.get(groupIds[mapping[i]]);if(Number.isFinite(value)&&target!==undefined){sums[target]+=value;counts[target]++;}}
      traces.forEach((trace,i)=>{if(counts[i])trace[output][frame]=sums[i]/counts[i];});
    }
  }
  return traces;
}

/** A saved anatomical snapshot remains usable without its full executable model. */
export async function recordingAnatomySource(summary, loadFull) {
  const modelId=summary.model_id||summary.metadata?.model_id||summary.anatomy?.model_id||'flywire-783';
  const modelHash=summary.model_hash||summary.metadata?.model_hash||summary.anatomy?.model_hash;
  try {
    const anatomy=await loadFull({modelId,modelHash});
    return {anatomy,scope:'full',warning:null};
  } catch(error) {
    const saved=summary.anatomy,count=summary.activity?.shape?.[1]||summary.neuron_count;
    if(!saved)throw error;
    if(saved.model_id!==modelId||(modelHash&&saved.model_hash!==modelHash))
      throw Error('Saved anatomy identity differs from the recording; it cannot be used as historical context.');
    if(saved.neuron_count!==count||!Number.isInteger(count)||count<1)
      throw Error('Saved historical anatomy does not contain the recorded neuron rows.');
    if(['metadata_url','positions_url','groups_url','visible_indices_url','identities_url'].some(key=>!saved[key]))
      throw Error('Full source anatomy is unavailable, and the saved recording lacks complete anatomical identity assets.');
    const warning='Full source anatomy is unavailable for this recording version. Showing historical recorded anatomy only.';
    return {anatomy:{...saved,anatomy_scope:'recorded_historical',anatomy_note:warning,
      anatomy_unavailable_reason:String(error.message||error)},scope:'recorded_historical',warning};
  }
}
