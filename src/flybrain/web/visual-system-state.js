/** Identity and clock invariants for the linked visual-system workspace.
 * This module contains no rendering and never substitutes missing data with zero.
 */
export const MODES = Object.freeze(['raw', 'control', 'difference']);
export function identityOf(value) {
  const p = value?.provenance || value;
  if (!p?.model_id || !p?.model_hash || !p?.run_id) throw Error('Evidence requires a model ID, immutable hash, and run ID.');
  return {model_id:p.model_id, model_hash:p.model_hash, run_id:p.run_id};
}
export function requireIdentity(expected, actual) {
  const a=identityOf(expected), b=identityOf(actual);
  for(const key of ['model_id','model_hash','run_id']) if(a[key]!==b[key]) throw Error(`Stale or incompatible evidence: ${key} differs.`);
  return b;
}
export function nearestTime(times, requested) {
  if(!Array.isArray(times)||!times.length||!Number.isFinite(requested)) throw Error('A finite recorded time is required.');
  if(times.some((v,i)=>!Number.isFinite(v)||(i>0&&v<=times[i-1]))) throw Error('Recording timestamps must be finite and increasing.');
  let lo=0, hi=times.length-1;
  while(lo<hi){const m=Math.floor((lo+hi)/2);if(times[m]<requested)lo=m+1;else hi=m;}
  return lo>0&&Math.abs(times[lo-1]-requested)<=Math.abs(times[lo]-requested)?lo-1:lo;
}
export function validateMap(data, state) {
  requireIdentity(state,data);
  if(data.unit!=='mV')throw Error('Voltage map requires mV units.');
  if(!MODES.includes(data.mode)||data.mode!==state.mode)throw Error('Voltage mode differs from the workspace.');
  if(data.time_ms!==state.time_ms)throw Error('View timestamp differs from the shared recorded cursor.');
  const ids=new Set();
  for(const row of data.rows||[]) {
    if(!row.entity_id||ids.has(row.entity_id))throw Error('Activity rows require unique source-qualified neuron identities.');
    ids.add(row.entity_id);
    if(row.recording_column!==null&&row.recording_column!==undefined&&(!Number.isInteger(row.recording_column)||row.recording_column<0))throw Error('Invalid recording-local column.');
    if(row.value!==null&&row.value!==undefined&&!Number.isFinite(row.value))throw Error('Activity values must be finite or explicitly missing.');
    if(!row.recorded&&row.value!==null&&row.value!==undefined)throw Error('An unrecorded neuron cannot have a voltage.');
    if(row.azimuth_deg!==null&&row.azimuth_deg!==undefined&&(!Number.isFinite(row.azimuth_deg)||Math.abs(row.azimuth_deg)>360))throw Error('Invalid visual azimuth.');
    if(row.elevation_deg!==null&&row.elevation_deg!==undefined&&(!Number.isFinite(row.elevation_deg)||Math.abs(row.elevation_deg)>90))throw Error('Invalid visual elevation.');
  }
  return data;
}
export function createWorkspaceState() {
  let value=null,revision=0;
  return {
    load(catalog){const identity=identityOf(catalog);const times=catalog.time_ms||[];nearestTime(times,times[0]);value={...identity,time_ms:times[0],frame_index:0,mode:'difference',population_ids:[],cell_types:[],entity_id:null,optical_column_id:null,region:null,interval:[times[0],times.at(-1)],time_samples:times};revision++;return this.snapshot();},
    update(patch){if(!value)throw Error('Load a recording first.');if(Object.keys(patch).some(k=>['model_id','model_hash','run_id','time_samples'].includes(k)))throw Error('Recording identity may only change by loading a run.');if(patch.mode&&!MODES.includes(patch.mode))throw Error('Unsupported voltage mode.');if(patch.time_ms!==undefined){const i=nearestTime(value.time_samples,patch.time_ms);patch={...patch,time_ms:value.time_samples[i],frame_index:i};}if(patch.interval&&(!patch.interval.every(Number.isFinite)||patch.interval[0]>patch.interval[1]))throw Error('Invalid selected time interval.');value={...value,...patch};revision++;return this.snapshot();},
    selectPopulation(population, additive=false){if(!population?.id||!population.cell_type)throw Error('Population identity is required.');const ids=additive?[...new Set([...value.population_ids,population.id])]:[population.id];const types=additive?[...new Set([...value.cell_types,population.cell_type])]:[population.cell_type];return this.update({population_ids:ids,cell_types:types,entity_id:null,optical_column_id:null});},
    selectNeuron(row){if(!row?.entity_id)throw Error('Neuron identity is required.');return this.update({entity_id:row.entity_id,population_ids:row.population_id?[row.population_id]:[],cell_types:row.cell_type?[row.cell_type]:[],optical_column_id:row.optical_column_id??null});},
    snapshot(){return value?JSON.parse(JSON.stringify({...value,revision})):null;},
    isCurrent(snapshot){return !!value&&snapshot.revision===revision&&snapshot.run_id===value.run_id;}
  };
}
export function finiteValue(value){return typeof value==='number'&&Number.isFinite(value)?value:null;}
export function voltageColor(value,mode='difference',extent=10){
  if(finiteValue(value)===null)return '#bfc4cc';
  const t=Math.max(-1,Math.min(1,mode==='difference'?value/Math.max(extent,.001):((value+90)/110)*2-1));
  const a=t<0?[244,245,247]:[244,245,247],b=t<0?[42,104,173]:[186,57,46],n=Math.abs(t);
  return `rgb(${a.map((v,i)=>Math.round(v+(b[i]-v)*n)).join(',')})`;
}
export function mapPosition(row){return Number.isFinite(row.azimuth_deg)&&Number.isFinite(row.elevation_deg)?[row.azimuth_deg,row.elevation_deg]:null;}
export function filterSelection(rows,state){return rows.filter(r=>(!state.entity_id||r.entity_id===state.entity_id)&&(!state.optical_column_id||r.optical_column_id===state.optical_column_id)&&(!state.population_ids.length||state.population_ids.includes(r.population_id)));}
export function evidenceMetadata(state,extra={}){return {...identityOf(state),time_ms:state.time_ms,time_interval_ms:state.interval,mode:state.mode,quantity:'membrane_voltage',unit:'mV',population_ids:state.population_ids,cell_types:state.cell_types,entity_id:state.entity_id,optical_column_id:state.optical_column_id,coordinate_convention:'Native dataset XYZ for anatomy; azimuth/elevation degrees only where mapping exists',...extra};}
