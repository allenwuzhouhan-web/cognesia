/** Differences use exactly matching measured timestamps, never interpolation. */
export function alignedDifference(a,b) {
  function validate(source){if(!source.timeMs||!source.values||source.timeMs.length!==source.values.length)throw new Error("Recording times and values do not match.");for(let i=0;i<source.timeMs.length;i++)if(!Number.isFinite(source.timeMs[i])||!Number.isFinite(source.values[i])||(i&&source.timeMs[i]<=source.timeMs[i-1]))throw new Error("Comparison needs finite, strictly increasing measured samples.");}
  validate(a);validate(b);if(a.unit!==b.unit)throw new Error("Difference requires matching recorded units.");
  const timeMs=[],values=[];let i=0,j=0;while(i<a.timeMs.length&&j<b.timeMs.length){const ta=a.timeMs[i],tb=b.timeMs[j];if(ta===tb){timeMs.push(ta);values.push(b.values[j]-a.values[i]);i++;j++;}else if(ta<tb)i++;else j++;}
  if(timeMs.length<2)throw new Error("Fewer than two exact timestamps are shared. No resampling or interpolation was applied.");
  return {timeMs:Float64Array.from(timeMs),values:Float64Array.from(values),unit:a.unit,matchedSamples:timeMs.length,unmatchedA:a.timeMs.length-timeMs.length,unmatchedB:b.timeMs.length-timeMs.length};
}

export function recordedSpikeEvents(source,limit=15000) {
  const indices=source?.spike_indices||source?.indices,times=source?.spike_times_ms||source?.times_ms||source?.spike_times;
  if(!indices||!times||indices.length!==times.length)return [];
  const events=[];for(let i=Math.max(0,indices.length-limit);i<indices.length;i++)if(Number.isFinite(times[i])&&Number.isInteger(indices[i])&&indices[i]>=0)events.push([times[i],indices[i]]);
  return events;
}

/** Geometry selections are full-model indices, independent of recording columns. */
export function fullModelConnectivityRequest(context,{sourceIndices=null,targetIndices=null,sourceRegions=[],targetRegions=[]}={}) {
  const modelId=context.modelId||context.metadata?.model_id,modelHash=context.metadata?.model_hash||context.modelHash;
  if(!modelId||!modelHash)throw new Error('The displayed anatomy source identity is unavailable. Reload the model before inspecting connections.');
  if(context.modelHash&&context.metadata?.model_hash&&context.modelHash!==context.metadata.model_hash)throw new Error('The displayed anatomy source hashes disagree. Reload the model before inspecting connections.');
  const count=context.positions?context.positions.length/3:context.metadata?.neuron_count;
  const request={limit:100,model_id:modelId,model_hash:modelHash};
  for(const[name,indices,regions]of [['source',sourceIndices,sourceRegions],['target',targetIndices,targetRegions]]){
    if(indices!==null){
      if(!Array.isArray(indices)||indices.some(index=>!Number.isInteger(index)||index<0||Number.isFinite(count)&&index>=count))throw new Error('A selected neuron is outside the displayed model anatomy. Select it again.');
      request[`${name}_indices`]=[...new Set(indices)];
    }else request[`${name}_regions`]=[...new Set(regions)];
  }
  // Never include run_id: it would reinterpret these as recording-local indices.
  return request;
}
