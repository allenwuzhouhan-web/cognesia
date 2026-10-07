/** One display policy for live streams, saved frames, and missing channels. */
export const BRAIN_MODES=['delta','absolute','baseline','anatomy','chemical'];
export function brainDisplayPolicy(mode,{live=false,liveSignal='raw',hasValues=false,hasChemistry=false}={}){
  if(!BRAIN_MODES.includes(mode))throw Error('Unknown brain display mode.');
  const anatomy=mode==='anatomy';
  const available=anatomy||(hasValues&&(live?(mode==='absolute'||mode==='baseline'&&liveSignal==='baseline'):(mode!=='chemical'||hasChemistry)));
  const unavailable=available?null:mode==='chemical'?(live?'Live neuron exposure unavailable.':'No recorded chemical exposure.'):
    mode==='baseline'?(live?'Baseline available during the control phase.':'No recorded baseline.'):
    mode==='delta'?(live?'Paired ΔV available after recording.':'No recorded paired ΔV.'):'No recorded membrane voltage.';
  return{mode,available,active:anatomy?0:1,absolute:['absolute','baseline'].includes(mode)?1:0,chemical:mode==='chemical'?1:0,live:live?1:0,unavailable};
}
export function applyBrainDisplayUniforms(uniforms,display,range=5){
  for(const [key,value] of [['uActive',display.active],['uAbsolute',display.absolute],['uChemical',display.chemical],['uSectionLive',display.live],['uRange',Number.isFinite(range)&&range>0?range:1]])if(uniforms[key])uniforms[key].value=value;
}
export function writeBrainActivity(target,values,available){
  if(!available||!values){target.fill(-1e30);return;}
  if(values.length!==target.length)throw Error('Display frame does not match anatomical rows.');
  for(let i=0;i<target.length;i++)target[i]=Number.isFinite(values[i])?values[i]:-1e30;
}
