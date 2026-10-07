import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { createFlyBodyPanel } from "./fly-body.js";

export function createBodyView({host,getContext}) {
  const modelId=context=>context.modelId||context.metadata?.model_id||context.liveFrame?.model_id||"flywire-783";
  const ctx=getContext(),body=createFlyBodyPanel({THREE,OrbitControls,host,positions:modelId(ctx)==="flywire-783"?ctx.positions:null,visibleIndices:ctx.visibleIndices});
  const banner=document.createElement("p");banner.className="instrument-status";host.prepend(banner);
  body.ready.catch(()=>{});let lastPositions=ctx.positions;
  const refresh=()=>{const context=getContext(),registered=modelId(context)==="flywire-783";banner.textContent=registered?"NeuroMechFly body with approximate cross-animal FlyWire alignment.":`${modelId(context)} has no registered transform to this body surface. The body is shown without a neural overlay.`;const toggle=host.querySelector("[data-fly-brain]");if(toggle){toggle.disabled=!registered;if(!registered){toggle.checked=false;toggle.dispatchEvent(new Event("change"));}}if(!registered&&lastPositions!==null){lastPositions=null;body.setBrain(null);}if(registered&&context.positions&&lastPositions!==context.positions){lastPositions=context.positions;body.setBrain({positions:context.positions,visibleIndices:context.visibleIndices});}body.setFrame({values:registered?context.values:null,mode:context.mode||"anatomy",range:context.summary?.activity?.color_range_mv||5,timeMs:context.timeMs||0,hasRecording:registered&&!!context.values});};
  refresh();
  return{refresh,setTime:refresh,dispose:()=>body.dispose()};
}

