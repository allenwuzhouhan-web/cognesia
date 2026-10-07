import { regionLabel } from './brain-region-names.js';

const DEFAULT_LABELS=['ME_L','ME_R','LO_L','LO_R','LOP_L','LOP_R','LA_L','LA_R','g1','a1','EB','FB'];
export function createRegionAtlas({THREE,camera,stage,host,overlay,regions=[],offset=[0,0,0],onSelect,onDirty,getRegion}) {
  let selected='',showLabels=true,token=0;
  const byKey=new Map(regions.map(r=>[r.key,r]));
  const label=key=>byKey.get(key)?.name||regionLabel(key);
  host.innerHTML='<div class="atlas-row"><label class="atlas-search-label">Find a brain region<input type="search" id="region-search" placeholder="e.g. medulla, mushroom body, antennal"></label><label class="atlas-toggle"><input type="checkbox" id="region-label-toggle" checked> Show full names</label></div><div class="atlas-row"><select id="region-select" aria-label="Brain region"></select><button id="region-clear">Clear focus</button></div><p id="region-selection-note" role="status">Labels mark neuron centers, not boundaries.</p>';
  const select=host.querySelector('#region-select'),search=host.querySelector('#region-search'),note=host.querySelector('#region-selection-note');
  function fillOptions() {
    const q=search.value.trim().toLowerCase();
    select.replaceChildren(new Option('All brain regions',''),...regions.filter(r=>`${label(r.key)} ${r.key}`.toLowerCase().includes(q)).sort((a,b)=>label(a.key).localeCompare(label(b.key))).map(r=>new Option(`${label(r.key)}${r.position?'':' · no located neurons'}`,r.key)));
    if([...select.options].some(x=>x.value===selected))select.value=selected;
  }
  const markers=new Map();
  for(const r of regions) {
    if(!r.position)continue;
    const marker=document.createElement('button');marker.className='brain-region-label';marker.hidden=true;marker.textContent=label(r.key);marker.title=`${regionLabel(r.key,{alias:true})} · ${r.neuron_count.toLocaleString()} assigned neurons`;
    marker.addEventListener('click',()=>choose(r.key));overlay.append(marker);markers.set(r.key,marker);
  }
  async function choose(key) {
    selected=key;fillOptions();const current=++token;
    for(const [k,el] of markers)el.classList.toggle('selected',k===key);
    if(!key){note.textContent='All neurons shown. Labels mark neuron centers, not region boundaries.';onSelect(null);onDirty();return;}
    note.textContent=`${label(key)} · loading assigned neurons…`;onDirty();
    try {
      const data=await (getRegion?getRegion(key):fetch(`/api/regions/${encodeURIComponent(key)}`).then(response=>{if(!response.ok)throw Error('Region mapping unavailable');return response.json();}));if(current!==token)return;
      onSelect(data.indices);note.textContent=`${label(key)} · ${data.indices.length.toLocaleString()} assigned neurons${byKey.get(key)?.position?'':'; no located anchors'}. Assignment centers are approximate.`;onDirty();
    }catch(error){if(current===token){onSelect(null);note.textContent=error.message;onDirty();}}
  }
  function render() {
    const width=stage.clientWidth,height=stage.clientHeight,occupied=[];
    const order=[selected,...DEFAULT_LABELS,...regions.slice(0,8).map(r=>r.key)].filter((k,i,a)=>k&&a.indexOf(k)===i);
    for(const marker of markers.values())marker.hidden=true;
    if(!showLabels||!width||!height)return;
    for(const key of order) {
      const r=byKey.get(key),marker=markers.get(key);if(!r?.position||!marker)continue;
      const p=new THREE.Vector3(...r.position.map((v,i)=>v-offset[i])).project(camera);
      if(p.z < -1 || p.z>1 || Math.abs(p.x)>1 || Math.abs(p.y)>1)continue;
      const textWidth=Math.min(width-24,Math.max(88,Math.min(184,label(key).length*5.1+18)));
      const x=Math.max(8,Math.min(width-textWidth-8,(p.x+1)*width/2-textWidth/2));
      let y=Math.max(58,Math.min(height-55,(1-p.y)*height/2));
      let tries=0;
      while(occupied.some(a=>x<a.x+a.w+5&&x+textWidth+5>a.x&&y<a.y+28&&y+28>a.y)&&tries++<5)y+=30;
      if(y>height-52||tries>5)continue;
      marker.hidden=false;marker.style.left=`${x}px`;marker.style.top=`${y}px`;marker.style.width=`${textWidth}px`;
      occupied.push({x,y,w:textWidth});
    }
  }
  search.addEventListener('input',fillOptions);select.addEventListener('change',()=>choose(select.value));
  host.querySelector('#region-clear').addEventListener('click',()=>{search.value='';choose('');});
  host.querySelector('#region-label-toggle').addEventListener('change',event=>{showLabels=event.target.checked;onDirty();});
  fillOptions();
  return {render,select:choose,dispose:()=>{++token;overlay.replaceChildren();host.replaceChildren();}};
}
