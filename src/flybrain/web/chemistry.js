// Recorded compartment fields only. No molecule positions or inferred missing data.
export const CHEMICAL_SPECIES = ['DA','OA','5HT','NO','sNPF','peptide_pool','TA','ACh'];
export function validateChemistry(record, neuronCount, expectedTimes) {
  if (!record || record.enabled === false || record.available === false) return null;
  const species = record.species, compartments = record.compartment_names || record.compartments;
  const time = record.time_ms, membership = record.membership || record.neuron_membership;
  if (!Array.isArray(species) || species.length !== 8 || !CHEMICAL_SPECIES.every(x=>species.includes(x))) throw Error('Recording has an unsupported chemical species axis.');
  if (!Array.isArray(compartments) || !compartments.length || !Array.isArray(time) || !time.length) throw Error('Chemical recording has missing compartment/time axes.');
  if (expectedTimes && (time.length!==expectedTimes.length || time.some((v,i)=>v!==expectedTimes[i]))) throw Error('Chemical and neural recordings have different time samples.');
  const flat = value => ArrayBuffer.isView(value) ? value : Float32Array.from(value?.flat(Infinity) || []);
  const concentrations = flat(record.concentrations_au), baseline = flat(record.baseline_concentrations_au);
  const expected = time.length*species.length*compartments.length;
  if (concentrations.length!==expected || (baseline.length && baseline.length!==expected)) throw Error('Chemical concentration shape does not match its axes.');
  for (const values of [concentrations,baseline]) for (const v of values) if (!Number.isFinite(v)||v<0) throw Error('Chemical concentration is missing, negative or nonfinite.');
  const ptr = membership?.indptr, indices = membership?.indices, weights = membership?.weights;
  if (!ptr || !indices || !weights || ptr.length!==neuronCount+1 || ptr[0]!==0 || ptr[neuronCount]!==indices.length || indices.length!==weights.length) throw Error('Chemical membership does not match the released neuron order.');
  for(let n=0;n<neuronCount;n++) {if(!Number.isInteger(ptr[n])||ptr[n]>ptr[n+1]) throw Error('Invalid chemical membership offsets.');let sum=0;for(let j=ptr[n];j<ptr[n+1];j++){if(!Number.isInteger(indices[j])||indices[j]<0||indices[j]>=compartments.length||!Number.isFinite(weights[j])||weights[j]<0)throw Error('Invalid chemical membership value.');sum+=weights[j]}if(ptr[n+1]>ptr[n]&&Math.abs(sum-1)>1e-5)throw Error('Chemical membership weights do not sum to one.');}
  const stateNames=record.state_names||[],hormoneNames=record.hormone_names||[];
  const stateValues=flat(record.state_values),hormones=flat(record.hormones_au),baselineStates=flat(record.baseline_state_values),baselineHormones=flat(record.baseline_hormones_au);
  for(const [values,names] of [[stateValues,stateNames],[hormones,hormoneNames],[baselineStates,stateNames],[baselineHormones,hormoneNames]])if(values.length&&values.length!==time.length*names.length)throw Error('State recording shape does not match its axes.');
  const enzymeArrays={};
  if(record.enzymes?.enabled)for(const [axis,names] of [['pools_au',record.enzymes.pool_names],['flux_au_per_ms',record.enzymes.flux_names]])for(const prefix of ['','baseline_']){
    const key=prefix+'enzyme_'+axis,values=flat(record[key]);
    if(!Array.isArray(names)||!names.length||values.length!==time.length*names.length*compartments.length)throw Error('Enzyme recording shape does not match its axes.');
    for(const value of values)if(!Number.isFinite(value)||value<0)throw Error('Enzyme recording contains missing, negative or nonfinite values.');
    enzymeArrays[key]=values;
  }
  return {...record,...enzymeArrays,species,compartments,time_ms:time,concentrations_au:concentrations,baseline_concentrations_au:baseline,state_names:stateNames,state_values:stateValues,baseline_state_values:baselineStates,baseline_hormones_au:baselineHormones,hormone_names:hormoneNames,hormones_au:hormones,neuron_membership:{indptr:ptr,indices,weights},neuron_count:neuronCount};
}
export function fieldValue(record,frame,speciesIndex,compartmentIndex,baseline=false){
  const values=baseline?record?.baseline_concentrations_au:record?.concentrations_au;
  if(!record||frame<0||frame>=record.time_ms.length||speciesIndex<0||speciesIndex>=record.species.length||compartmentIndex<0||compartmentIndex>=record.compartments.length)return null;
  const v=values?.[(frame*record.species.length+speciesIndex)*record.compartments.length+compartmentIndex];return Number.isFinite(v)?v:null;
}
export function projectExposure(record,frame,speciesIndex,baseline=false){
  const values=new Float32Array(record.neuron_count).fill(-1),m=record.neuron_membership;
  for(let n=0;n<record.neuron_count;n++){if(m.indptr[n]===m.indptr[n+1])continue;let sum=0,valid=true;for(let j=m.indptr[n];j<m.indptr[n+1];j++){const c=fieldValue(record,frame,speciesIndex,m.indices[j],baseline);if(c===null){valid=false;break}sum+=m.weights[j]*c;}if(valid)values[n]=sum;}
  return values;
}
export function chemicalTrace(record,speciesIndex,compartmentIndex,baseline=false){return Float64Array.from(record.time_ms,(_,f)=>fieldValue(record,f,speciesIndex,compartmentIndex,baseline)??NaN);}
export function stateTrace(record,name,baseline=false){const i=record.state_names.indexOf(name);if(i<0)throw Error('State variable is not recorded.');return Float64Array.from(record.time_ms,(_,f)=>(baseline?record.baseline_state_values:record.state_values)?.[f*record.state_names.length+i]??NaN);}