export function createAnatomyPanel({host,getContext,onStatus}) {
  host.classList.add("anatomy-instance");
  host.innerHTML='<div class="instrument-controls"><label>Cross section<select data-axis><option value="none">Whole brain</option><option value="0">Voxel X slab</option><option value="1">Voxel Y slab</option><option value="2">Voxel Z slab</option></select></label><label>Position<input data-position type="range" min="0" max="1000" value="500"></label><label>Thickness<input data-thickness type="range" min="1" max="1000" value="120"></label><button data-home>Reset camera</button><label>Region<select data-region><option value="">All regions</option></select></label><label><input type="checkbox" data-isolate checked> Isolate selection</label></div><div class="anatomy-instance-stage"></div><p class="instrument-status">Annotation anchors. Cross sections use original dataset XYZ, not MRI tissue.</p>';
  const $=s=>host.querySelector(s),stage=$(".anatomy-instance-stage"),status=$(".instrument-status"),scene=new THREE.Scene();scene.background=new THREE.Color("#15181d");
  const camera=new THREE.PerspectiveCamera(42,1,.001,100),renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));stage.append(renderer.domElement);
  const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=false;
  let geometry=null,points=null,material=null,lastPositions=null,lastRegions=null,visible=[],bounds=null,selected=null,token=0,disposed=false,frame=null;
  const requestDraw=()=>{if(disposed||frame!==null)return;frame=requestAnimationFrame(()=>{frame=null;if(stage.clientWidth&&stage.clientHeight)renderer.render(scene,camera);});};
  controls.addEventListener("change",requestDraw);
  function home(){if(!bounds)return;const center=new THREE.Vector3(...bounds.low.map((v,i)=>(v+bounds.high[i])/2)),radius=Math.max(...bounds.high.map((v,i)=>v-bounds.low[i]))||1;controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(0,-.1,1).normalize().multiplyScalar(radius*1.8));camera.near=Math.max(.00001,radius/10000);camera.far=radius*100;camera.updateProjectionMatrix();controls.update();requestDraw();}
  function filter(){if(!geometry||!bounds)return;const axis=$("[data-axis]").value,indices=[],pos=geometry.attributes.position.array,selectedSet=selected?new Set(selected):null;
    let lower=-Infinity,upper=Infinity;if(axis!=="none"){const i=Number(axis),extent=bounds.high[i]-bounds.low[i],center=bounds.low[i]+Number($("[data-position]").value)/1000*extent,half=Number($("[data-thickness]").value)/2000*extent;lower=center-half;upper=center+half;}
    for(const i of visible){if(selectedSet&&$("[data-isolate]").checked&&!selectedSet.has(i))continue;if(axis!=="none"&&(pos[i*3+Number(axis)]<lower||pos[i*3+Number(axis)]>upper))continue;indices.push(i);}
    geometry.setIndex(new THREE.BufferAttribute(Uint32Array.from(indices),1));status.textContent=`${indices.length.toLocaleString()} visible annotation anchors · ${axis==="none"?"whole volume":`dataset ${"XYZ"[Number(axis)]} slab`} · visual isolation does not alter the simulation scope.`;requestDraw();
  }
  function refresh(){
    if(disposed)return;const context=getContext();if(!context.positions){status.textContent="Anatomical coordinates are not loaded.";return;}
    if(context.positions!==lastPositions){
      lastPositions=context.positions;selected=null;$("[data-region]").value="";token++;if(points){scene.remove(points);geometry.dispose();material.dispose();}
      const pos=Float32Array.from(context.positions),count=pos.length/3;visible=context.visibleIndices?Array.from(context.visibleIndices):Array.from({length:count},(_,i)=>i);visible=visible.filter(i=>i>=0&&i<count&&[0,1,2].every(j=>Number.isFinite(pos[3*i+j])));
      bounds={low:[Infinity,Infinity,Infinity],high:[-Infinity,-Infinity,-Infinity]};for(const i of visible)for(let j=0;j<3;j++){bounds.low[j]=Math.min(bounds.low[j],pos[3*i+j]);bounds.high[j]=Math.max(bounds.high[j],pos[3*i+j]);}
      geometry=new THREE.BufferGeometry();geometry.setAttribute("position",new THREE.BufferAttribute(pos,3));geometry.setAttribute("color",new THREE.BufferAttribute(new Float32Array(pos.length),3));material=new THREE.PointsMaterial({size:.005,vertexColors:true,sizeAttenuation:true,transparent:true,opacity:.65});points=new THREE.Points(geometry,material);scene.add(points);filter();home();
    }
    if(context.metadata?.regions!==lastRegions){lastRegions=context.metadata?.regions;const select=$("[data-region]"),prior=select.value;select.replaceChildren(new Option("All regions",""));for(const region of lastRegions||[])select.add(new Option(region.label||region.name||region.key,region.key));if([...select.options].some(o=>o.value===prior))select.value=prior;}
    const color=geometry.attributes.color.array,values=context.values,range=context.summary?.activity?.color_range_mv||5,absolute=["absolute","baseline"].includes(context.mode);
    for(let i=0;i<color.length/3;i++){const v=values?.[i];let strength=Number.isFinite(v)?Math.min(1,absolute?(v+90)/110:Math.abs(v)/range):0;strength=Math.max(0,strength);const hot=absolute?strength>.5:v>=0;color[i*3]=.4+strength*(hot?.58:-.15);color[i*3+1]=.58+strength*(hot?-.25:.1);color[i*3+2]=.72+strength*(hot?-.48:.26);}
    geometry.attributes.color.needsUpdate=true;requestDraw();
  }
  for(const input of host.querySelectorAll("[data-axis],[data-position],[data-thickness],[data-isolate]"))input.addEventListener("input",filter);
  $("[data-home]").addEventListener("click",home);$("[data-region]").addEventListener("change",async event=>{const key=event.target.value,current=++token;if(!key){selected=null;filter();return;}try{const context=getContext(),modelId=context.modelId||context.metadata?.model_id,modelHash=context.metadata?.model_hash||context.modelHash;if(!modelId||!modelHash)throw new Error("The displayed anatomy source identity is unavailable. Reload the model.");const url=context.metadata?.regions_url||`/api/model-anatomy/${encodeURIComponent(modelId)}/regions.json?model_hash=${encodeURIComponent(modelHash)}`,response=await fetch(url),data=await response.json();if(!response.ok)throw new Error(data.error||"Region unavailable.");if(current!==token||disposed)return;selected=data[key];if(!Array.isArray(selected))throw new Error("Region membership is unavailable for this dataset.");filter();}catch(error){onStatus?.(error.message);status.textContent=error.message;}});
  const resize=()=>{if(disposed||!stage.clientWidth||!stage.clientHeight)return;renderer.setSize(stage.clientWidth,stage.clientHeight,false);camera.aspect=stage.clientWidth/stage.clientHeight;camera.updateProjectionMatrix();requestDraw();};const observer=new ResizeObserver(resize);observer.observe(stage);refresh();resize();
  return{refresh,setTime:refresh,dispose(){disposed=true;token++;observer.disconnect();if(frame!==null)cancelAnimationFrame(frame);controls.dispose();geometry?.dispose();material?.dispose();renderer.dispose();renderer.forceContextLoss();}};
}
