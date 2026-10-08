import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { initializeWorkspaceOverview } from "./workspace-overview.js";
import { initializeWorkspaceSettings } from "./workspace-settings.js";
import { initializeSequenceTimeline } from "./sequence-timeline.js";
import { initializeWorkspaceNotes } from "./workspace-notes.js";
import { initializeDesktopWorkspace } from "./desktop-workspace.js";
import { initializeExperimentControls } from "./experiment-controls.js";
import { initializeLayoutWorkbench } from "./layout-workbench.js";
import { createBrainSections, insideSection } from "./brain-sections.js";
import { initializeAnalysis } from "./analysis.js";
import { createSignalAdapter } from "./analysis-data.js?v=neuromod-20260927";
import { validateChemistry, projectExposure, fieldValue, chemicalTrace, stateTrace } from "./chemistry.js";
import { regionLabel, speciesLabel } from "./brain-region-names.js";
import { initializeChemicalControls } from "./chemical-controls.js";
import { createRegionAtlas } from "./region-atlas.js";
import { createFlyBodyPanel } from "./fly-body.js";
import { brainDisplayPolicy, applyBrainDisplayUniforms, writeBrainActivity } from "./brain-display.js";
import { centeredAnatomy, fittedCameraDistance, recordingRowMap, projectRecordingFrame, recordedClassTraces, recordingAnatomySource } from "./anatomy-rendering.js";
import {
  initializeLab,
  configureLab,
  collectLabOptions,
  restoreLabOptions,
  setLabRunning,
  addNeuronElectrode,
  setLabRecording,
  updateLabPlayback,
} from "./lab.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const modelDisplayName = id => ({'paralimbo-v0-1-0':'ParaLimbo 0.1 · BANC × FlyWire','banc-888':'BANC 888','cognesia-fused-v1':'Cognesia','flywire-783':'FlyWire 783'})[id]||id||'FlyWire 783';
let stimulusFrameCanvas = document.createElement("canvas");
const palette = [
  "#65b5ff",
  "#28754b",
  "#a64e29",
  "#b2a1ff",
  "#a8375d",
  "#346f7f",
  "#80712e",
  "#536373",
];
// Preserve category hues with enough luminance for the dark workspace.
const displayColors = new Map();
function plotColor(source, index = 0) {
  const key = source || palette[index % palette.length];
  if (!displayColors.has(key)) {
    const color = new THREE.Color(key);
    const hsl = {};
    color.getHSL(hsl, THREE.SRGBColorSpace);
    color.setHSL(hsl.h, Math.min(0.7, Math.max(0.4, hsl.s)),
      Math.max(0.60, Math.min(0.72, hsl.l)), THREE.SRGBColorSpace);
    displayColors.set(key, `#${color.getHexString()}`);
  }
  return displayColors.get(key);
}
const labels = {
  grating: "Moving grating",
  flash: "Full-field flash",
  edge: "Moving edge",
  looming: "Looming disc",
  apparent_motion: "Apparent motion",
  dark: "Dark control",
};
const state = {
  bootstrap: null,
  metadata: null,
  positions: null,
  groups: null,
  visibleIndices: null,
  summary: null,
  activity: {},
  mode: "delta",
  readout: "types",
  frame: 0,
  time: 0,
  playing: false,
  playbackSpeed: 0.25,
  previewStart: performance.now(),
  previewEdited: false,
  runLoading: false,
  job: null,
  selectedNeuron: null,
  cameraView: "overview",
  morphologyEnabled: false,
  morphologyMode: "anchors",
  overviewToken: 0,
  morphologyNeuron: null,
  morphologyToken: 0,
  selectedEyeColumn: null,
  eyeHitTargets: [],
  eyeOrientation: "fly",
  chemistry: null,
  chemicalCache: null,
  chemistryError: null,
  previewStopped: true,
  previewDirty: true,
  sceneDirty: true,
  recordedToAnatomy: null,
  anatomyToRecorded: null,
  recordingMetadata: null,
  eyeMap: null,
  anatomyIdentities: null,
  projectedFrame: null,
};
let analysisWorkbench, chemicalControls, regionAtlas, flyBodyPanel, experimentControls, layoutWorkbench, brainSections, workspaceOverview, workspaceSettings, sequenceTimeline, sequenceWorkspace, workspaceNotes, desktopWorkspace;
const sectionState = {enabled:false,axis:2,center:0,thickness:.2,isolate:false};
let scene,
  camera,
  renderer,
  controls,
  geometry,
  points,
  material,
  resizeObserver,
  pointCount = 0,
  boundsRadius = 1,
  lastRender = performance.now(),
  lastPreview = 0,
  runLoadToken = 0;
let toastTimer;
let morphologyLines = null,
  overviewLines = null,
  morphologyTexture = null;
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const formatNumber = (value) =>
  Number.isFinite(Number(value)) ? Number(value).toLocaleString("en-US") : "—";
const signed = (value) =>
  !Number.isFinite(value)
    ? "—"
    : `${value > 0 ? "+" : ""}${Math.abs(value) < 0.01 ? value.toFixed(3) : value.toFixed(2)}`;
async function requestJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail;
    try {
      detail = await response.json();
    } catch {}
    throw new Error(
      detail?.error || detail?.detail || `Request failed (${response.status})`,
    );
  }
  return response.json();
}
async function requestArray(url, Type = Float32Array) {
  const response = await fetch(url);
  if (!response.ok)
    throw new Error(`Could not load recorded array (${response.status})`);
  return new Type(await response.arrayBuffer());
}
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("#toast").hidden = true), 6500);
}
function settings(strict=false) {
  const out = {
    stimulus: $("#stimulus-type").value,
    direction_deg: Number($("#direction").value),
    speed_deg_s: Number($("#speed").value),
    contrast: Number($("#contrast").value) / 100,
    duration_ms: Number($("#duration").value),
    mean_luminance: Number($("#mean-luminance").value),
    spatial_period_deg: Number($("#spatial-period").value),
    grating_waveform: $("#grating-waveform").value,
  };
  if (out.stimulus === "apparent_motion") {
    out.apparent_interval_ms =
      (Number($("#apparent-interval").value) * 1000) / 240;
    out.apparent_separation_columns = Number($("#apparent-separation").value);
  }
  const base = { ...out, ...collectLabOptions(), neuromod: chemicalOptions(strict) };
  const result=experimentControls ? experimentControls.options(base) : base;
  return !strict&&result.legacy_protocol?{...base,...result}:result;
}
function chemicalOptions(strict=false) { return chemicalControls.getOptions(strict); }
function restoreChemicalOptions(options) { chemicalControls.restore(options); }
const LIVE_RELOAD_SNAPSHOT = 'cognesia.live-reload.workspace.v1';
let workspaceReadyForReload = false;
function restoreWorkspaceOptions(options) {
  if(options.stimulus)$("#stimulus-type").value=options.stimulus;
  for(const [control,key,scale] of [
    ["direction","direction_deg",1],["speed","speed_deg_s",1],["contrast","contrast",100],
    ["duration","duration_ms",1],["mean-luminance","mean_luminance",1],["spatial-period","spatial_period_deg",1],
    ["apparent-interval","apparent_interval_ms",.24],["apparent-separation","apparent_separation_columns",1],
  ]) if(Number.isFinite(options[key]))$("#"+control).value=options[key]*scale;
  if(options.grating_waveform)$("#grating-waveform").value=options.grating_waveform;
  restoreLabOptions(options);restoreChemicalOptions(options);updateControls();
  workspaceOverview?.refresh();
}
window.addEventListener('cognesia:before-live-reload', event => {
  if(!workspaceReadyForReload){event.preventDefault();return;}
  try {
    sessionStorage.setItem(LIVE_RELOAD_SNAPSHOT,JSON.stringify({version:1,options:settings(),
      runId:state.summary?.id,timeMs:state.time,mode:state.mode}));
  } catch(error) {
    event.preventDefault();
    toast(`Live update waiting: could not preserve workspace settings (${error.message}).`);
  }
});
async function loadChemicalRecording(summary) {
  let record = summary.chemistry;
  if (!record || record.enabled === false || record.available === false) return null;
  if (record.url) record = {...record,...await requestJSON(record.url)};
  const member = record.membership || record.neuron_membership || {};
  const [concentrations,baseline,stateValues,hormones,indptr,indices,weights,baselineStates,baselineHormones] = await Promise.all([
    record.concentrations_url ? requestArray(record.concentrations_url) : record.concentrations_au,
    record.baseline_concentrations_url ? requestArray(record.baseline_concentrations_url) : record.baseline_concentrations_au,
    record.state_values_url ? requestArray(record.state_values_url) : record.state_values,
    record.hormones_url ? requestArray(record.hormones_url) : record.hormones_au,
    member.indptr_url ? requestArray(member.indptr_url, Uint32Array) : member.indptr,
    member.indices_url ? requestArray(member.indices_url, Uint32Array) : member.indices,
    member.weights_url ? requestArray(member.weights_url) : member.weights,
    record.baseline_state_values_url ? requestArray(record.baseline_state_values_url) : record.baseline_state_values,
    record.baseline_hormones_au_url ? requestArray(record.baseline_hormones_au_url) : record.baseline_hormones_au,
  ]);
  const enzymeKeys=['enzyme_pools_au','baseline_enzyme_pools_au','enzyme_flux_au_per_ms','baseline_enzyme_flux_au_per_ms'];
  const enzymeArrays=await Promise.all(enzymeKeys.map(key=>record[key+'_url']?requestArray(record[key+'_url']):record[key]));
  return validateChemistry({...record,...Object.fromEntries(enzymeKeys.map((key,i)=>[key,enzymeArrays[i]])),concentrations_au:concentrations,baseline_concentrations_au:baseline,
    state_values:stateValues,hormones_au:hormones,baseline_state_values:baselineStates,baseline_hormones_au:baselineHormones,neuron_membership:{indptr,indices,weights},membership:undefined},summary.activity?.shape?.[1] ?? summary.neuron_count,summary.frames?.time_ms);
}
function chemicalFrame() {
  const c = state.chemistry;
  if (!c) {if(state.missingChemicalFrame?.length!==pointCount)state.missingChemicalFrame=new Float32Array(pointCount).fill(-1);return state.missingChemicalFrame;}
  const species = c.species.indexOf($("#chemical-species").value), baseline = $("#chemical-condition").value === "baseline";
  const key = `${state.frame}:${species}:${baseline}`;
  if (state.chemicalCache?.key !== key) {
    const recorded=projectExposure(c,state.frame,species,baseline);
    state.chemicalCache={key,values:state.recordedToAnatomy?projectRecordingFrame(recorded,0,state.recordedToAnatomy,pointCount):recorded};
  }
  return state.chemicalCache.values;
}
function activityOffset() { return 0; }
function chemicalRange() {
  const c=state.chemistry;
  if(!c) return 1;
  const species=c.species.indexOf($("#chemical-species").value), baseline=$("#chemical-condition").value === "baseline";
  const key=`${species}:${baseline}`;
  if(state.chemicalRangeCache?.record===c&&state.chemicalRangeCache.key===key)return state.chemicalRangeCache.range;
  let max=0;
  for(let f=0;f<c.time_ms.length;f++)for(let j=0;j<c.compartments.length;j++)max=Math.max(max,fieldValue(c,f,species,j,baseline)??0);
  const range=Math.max(max,0.000001);state.chemicalRangeCache={record:c,key,range};return range;
}
function configureChemicalReadout() {
  const c=state.chemistry;
  $("#chemical-compartment").replaceChildren(...(c?c.compartments.map((x,i)=>new Option(regionLabel(x),String(i))):[new Option("No recorded field","")]));
  if(c?.compartments.includes("g4"))$("#chemical-compartment").value=String(c.compartments.indexOf("g4"));
  $("#state-trace-variable").replaceChildren(...(c?c.state_names.map(x=>new Option(x,x)):[new Option("No recorded state","")]));
  $("#pin-chemical").disabled=!c;$("#pin-state").disabled=!c?.state_values.length;
  $("#chemical-status").textContent=c?`Recorded ${c.species.length} species · ${c.compartments.length} compartments · ${c.scenario || "declared initial state"}`:state.chemistryError||"Chemical fields unavailable in this recording";
  $("#chemical-provenance").textContent=c?"Model exposure (a.u.); unassigned neurons are unknown.":"No chemical data in this recording.";
  $("#chemical-details").hidden=!c;$("#chemical-details").open=false;
  $("#chemical-assumptions").innerHTML=c?"<ul>"+[...(c.assumptions||[]),...(c.warnings||[])].map(item=>`<li>${escapeHTML(typeof item==="string"?item:JSON.stringify(item))}</li>`).join("")+"</ul>":"";
  $("#chemical-diagnostics").textContent=c?JSON.stringify({scenario:c.scenario,interpretation:c.interpretation,source_provenance:c.source_provenance,membership_policy:c.membership_policy,paired_initialization:c.paired_initialization,diagnostics:c.diagnostics,baseline_diagnostics:c.baseline_diagnostics},null,2):"";

  drawChemicalReadout();
}
function drawRecordedLine(canvas,times,values,color,current) {
  const {ctx,width,height}=resizeCanvas(canvas);ctx.clearRect(0,0,width,height);
  const finite=Array.from(values||[]).filter(Number.isFinite);
  if(!times?.length||!finite.length){ctx.fillStyle="#76828b";ctx.font="10px sans-serif";ctx.fillText("No recorded values",10,height/2);return;}
  const lo=Math.min(0,...finite),hi=Math.max(lo+0.001,...finite),left=36,right=8,top=12,bottom=20;
  const x=t=>left+(t-times[0])/Math.max(1,times.at(-1)-times[0])*(width-left-right),y=v=>height-bottom-(v-lo)/(hi-lo)*(height-top-bottom);
  ctx.fillStyle="#a1adbe";ctx.font="9px sans-serif";ctx.fillText(hi.toPrecision(3),1,top+3);ctx.fillText(lo.toPrecision(2),1,height-bottom);
  ctx.fillText(`${(times[0]/1000).toFixed(2)} s`,left,height-4);ctx.fillText(`${(times.at(-1)/1000).toFixed(2)} s`,width-42,height-4);
  ctx.strokeStyle=color;ctx.lineWidth=1.4;ctx.beginPath();let open=false;
  values.forEach((v,i)=>{if(!Number.isFinite(v)){open=false;return;}if(open)ctx.lineTo(x(times[i]),y(v));else ctx.moveTo(x(times[i]),y(v));open=true;});ctx.stroke();
  if(Number.isFinite(current)&&current>=times[0]&&current<=times.at(-1)){ctx.strokeStyle="#8c969e";ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(x(current),top);ctx.lineTo(x(current),height-bottom);ctx.stroke();ctx.setLineDash([]);}
}
function drawChemicalReadout() {
  const c=state.chemistry, name=$("#chemical-species").value, ci=Number($("#chemical-compartment").value),si=c?.species.indexOf(name),baseline=$("#chemical-condition").value==="baseline";
  const values=c?chemicalTrace(c,si,ci,baseline):[];
  drawRecordedLine($("#chemical-trace"),c?.time_ms,values,"#66d5b4",state.time);
  const value=c?fieldValue(c,state.frame,si,ci,baseline):null;
  $("#chemical-value").textContent=Number.isFinite(value)?`${value.toFixed(5)} a.u.`:"—";
  $("#chemical-trace-label").textContent=`${speciesLabel(name)} · ${c?.compartments[ci]?regionLabel(c.compartments[ci]):"unavailable"} · ${baseline?"baseline":"stimulated"}`;
  const stateName=$("#state-trace-variable").value;
  $("#state-condition-label").textContent=baseline?"Matched baseline state":"Stimulated state";
  drawRecordedLine($("#state-trace"),c?.time_ms,c&&c.state_names.includes(stateName)?stateTrace(c,stateName,baseline):[],"#b2a1ff",state.time);
  $("#state-readings").innerHTML=c?c.state_names.map((name,i)=>{const v=(baseline?c.baseline_state_values:c.state_values)?.[state.frame*c.state_names.length+i];return `<span>${escapeHTML(name)} ${Number.isFinite(v)?v.toFixed(3):"—"}</span>`;}).concat(c.hormone_names.map((name,i)=>{const v=(baseline?c.baseline_hormones_au:c.hormones_au)?.[state.frame*c.hormone_names.length+i];return `<span>${escapeHTML(name)} ${Number.isFinite(v)?v.toFixed(4)+" a.u.":"—"}</span>`;})).join(""):"No recorded internal state; missing values are not zero.";
}
async function stopAll() {
  setPlaying(false);state.playing=false;state.previewStopped=true;state.previewDirty=true;++state.overviewToken;++state.morphologyToken;if(controls)controls.autoRotate=false;$("#rotate-button").classList.remove("active");
  $("#global-engine-status").textContent="STOPPING…";
  const result=await requestJSON("/api/stop-all",{method:"POST"});
  if(!result.active_jobs){finishJob();$("#global-engine-status").textContent="STOPPED";}
  else $("#global-engine-status").textContent="STOP REQUESTED";
  return result;
}
async function clearDisplayCache() {
  $("#clear-cache").disabled=true;
  try {
    let stopped=await stopAll();
    for(let i=0;stopped.active_jobs&&i<16;i++){await new Promise(resolve=>setTimeout(resolve,250));stopped=await stopAll();}
    if(stopped.active_jobs)throw Error("An active worker is still stopping. Cache is preserved; retry when stopped.");
    const result=await requestJSON("/api/cache/clear",{method:"POST"});
    if("caches" in window)for(const key of await caches.keys())await caches.delete(key);
    ++runLoadToken;++state.overviewToken;++state.morphologyToken;
    state.summary=null;state.recordingMetadata=null;state.recordedToAnatomy=null;state.anatomyToRecorded=null;state.projectedFrame=null;state.activity={};state.chemistry=null;state.chemicalCache=null;state.stimulusFrames=null;state.eyeLuminance=null;
    for(const item of [points,overviewLines,morphologyLines]){item?.geometry?.dispose();item?.material?.dispose();}
    morphologyTexture?.dispose();regionAtlas?.dispose();flyBodyPanel?.dispose();renderer?.dispose();renderer=null;
    toast(`Cleared ${formatNumber(result.bytes_removed)} bytes of generated display cache. Recordings, source data, evidence and preferences are preserved.`);
    location.reload();
  }catch(error){toast(error.message);$("#clear-cache").disabled=false;}
}
function previewSettings() {
  const s = settings(),
    v = s.visual_overrides || {},
    frameRate =
      v.frame_rate ??
      state.bootstrap?.parameter_schema?.find?.((e) => e.key === "frame_rate")
        ?.default ??
      240,
    frameMs = 1000 / frameRate,
    spacing =
      v.eye_spacing ??
      state.bootstrap?.parameter_schema?.find?.((e) => e.key === "eye_spacing")
        ?.default ??
      5.1,
    onset = v.apparent_onset_ms ?? 100;
  return {
    ...s,
    eye_spacing_deg: spacing,
    apparent_flash_duration_ms: frameMs,
    apparent_flash_radius_deg:
      (v.apparent_point_radius_columns ?? 0.45) * spacing,
    apparent_effective_interval_ms:
      Math.floor((s.apparent_interval_ms ?? (4 * 1000) / 240) / frameMs + 0.5) *
      frameMs,
    apparent_effective_onset_ms: Math.floor(onset / frameMs + 0.5) * frameMs,
  };
}
function runSettings() {
  const s = state.summary?.stimulus || {};
  return {
    ...settings(),
    ...s,
    stimulus: s.type || s.stimulus || settings().stimulus,
  };
}
function markPreviewEdited() {
  state.previewDirty=true;
  state.previewEdited = !!state.summary;
  state.previewStart = performance.now();
  if (state.summary) {
    $(".input-note").textContent =
      "Edited input preview. Run again to record a matching brain response.";
    $(".input-note").classList.add("edited");
  }
}
function updateControls() {
  const s = settings();
  const directions = {
    0: "rightward",
    45: "up-right",
    90: "upward",
    135: "up-left",
    180: "leftward",
    225: "down-left",
    270: "downward",
    315: "down-right",
  };
  $("#direction-output").textContent =
    `${s.direction_deg}° · ${directions[s.direction_deg] || ""}`;
  $("#speed-output").textContent = `${s.speed_deg_s} °/s`;
  $("#contrast-output").textContent = `${Math.round(s.contrast * 100)}%`;
  $("#duration-output").textContent =
    `${(s.duration_ms / 1000).toFixed(2).replace(/0$/, "")} s`;
  $("#stimulus-screen-title").textContent = labels[s.stimulus].toUpperCase();
  $$("[data-direction]").forEach((button) =>
    button.classList.toggle(
      "active",
      Number(button.dataset.direction) === s.direction_deg,
    ),
  );
  const moving = ["grating", "edge", "apparent_motion"].includes(s.stimulus);
  $("#direction").disabled = !moving;
  $$("[data-direction]").forEach((button) => (button.disabled = !moving));
  $("#speed").disabled = !["grating", "edge", "looming"].includes(s.stimulus);
  $("#contrast").disabled = s.stimulus === "dark";
  $("#apparent-controls").hidden = s.stimulus !== "apparent_motion";
  $("#grating-controls").hidden = s.stimulus !== "grating";
  $("#spatial-period-field").hidden = s.stimulus !== "grating";
  $("#mean-luminance").disabled = s.stimulus === "dark";
  const preview = previewSettings();
  $("#apparent-interval-output").textContent =
    `${preview.apparent_effective_interval_ms.toFixed(2)} ms effective`;
  $("#apparent-frame-note").textContent =
    `Two point flashes · ${(1000 / preview.apparent_flash_duration_ms).toFixed(0)} Hz source frames · ${preview.apparent_flash_duration_ms.toFixed(2)} ms each.`;
  $("#apparent-separation-output").textContent =
    `${$("#apparent-separation").value} ${Number($("#apparent-separation").value) === 1 ? "column" : "columns"} · ${(Number($("#apparent-separation").value) * preview.eye_spacing_deg).toFixed(1)}°`;
  if (!state.summary) {
    $("#time-total").textContent = (s.duration_ms / 1000).toFixed(3);
    $("#timeline-mid").textContent = formatNumber(s.duration_ms / 2);
    $("#timeline-end").textContent = `${formatNumber(s.duration_ms)} ms`;
  }
  workspaceOverview?.refresh();
}

const renderingHealth={rafCalls:0,timerTicks:0,resizeCalls:0,draws:0,lastDrawMs:null,lastRafMs:null,errors:[],shaderErrors:[]};
function renderingDiagnostics(){
  const canvas=renderer?.domElement,box=canvas?.getBoundingClientRect(),gl=renderer?.getContext();
  return{native:!!window.__COGNESIA_DESKTOP__,visibility:document.visibilityState,focused:document.hasFocus(),
    brain:{...renderingHealth,connected:!!canvas?.isConnected,canvas:[canvas?.width,canvas?.height],
      cssSize:[box?.width,box?.height],experimentHidden:$("#experiment-view")?.hidden,
      renderState:canvas?.dataset.renderState,contextLost:gl?.isContextLost(),contextAttributes:gl?.getContextAttributes(),
      rendererCalls:renderer?.info.render.calls,rendererPoints:renderer?.info.render.points,
      camera:camera?.position.toArray(),cameraAspect:camera?.aspect,sourceNeurons:pointCount,
      sceneChildren:scene?.children.length,dirty:state.sceneDirty},fly:flyBodyPanel?.diagnostics?.()||null};
}
window.cognesiaRenderingDiagnostics=renderingDiagnostics;
function setupScene() {
  const container = $("#brain-canvas");
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(36, 1, 0.001, 1000);
  camera.position.set(0, 0, 4);
  renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "high-performance",
    // WKWebView may composite a static canvas after its drawing buffer clears.
    preserveDrawingBuffer: !!window.__COGNESIA_DESKTOP__,
  });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0xffffff, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.appendChild(renderer.domElement);
  renderer.domElement.dataset.renderState='ready';
  renderer.debug.onShaderError=(gl,program,vertex,fragment)=>{renderingHealth.shaderErrors.push({program:gl.getProgramInfoLog(program),vertex:gl.getShaderInfoLog(vertex),fragment:gl.getShaderInfoLog(fragment)});renderingHealth.shaderErrors=renderingHealth.shaderErrors.slice(-3);};
  const redrawWhenVisible=()=>{if(document.visibilityState==='hidden')return;state.sceneDirty=true;state.previewDirty=true;flyBodyPanel?.requestRender();};
  document.addEventListener('visibilitychange',redrawWhenVisible);
  window.addEventListener('pageshow',redrawWhenVisible);window.addEventListener('focus',redrawWhenVisible);
  renderer.domElement.addEventListener('webglcontextlost',event=>{event.preventDefault();event.currentTarget.dataset.renderState='context-lost';state.sceneDirty=true;});
  renderer.domElement.addEventListener('webglcontextrestored',event=>{event.currentTarget.dataset.renderState='restored';redrawWhenVisible();});
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.07;
  controls.rotateSpeed = 0.55;
  controls.zoomSpeed = 0.7;
  controls.autoRotateSpeed = 0.6;
  controls.minDistance = 0.1;
  controls.maxDistance = 30;
  controls.addEventListener("change",()=>{state.sceneDirty=true;});
  controls.addEventListener("start", () => {
    state.cameraView = "custom";
    $$("[data-view]").forEach((button) => button.classList.remove("active"));
  });
  const resizeScene = () => {
    renderingHealth.resizeCalls++;
    const { width, height } = container.getBoundingClientRect();
    if (width<=0 || height<=0) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / Math.max(height, 1);
    camera.updateProjectionMatrix();
    if (geometry && state.cameraView !== 'custom') setCameraView(state.cameraView);
    state.sceneDirty=true;state.previewDirty=true;
  };
  resizeObserver = new ResizeObserver(resizeScene);
  resizeObserver.observe(container);
  window.addEventListener('resize',resizeScene);
  window.addEventListener('cognesia-render-quality',event=>{
    const requested=Number(event.detail?.pixelRatio);
    if(!Number.isFinite(requested)||requested<=0)return;
    const ratio=Math.min(requested,Math.max(1,devicePixelRatio),2);
    renderer.setPixelRatio(ratio);
    if(material)material.uniforms.uPointSize.value=2.3*ratio;
    resizeScene();
  });
  if(window.__COGNESIA_DESKTOP__){
    const addError=message=>{renderingHealth.errors.push(String(message));renderingHealth.errors=renderingHealth.errors.slice(-4);};
    window.addEventListener('error',event=>addError(`${event.message} ${event.filename}:${event.lineno}`));
    window.addEventListener('unhandledrejection',event=>addError(event.reason?.stack||event.reason));
    // A bounded diagnostic probe distinguishes startup timer/RAF scheduling.
    // It never advances simulation or triggers a render.
    renderingHealth.timerProbeComplete=false;
    const timer=setInterval(()=>{renderingHealth.timerTicks++;if(renderingHealth.timerTicks>=10){clearInterval(timer);renderingHealth.timerProbeComplete=true;}},1000);
    window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
  }
  let start = null;
  renderer.domElement.addEventListener(
    "pointerdown",
    (event) => (start = [event.clientX, event.clientY]),
  );
  renderer.domElement.addEventListener("pointerup", (event) => {
    if (
      start &&
      Math.hypot(start[0] - event.clientX, start[1] - event.clientY) < 4 &&
      event.button === 0
    )
      inspectPoint(event);
    start = null;
  });
}
function setCameraView(view = "overview") {
  if (!camera || !controls) return;
  state.cameraView = view;
  const directions = {
    overview: [0.07, -0.08, 1],
    xy: [0, 0, 1],
    xz: [0, -1, 0],
    yz: [1, 0, 0],
  };
  const sides = state.metadata?.analysis?.orientation?.positions;
  if (sides?.left && sides?.right) {
    const axis = sides.right.normalized.map((v, i) => v - sides.left.normalized[i]);
    directions.left = axis.map((v) => -v);
    directions.right = axis;
  } else {
    if (["left", "right"].includes(view)) {
      toast("Annotated left/right orientation is not available for this model.");
      return;
    }
  }
  camera.up.set(0, 1, 0);
  if (["xz", "yz"].includes(view)) camera.up.set(0, 0, 1);
  const direction=directions[view] || directions.overview;
  const distance=state.sceneBounds?fittedCameraDistance(state.sceneBounds,direction,camera.up.toArray(),camera.fov,camera.aspect):boundsRadius*3.7;
  const vector = new THREE.Vector3(...direction).normalize().multiplyScalar(distance);
  camera.position.copy(vector);
  camera.near=Math.max(.0001,boundsRadius/1000);camera.far=Math.max(100,distance*20);
  camera.updateProjectionMatrix();controls.minDistance=Math.max(.02,boundsRadius*.05);controls.maxDistance=Math.max(30,distance*5);
  controls.target.set(0, 0, 0);
  controls.update();
  updateOrientation();
  $$("[data-view]").forEach((button) =>
    button.classList.toggle("active", button.dataset.view === view),
  );
  $(".axis-v").textContent = view === "xz" || view === "yz" ? "Z" : "Y";
  $(".axis-h").textContent = view === "yz" ? "Y" : "X";
}
function updateOrientation() {
  if (!camera) return;
  const positions = state.metadata?.analysis?.orientation?.positions;
  const stage = $("#brain-stage"), width = stage.clientWidth, height = stage.clientHeight;
  const projected = {};
  for (const side of ["left", "right"]) {
    const marker = $(`#brain-${side}-marker`), point = positions?.[side]?.normalized;
    marker.hidden = !point || !width || !height;
    if (marker.hidden) continue;
    const p = new THREE.Vector3(...point).sub(new THREE.Vector3(...(state.sceneOffset||[0,0,0]))).project(camera);
    const x = (p.x + 1) * width / 2, y = (1 - p.y) * height / 2;
    projected[side] = [x, y];
    marker.hidden = p.z < -1 || p.z > 1 || x < 12 || x > width - 12 || y < 45 || y > height - 35;
    marker.style.left = `${x}px`;
    marker.style.top = `${y}px`;
  }
  if (projected.left && projected.right && Math.hypot(projected.left[0] - projected.right[0], projected.left[1] - projected.right[1]) < 32) {
    $("#brain-left-marker").hidden = true;
    $("#brain-right-marker").hidden = true;
  }
  $("#orientation-note").textContent = ["left", "right"].includes(state.cameraView)
    ? `Viewing from fly's ${state.cameraView} side · L / R are anatomical labels`
    : "L / R: fly's sides";
}
function makePointCloud() {
  pointCount = state.positions.length / 3;
  const centered=centeredAnatomy(state.positions,state.visibleIndices);
  state.sceneOffset=centered.offset;state.sceneBounds=centered.bounds;boundsRadius=centered.radius;
  geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.BufferAttribute(centered.positions, 3),
  );
  const groupColors = new Float32Array(pointCount * 3);
  const groups = state.metadata?.groups || state.bootstrap?.groups || [];
  const lookup = new Map(
    groups.map((group, index) => [
      group.id ?? index,
      new THREE.Color(group.color || palette[index%palette.length]).lerp(new THREE.Color('#c9d9e8'),.3),
    ]),
  );
  for (let index = 0; index < pointCount; index++) {
    const color = lookup.get(state.groups[index]) || new THREE.Color("#536373");
    groupColors[index * 3] = color.r;
    groupColors[index * 3 + 1] = color.g;
    groupColors[index * 3 + 2] = color.b;
  }
  geometry.setAttribute(
    "aGroupColor",
    new THREE.BufferAttribute(groupColors, 3),
  );
  geometry.setAttribute("aRegion", new THREE.BufferAttribute(new Float32Array(pointCount).fill(1),1));
  geometry.setAttribute(
    "aActivity",
    new THREE.BufferAttribute(new Float32Array(pointCount), 1).setUsage(
      THREE.DynamicDrawUsage,
    ),
  );
  geometry.setIndex(new THREE.BufferAttribute(centered.visibleIndices, 1));
  geometry.computeBoundingSphere();
  material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.NormalBlending,
    uniforms: {
      uActive: { value: 0 },
      uAbsolute: { value: 0 },
      uChemical: { value: 0 },
      uRange: { value: 5 },
      uPointSize: { value: 2.3 * renderer.getPixelRatio() },
      uCloudOpacity: { value: 1 },
      uRegionFocus: { value: 0 },
    },
    vertexShader: `attribute float aRegion; uniform float uRegionFocus; attribute vec3 aGroupColor; attribute float aActivity; uniform float uActive; uniform float uAbsolute; uniform float uChemical; uniform float uRange; uniform float uPointSize; varying vec3 vColor; varying float vOpacity; void main(){ vec4 mvPosition=modelViewMatrix*vec4(position,1.0); gl_Position=projectionMatrix*mvPosition; float value=aActivity; float normalized=clamp(abs(value)/max(uRange,0.001),0.0,1.0); vec3 cool=vec3(0.25,0.65,1.0); vec3 hot=vec3(1.0,0.46,0.28); vec3 quiet=vec3(0.58,0.64,0.70); vec3 activityColor=mix(quiet,value>=0.0?hot:cool,pow(normalized,0.45)); if(uAbsolute>0.5){ normalized=clamp((value+90.0)/110.0,0.0,1.0); activityColor=mix(cool,hot,normalized); } if(uChemical>0.5){normalized=clamp(value/max(uRange,0.000001),0.0,1.0);activityColor=mix(vec3(.12,.22,.24),vec3(.1,.78,.59),sqrt(normalized));if(value<0.0)activityColor=vec3(.61,.64,.66);} vColor=mix(aGroupColor,activityColor,uActive); vOpacity=mix(0.72,0.28+0.68*pow(normalized,0.4),uActive); if(uActive>.5 && (value < -1e20 || (uChemical>.5 && value<0.0))){vColor=vec3(.48,.55,.64);vOpacity=.42;normalized=0.0;} vOpacity*=mix(1.0,mix(0.045,1.0,aRegion),uRegionFocus); gl_PointSize=uPointSize*(0.60+normalized*uActive*1.00)*(1.0+uRegionFocus*aRegion*.5); }`,
    fragmentShader: `uniform float uCloudOpacity; varying vec3 vColor; varying float vOpacity; void main(){float dist=length(gl_PointCoord-0.5)*2.0;if(dist>1.0)discard;float alpha=smoothstep(1.0,0.30,dist)*vOpacity*uCloudOpacity;gl_FragColor=vec4(vColor,alpha);}`,
  });
  points = new THREE.Points(geometry, material);
  installSectionShader(material, true);
  scene.add(points);state.sceneDirty=true;
  regionAtlas=createRegionAtlas({THREE,camera,stage:$("#brain-stage"),host:$("#region-atlas-controls"),overlay:$("#brain-region-labels"),regions:state.metadata?.regions||[],offset:state.sceneOffset,
    getRegion:sourceRegion,onDirty:()=>{state.sceneDirty=true;},onSelect:indices=>{
      const mask=geometry.attributes.aRegion.array;mask.fill(indices?0:1);if(indices)for(const index of indices)if(index>=0&&index<pointCount)mask[index]=1;
      geometry.attributes.aRegion.needsUpdate=true;material.uniforms.uRegionFocus.value=indices?1:0;state.sceneDirty=true;
    }});
  flyBodyPanel?.setBrain((state.metadata?.model_id || "flywire-783") === "flywire-783" && state.metadata?.anatomy_scope!=='recorded_historical' ? {positions:state.positions,visibleIndices:state.visibleIndices} : null);
  initializeBrainSections();
  setCameraView();
  $("#stage-loading").hidden = true;
  $("#visible-count").textContent =
    `${formatNumber(state.visibleIndices?.length || pointCount)} POSITIONS`;
  window.dispatchEvent(new Event('cognesia-anatomy-ready'));
}
function installSectionShader(shader, region = false) {
  if (!shader?.isShaderMaterial || shader.userData.sectionInstalled) return;
  shader.userData.sectionInstalled = true;
  shader.uniforms.uSectionLive={value:0};
  shader.uniforms.uSectionEnabled={value:sectionState.enabled?1:0};shader.uniforms.uSectionAxis={value:new THREE.Vector3(0,0,1)};
  shader.uniforms.uSectionCenter={value:0};shader.uniforms.uSectionHalf={value:.1};shader.uniforms.uSectionIsolate={value:0};
  const attribute=region&&!/attribute\s+float\s+aRegion/.test(shader.vertexShader)?'attribute float aRegion;':'';
  shader.vertexShader=`${attribute} varying vec3 vSectionPosition; varying float vSectionRegion; varying float vSectionAvailable;\n`+shader.vertexShader.replace(/void\s+main\s*\(\s*\)\s*\{/,`void main(){vSectionAvailable=1.0;vSectionPosition=position;vSectionRegion=${region?'aRegion':'1.0'};`);
  if(shader.vertexShader.includes('attribute float aActivity'))shader.vertexShader=shader.vertexShader.replace('vSectionAvailable=1.0;','vSectionAvailable=aActivity > -1e20 ? 1.0:0.0;');
  if(shader.vertexShader.includes('vec4 neuron=texture2D(uNeurons,uv);'))shader.vertexShader=shader.vertexShader.replace('vec4 neuron=texture2D(uNeurons,uv);','vec4 neuron=texture2D(uNeurons,uv);vSectionAvailable=neuron.r > -1e20 ? 1.0:0.0;');
  shader.fragmentShader='uniform float uSectionLive; varying float vSectionAvailable; uniform float uSectionEnabled;uniform vec3 uSectionAxis;uniform float uSectionCenter;uniform float uSectionHalf;uniform float uSectionIsolate;varying vec3 vSectionPosition;varying float vSectionRegion;\n'+shader.fragmentShader.replace(/void\s+main\s*\(\s*\)\s*\{/,'void main(){if(uSectionEnabled>.5 && abs(dot(vSectionPosition,uSectionAxis)-uSectionCenter)>uSectionHalf)discard;if(uSectionIsolate>.5 && vSectionRegion<.5)discard;');
  shader.needsUpdate=true;applySectionState();
}
function applySectionState() {
  const axis=new THREE.Vector3(...[0,1,2].map(i=>i===sectionState.axis?1:0));
  for(const shader of [material,overviewLines?.material]) {
    if(!shader?.uniforms?.uSectionEnabled)continue;
    shader.uniforms.uSectionEnabled.value=sectionState.enabled?1:0;
    shader.uniforms.uSectionAxis.value.copy(axis);shader.uniforms.uSectionCenter.value=sectionState.center;
    shader.uniforms.uSectionHalf.value=sectionState.thickness/2;shader.uniforms.uSectionIsolate.value=sectionState.isolate?1:0;
  }
  if(morphologyLines?.material) {
    renderer.localClippingEnabled=true;
    morphologyLines.material.clippingPlanes=sectionState.enabled?[new THREE.Plane(axis.clone(),sectionState.thickness/2-sectionState.center),new THREE.Plane(axis.clone().negate(),sectionState.thickness/2+sectionState.center)]:[];
    morphologyLines.material.needsUpdate=true;
    if(state.morphologyMode==='arbor')morphologyLines.visible=!sectionState.isolate||state.selectedNeuron===null||geometry.attributes.aRegion.array[state.selectedNeuron]>.5;
  }
  state.sceneDirty=true;
}
async function sourceRegion(key) {
  if(state.metadata?.regions_url) {
    if(state.regionMembershipUrl!==state.metadata.regions_url){state.regionMembership=await requestJSON(state.metadata.regions_url);state.regionMembershipUrl=state.metadata.regions_url;}
    if(!state.regionMembership[key])throw Error('Region is not present in this model');
    return {key,indices:state.regionMembership[key]};
  }
  return requestJSON(`/api/regions/${encodeURIComponent(key)}`);
}
function initializeBrainSections() {
  brainSections?.dispose();
  brainSections=createBrainSections({host:$("#region-atlas-controls"),getRegions:()=>state.metadata?.regions?.map(item=>({...item,name:item.name||regionLabel(item.key)}))||[],
    getPositions:()=>state.positions,getOffset:()=>state.sceneOffset,getRegion:sourceRegion,
    requestJSON:(url,options)=>{if(url==='/api/connectivity'&&options?.body){if(state.metadata?.anatomy_scope==='recorded_historical')throw Error('Full historical connectivity is unavailable in this saved-anatomy view.');const body=JSON.parse(options.body);body.model_hash=state.metadata?.model_hash;return requestJSON(url,{...options,body:JSON.stringify(body)});}return requestJSON(url,options);},onStatus:toast,getRunId:()=>null,
    getModelId:()=>state.metadata?.model_id||'flywire-783',onClip:value=>{Object.assign(sectionState,value);applySectionState();},
    onSelection:(indices,{isolate})=>{
      sectionState.isolate=isolate;const mask=geometry.attributes.aRegion.array;mask.fill(indices?0:1);if(indices)for(const index of indices)mask[index]=1;
      geometry.attributes.aRegion.needsUpdate=true;material.uniforms.uRegionFocus.value=indices?1:0;
      if(overviewLines?.geometry.attributes.aRegion){const target=overviewLines.geometry.attributes.aRegion,owners=overviewLines.geometry.attributes.aOwner.array;for(let i=0;i<owners.length;i++)target.array[i]=mask[owners[i]];target.needsUpdate=true;}
      applySectionState();
    }});
}
async function replaceAnatomy(anatomy, isCurrent = () => true) {
  const [positions,groups,metadata,visibleIndices,identities]=await Promise.all([requestArray(anatomy.positions_url),requestArray(anatomy.groups_url,Uint8Array),requestJSON(anatomy.metadata_url),requestArray(anatomy.visible_indices_url,Uint32Array),anatomy.identities_url?requestJSON(anatomy.identities_url):null]);
  if(!isCurrent())return false;
  if(positions.length!==metadata.neuron_count*3||groups.length!==metadata.neuron_count)throw Error('Anatomy assets have inconsistent row counts.');
  if(anatomy.model_hash&&metadata.model_hash!==anatomy.model_hash)throw Error('Loaded anatomy differs from its requested source version.');
  metadata.anatomy_scope=anatomy.anatomy_scope||'full';metadata.anatomy_note=anatomy.anatomy_note||null;
  metadata.anatomy_unavailable_reason=anatomy.anatomy_unavailable_reason||null;
  regionAtlas?.dispose();brainSections?.dispose();state.overviewToken++;state.morphologyToken++;
  for(const object of [points,overviewLines,morphologyLines])if(object){scene.remove(object);object.geometry?.dispose();object.material?.dispose();}
  overviewLines=null;morphologyLines=null;points=null;state.selectedNeuron=null;state.summary=null;state.recordingMetadata=null;state.recordedToAnatomy=null;state.anatomyToRecorded=null;state.projectedFrame=null;state.activity={};state.chemistry=null;state.liveFrame=null;state.liveVoltage=null;
  state.recordedToAnatomy=null;state.anatomyToRecorded=null;state.recordingMetadata=null;state.projectedFrame=null;state.chemicalCache=null;
  state.positions=positions;state.groups=groups;state.metadata=metadata;state.visibleIndices=visibleIndices;state.anatomyUrl=anatomy.metadata_url;state.anatomyIdentities=identities;
  state.regionMembership=null;state.regionMembershipUrl=null;
  if(morphologyTexture){morphologyTexture.dispose();morphologyTexture=null;}
  sectionState.enabled=false;sectionState.isolate=false;
  makePointCloud();setMorphologyMode('anchors');$("#neuron-count").textContent=formatNumber(pointCount);
  const historical=metadata.anatomy_scope==='recorded_historical';
  const original=!historical&&(metadata.model_id||'flywire-783')==='flywire-783';
  $("#connection-count").textContent=original?'54.49M':'—';$("#connection-count-label").textContent=original?'Synapses':'Connections';
  $("#model-footer").textContent=historical?`Historical recorded anatomy only · ${metadata.model_hash?.slice(0,12)||'saved source'}`:`Computed locally · ${metadata.model_id||'FlyWire v783'}`;
  $(".page-heading h1").textContent=historical?`${modelDisplayName(metadata.model_id)} · ${formatNumber(pointCount)} recorded neurons`:metadata.model_id&&metadata.model_id!=='flywire-783'?`${modelDisplayName(metadata.model_id)} · ${formatNumber(pointCount)} neurons`:'FlyWire v783 · whole-brain model';
  layoutWorkbench?.refresh();
  refreshEyeMap();
  return true;
}
async function switchModelAnatomy(modelId) {
  if(state.job){toast('Model saved for the next run.');return;}
  const token=++runLoadToken;
  const anatomy=await requestJSON(`/api/model-anatomy/${encodeURIComponent(modelId)}/metadata.json`);
  if(token===runLoadToken&&anatomy&&state.anatomyUrl!==anatomy.metadata_url){
    const replaced=await replaceAnatomy(anatomy,()=>token===runLoadToken);
    if(replaced&&token===runLoadToken){
      state.playing=false;state.time=0;state.frame=0;state.stimulusFrames=null;state.eyeLuminance=null;
      $('#saved-runs').value='';$('#run-title').textContent='No recording';$('#recording-label').textContent=`${modelDisplayName(modelId)} · Anatomy`;
      $('#readout-state').textContent='No recording';$('#playback-note').textContent='';$('#fly-time-label').textContent='No recording';
      for(const id of ['play-button','timeline','fly-play-button','fly-timeline'])$('#'+id).disabled=true;
      configureChemicalReadout();updateActivity();buildTraces();sequenceTimeline?.refresh();analysisWorkbench?.refresh();workspaceNotes?.refresh();
    }
  }
}
async function loadAnatomyForRecording(summary, isCurrent = () => true) {
  const modelId=summary.model_id||summary.metadata?.model_id||summary.anatomy?.model_id||'flywire-783';
  const modelHash=summary.model_hash||summary.metadata?.model_hash||summary.anatomy?.model_hash;
  const source=await recordingAnatomySource(summary,async({modelId,modelHash})=>{
    const query=modelHash?`?model_hash=${encodeURIComponent(modelHash)}`:'';
    const full=await requestJSON(`/api/model-anatomy/${encodeURIComponent(modelId)}/metadata.json${query}`);
    if(isCurrent()&&state.anatomyUrl!==full.metadata_url)await replaceAnatomy(full,isCurrent);
    return full;
  });
  if(!isCurrent())return null;
  if(source.scope==='recorded_historical'&&state.anatomyUrl!==source.anatomy.metadata_url)await replaceAnatomy(source.anatomy,isCurrent);
  if(!isCurrent())return null;
  const recordedMetadata=summary.anatomy||state.metadata;
  const recordedIdentities=summary.anatomy?.identities_url?await requestJSON(summary.anatomy.identities_url):null;
  if(!isCurrent())return null;
  const mapping=recordingRowMap({fullCount:pointCount,recordedCount:summary.activity?.shape?.[1]||summary.neuron_count,
    fullIdentities:state.anatomyIdentities,recordedIdentities,fullModelHash:state.metadata.model_hash,recordedModelHash:modelHash,
    recordedIndices:summary.metadata?.recorded_indices,parentIndices:summary.metadata?.selection?.parent_indices,
    allowReleasedOrder:modelId==='flywire-783'&&!summary.anatomy&&!summary.metadata?.selection});
  const receptors=(recordedMetadata.analysis?.receptors||[]).flatMap(r=>{
    const index=summary.anatomy?r.index:mapping.anatomyToRecorded[r.index];
    return index>=0?[{...r,index}]:[];
  });
  return {...mapping,recordingMetadata:{...recordedMetadata,neuron_count:mapping.recordedToAnatomy.length,
    analysis:{...recordedMetadata.analysis,receptors}}};
}
function signalState(){return {...state,metadata:state.recordingMetadata||state.metadata};}
function recordedNeuronIndex(index){return state.anatomyToRecorded?.[index]??-1;}
async function selectedNeuronAnnotation(index) {
  const local=recordedNeuronIndex(index);
  if(state.summary?.anatomy&&local>=0) {
    const query=new URLSearchParams({model_id:state.metadata?.model_id||'flywire-783',run_id:state.summary.id});
    return requestJSON(`/api/neuron/${local}?${query}`);
  }
  const identity=state.anatomyIdentities?.[index];
  if(identity)return {...identity,index,super_class:state.metadata?.groups?.find(g=>g.id===state.groups[index])?.name,
    model_id:state.metadata.model_id,model_hash:state.metadata.model_hash};
  const query=new URLSearchParams({model_id:state.metadata?.model_id||'flywire-783'});
  if(state.metadata?.model_hash)query.set('model_hash',state.metadata.model_hash);
  return requestJSON(`/api/neuron/${index}?${query}`);
}
function applyLiveFrame(frame) {
  if(!geometry||!frame?.voltage_mv)return;
  const indices=frame.parent_indices||frame.indices||[],values=frame.voltage_mv;
  if(indices.length!==values.length)return;
  state.liveFrame=frame;
  if(!state.liveVoltage||state.liveVoltage.length!==pointCount)state.liveVoltage=new Float32Array(pointCount).fill(NaN);
  state.liveVoltage.fill(NaN);
  for(let i=0;i<indices.length;i++)if(indices[i]>=0&&indices[i]<pointCount)state.liveVoltage[indices[i]]=values[i];
  updateActivity();
  $("#connection-state").textContent=`Live ${frame.phase} · ${(Number(frame.model_time_ms)/1000).toFixed(3)} s model time`;
  $("#recording-label").textContent=frame.phase==='core_protocol'?'LIVE · original core protocol · raw activity':frame.baseline_available?'LIVE · matched control available':'LIVE · raw activity · matched control pending';
  if(indices.length<pointCount)$("#recording-label").textContent+=` · ${formatNumber(indices.length)} / ${formatNumber(pointCount)} neurons · gray = unavailable`;
  layoutWorkbench?.setTime(frame.model_time_ms);
  sequenceTimeline?.setLiveFrame?.(frame);
}
function currentValues() {
  if(state.mode==='anatomy')return null;
  if(state.job&&state.liveFrame)return state.mode==='absolute'||state.mode==='baseline'&&state.liveFrame.signal==='baseline'?state.liveVoltage:null;
  if (state.mode === "chemical") return chemicalFrame();
  const source=state.mode==='absolute'?state.activity.raw:state.mode==='baseline'?state.activity.baseline:state.activity.delta;
  if(!source||!state.recordedToAnatomy)return null;
  const cached=state.projectedFrame;
  if(cached?.source===source&&cached.frame===state.frame&&cached.mapping===state.recordedToAnatomy)return cached.values;
  const values=projectRecordingFrame(source,state.frame,state.recordedToAnatomy,pointCount,cached?.values?.length===pointCount?cached.values:undefined);
  state.projectedFrame={source,frame:state.frame,mapping:state.recordedToAnatomy,values};
  return values;
}
function updateActivity() {
  state.sceneDirty=true;
  if (!geometry) return;
  let values=null,displayError=null;
  try{values=currentValues();if(values&&values.length!==pointCount)throw Error("Display frame does not match anatomical rows.");}catch(error){values=null;displayError=error.message;}
  const live=!!(state.job&&state.liveFrame),display=brainDisplayPolicy(state.mode,{live,liveSignal:state.liveFrame?.signal,hasValues:!!values,hasChemistry:!!state.chemistry});
  state.brainDisplay=display;
  const active=display.active&&display.available;
  const displayRange=state.mode==='chemical'&&!live?chemicalRange():Number(state.summary?.activity?.color_range_mv||5);
  applyBrainDisplayUniforms(material.uniforms,display,displayRange);
  writeBrainActivity(geometry.attributes.aActivity.array,values,active);
  geometry.attributes.aActivity.needsUpdate=true;
  const range = displayRange;
  $("#scale-low").textContent =
    state.mode === "chemical" ? (state.chemistry ? "0 a.u." : "Field unavailable") : state.mode === "anatomy"
      ? "Cell class"
      : ["absolute", "baseline"].includes(state.mode)
        ? "−90 mV"
        : `−${Number(range.toPrecision(2))} mV`;
  $("#scale-high").textContent =
    state.mode === "chemical" ? (state.chemistry ? `${Number(range.toPrecision(3))} a.u.` : "") : state.mode === "anatomy"
      ? ""
      : ["absolute", "baseline"].includes(state.mode)
        ? "+20 mV"
        : `+${Number(range.toPrecision(2))} mV`;
  if(!display.available){$("#scale-low").textContent=({chemical:'Field unavailable',baseline:'Baseline unavailable',delta:'ΔV unavailable',absolute:'Voltage unavailable'})[state.mode];$("#scale-high").textContent='';}
  $("#color-scale").title=displayError||display.unavailable||'';
  const scaleColors = state.mode === "chemical" ? ["#a1a8ad","#1f383d","#237967","#1ac796"] : state.mode === "anatomy"
    ? (state.metadata?.groups || state.bootstrap?.groups || [])
        .map((group, index) => plotColor(group.color, index))
    : ["absolute", "baseline"].includes(state.mode)
    ? Array.from({length: 9}, (_, i) => {
        const fraction = i / 8;
        return `rgb(${Math.round(46 + 134 * fraction)},${Math.round(106 - 27 * fraction)},${Math.round(164 - 114 * fraction)})`;
      })
    : ["#2e6aa4", "#3a6997", "#46688a", "#51677d", "#5c6670",
       "#726060", "#885b51", "#9e5541", "#b44f32"];
  $("#color-scale").replaceChildren(...scaleColors.map((color) => {
    const swatch = document.createElement("i");
    swatch.style.backgroundColor = color;
    swatch.style.flex = "1";
    return swatch;
  }));
  if (state.selectedNeuron !== null) updateInspectorValue(values);
  if (morphologyLines && morphologyLines.visible) updateMorphologyColor(values);
  if (overviewLines && overviewLines.visible) updateOverviewActivity(values);
  updateFlyFrame(values);
  drawBrainScene();
  drawTraces();
  drawChemicalReadout();
}
function updateFlyFrame(values=currentValues()) {
  const live=!!(state.job&&state.liveFrame),display=brainDisplayPolicy(state.mode,{live,liveSignal:state.liveFrame?.signal,hasValues:!!values,hasChemistry:!!state.chemistry});
  const available=display.available&&display.active;
  flyBodyPanel?.setFrame({values:available?values:null,mode:state.mode,range:state.mode==="chemical"&&!live?chemicalRange():Number(state.summary?.activity?.color_range_mv||5),timeMs:live?state.liveFrame.model_time_ms:state.time,hasRecording:!!available,
    label:state.mode==="chemical"?`${speciesLabel($("#chemical-species").value)} · ${$("#chemical-condition").value} · model a.u.`:live?'live model membrane voltage · mV':undefined});
}
async function inspectPoint(event) {
  if (!points) return;
  const bounds = renderer.domElement.getBoundingClientRect();
  const mouse = new THREE.Vector2(
    ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
    (-(event.clientY - bounds.top) / bounds.height) * 2 + 1,
  );
  const raycaster = new THREE.Raycaster();
  raycaster.params.Points.threshold = boundsRadius * 0.009;
  raycaster.setFromCamera(mouse, camera);
  const found = raycaster.intersectObject(points).find(hit => {
    const point=geometry.attributes.position.array.subarray(hit.index*3,hit.index*3+3);
    return insideSection(point,sectionState) && (!sectionState.isolate || geometry.attributes.aRegion.array[hit.index] > .5);
  });
  if (!found) {
    state.selectedNeuron = null;
    state.morphologyToken++;
    if (morphologyLines) morphologyLines.visible = false;
    if (state.morphologyMode === "arbor") {
      material.uniforms.uCloudOpacity.value = 0.95;
      $("#morphology-status").textContent =
        "Click a neuron to load its complete real arbor";
    }
    $("#brain-inspector").hidden = true;
    return;
  }
  const index = found.index;
  state.selectedNeuron = index;
  if (state.morphologyMode === "arbor") loadMorphology(index);
  $("#brain-inspector").hidden = false;
  $("#brain-inspector").innerHTML =
    `<strong>Neuron ${formatNumber(index)}</strong><span>Loading annotation…</span>`;
  try {
    const neuron = await selectedNeuronAnnotation(index);
    if (state.selectedNeuron !== index) return;
    const name = neuron.cell_type || neuron.type || "Unclassified neuron";
    $("#brain-inspector").innerHTML =
      `<strong>${escapeHTML(name)}</strong><span>${escapeHTML(neuron.super_class || neuron.class || "")} ${escapeHTML(neuron.hemisphere || neuron.side || "")}</span><span>Root ${escapeHTML(neuron.root_id || neuron.id || index)}</span><span id="inspector-voltage"></span><button id="neuron-electrode-button">＋ Place electrode here</button><button id="neuron-chart-button">Chart this neuron</button>`;
    $("#neuron-chart-button").disabled=recordedNeuronIndex(index)<0;
    updateInspectorValue();
  } catch (error) {
    if (state.selectedNeuron !== index) return;
    $("#brain-inspector").innerHTML =
      `<strong>Neuron ${formatNumber(index)}</strong><span id="inspector-voltage"></span><button id="neuron-electrode-button">＋ Place electrode here</button><button id="neuron-chart-button">Chart this neuron</button>`;
    $("#neuron-chart-button").disabled=recordedNeuronIndex(index)<0;
    updateInspectorValue();
  }
}
function setMorphologyMode(mode) {
  state.sceneDirty=true;
  if (!material) {
    toast("Anatomy is still loading.");
    return;
  }
  if(mode!=='anchors' && ((state.metadata?.model_id||'flywire-783')!=='flywire-783'||state.metadata?.anatomy_scope==='recorded_historical')) {toast('Complete arbors are currently available for the original FlyWire row order. This view uses source annotation anchors.');mode='anchors';}
  const previousMode = state.morphologyMode;
  state.morphologyMode = mode;
  if (previousMode === "arbor" && mode !== "arbor") setCameraView("overview");
  $("#representation-label").textContent =
    mode === "anchors"
      ? "ANNOTATION ANCHORS"
      : mode === "arbor"
        ? "REAL SELECTED ARBOR"
        : "REAL NEURITES";
  $("#visible-count").textContent =
    mode === "overview" && state.overviewSegments
      ? `${formatNumber(state.overviewSegments)} SEGMENTS`
      : `${formatNumber(state.visibleIndices?.length || pointCount)} POSITIONS`;
  state.morphologyEnabled = mode !== "anchors";
  state.morphologyToken++;
  $("#anchor-view-button").classList.toggle("active", mode === "anchors");
  $("#morphology-view-button").classList.toggle("active", mode === "overview");
  $("#arbor-view-button").classList.toggle("active", mode === "arbor");
  $("#morphology-controls").hidden = mode !== "overview";
  $("#morphology-status").classList.remove("error");
  if (morphologyLines) morphologyLines.visible = false;
  if (overviewLines) overviewLines.visible = mode === "overview";
  material.uniforms.uCloudOpacity.value =
    mode === "overview" && overviewLines?.visible ? 0 : 0.95;
  if (mode === "anchors") {
    $("#morphology-status").textContent = "Neuron annotation anchors";
    return;
  }
  if (mode === "arbor") {
    if (state.selectedNeuron !== null) loadMorphology(state.selectedNeuron);
    else
      $("#morphology-status").textContent =
        "Click a neuron to load its complete real arbor";
  } else if (overviewLines) {
    overviewDescription();
    updateOverviewActivity();
    if (state.overviewMetadata?.status === "partial") loadMorphologyOverview();
  } else loadMorphologyOverview();
}
function normalizedSkeletonCoordinate(value, axis, units = "um") {
  return units === "normalized"
    ? value
    : (value * (units === "nm" ? 0.001 : 1) -
        (state.metadata.center_um || [0, 0, 0])[axis]) /
        (state.metadata.scale_um || 1);
}
async function loadMorphology(index) {
  state.sceneDirty=true;
  const token = ++state.morphologyToken;
  if (morphologyLines) morphologyLines.visible = false;
  if (state.morphologyNeuron === index && morphologyLines) {
    morphologyLines.visible = state.morphologyMode === "arbor";
    material.uniforms.uCloudOpacity.value = 0.12;
    $("#morphology-status").textContent =
      `Complete source arbor · ${formatNumber(state.morphologyMetadata.node_count || state.morphologyMetadata.vertex_count || morphologyLines.geometry.attributes.position.count / 2 + 1)} nodes · one model state per neuron; chemical exposure is compartment-level`;
    updateMorphologyColor();
    focusSelectedArbor();
    return;
  }
  material.uniforms.uCloudOpacity.value = 0.95;
  $("#morphology-status").classList.remove("error");
  $("#morphology-status").textContent = "Loading complete source arbor…";
  try {
    let metadata = await requestJSON(`/api/morphology/${index}`);
    for (
      let attempt = 0;
      ["loading", "pending", "queued", "running", "preparing"].includes(
        metadata.status,
      ) && attempt < 40;
      attempt++
    ) {
      $("#morphology-status").textContent =
        metadata.message || "Preparing source arbor…";
      await new Promise((resolve) => setTimeout(resolve, 1200));
      if (token !== state.morphologyToken || state.selectedNeuron !== index)
        return;
      metadata = await requestJSON(`/api/morphology/${index}`);
    }
    if (!metadata.vertices_url || !metadata.edges_url)
      throw new Error(
        metadata.message ||
          "Source arbor unavailable; prepare the morphology library first.",
      );
    const [vertices, edges] = await Promise.all([
      requestArray(metadata.vertices_url),
      requestArray(metadata.edges_url, Uint32Array),
    ]);
    if (
      token !== state.morphologyToken ||
      state.selectedNeuron !== index ||
      state.morphologyMode !== "arbor"
    )
      return;
    if (vertices.length % 3 || edges.length % 2)
      throw new Error("Invalid source arbor geometry");
    const positions = new Float32Array(edges.length * 3),
      units = metadata.coordinate_units || metadata.units || "um";
    for (let i = 0; i < edges.length; i++) {
      if (edges[i] * 3 + 2 >= vertices.length)
        throw new Error("Source edge is outside vertex table");
      for (let axis = 0; axis < 3; axis++)
        positions[i * 3 + axis] = normalizedSkeletonCoordinate(
          vertices[edges[i] * 3 + axis],
          axis,
          units,
        );
    }
    if (morphologyLines) {
      scene.remove(morphologyLines);
      morphologyLines.geometry.dispose();
      morphologyLines.material.dispose();
    }
    const skeletonGeometry = new THREE.BufferGeometry();
    skeletonGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(positions, 3),
    );
    morphologyLines = new THREE.LineSegments(
      skeletonGeometry,
      new THREE.LineBasicMaterial({
        color: 0x2866a5,
        transparent: true,
        opacity: 0.95,
        depthWrite: false,
      }),
    );
    scene.add(morphologyLines);state.sceneDirty=true;
    state.morphologyNeuron = index;
    state.morphologyMetadata = { ...metadata, node_count: vertices.length / 3 };
    material.uniforms.uCloudOpacity.value = 0.12;
    $("#morphology-status").textContent =
      `Complete source arbor · ${formatNumber(vertices.length / 3)} nodes · one model state per neuron; chemical exposure is compartment-level`;
    updateMorphologyColor();
    focusSelectedArbor();
  } catch (error) {
    if (token !== state.morphologyToken) return;
    $("#morphology-status").textContent = error.message;
    $("#morphology-status").classList.add("error");
    if (morphologyLines) morphologyLines.visible = false;
    material.uniforms.uCloudOpacity.value = 0.95;
  }
}
function focusSelectedArbor() {
  if (!morphologyLines) return;
  morphologyLines.geometry.computeBoundingSphere();
  const sphere = morphologyLines.geometry.boundingSphere;
  if (!sphere || !Number.isFinite(sphere.radius)) return;
  const direction = camera.position.clone().sub(controls.target).normalize();
  controls.target.copy(sphere.center);
  camera.position
    .copy(sphere.center)
    .addScaledVector(direction, Math.max(0.12, sphere.radius * 3.7));
  controls.update();
  $("#visible-count").textContent =
    `${formatNumber(state.morphologyMetadata?.node_count)} SOURCE NODES`;
  $$("[data-view]").forEach((button) => button.classList.remove("active"));
}
function morphologyProgressText(metadata) {
  const raw = metadata.progress ?? metadata.fraction;
  const progress = Number.isFinite(Number(raw))
    ? ` · ${Math.round(Number(raw) * (Number(raw) > 1 ? 1 : 100))}%`
    : "";
  return `${metadata.message || metadata.stage || metadata.status || "Preparing morphology library"}${progress}`;
}
async function waitForMorphologyLibrary(token, budget) {
  let status = await requestJSON("/api/morphology/status");
  const ready = (s) =>
    ["ready", "complete", "completed"].includes(s.status) || s.ready;
  const underway = [
    "queued",
    "running",
    "downloading",
    "verifying",
    "indexing",
    "importing",
    "connecting",
    "preparing",
    "processing",
  ];
  if (!ready(status) && !underway.includes(status.status))
    status = await requestJSON("/api/morphology/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  let attempt = 0;
  while (!ready(status)) {
    if (token !== state.overviewToken) return false;
    if (["failed", "error", "cancelled"].includes(status.status))
      throw new Error(
        status.error || status.message || "Morphology preparation stopped",
      );
    $("#morphology-progress").textContent = morphologyProgressText(status);
    if (attempt % 4 === 0) {
      try {
        const partial = await requestJSON(
          `/api/morphology/overview?budget=${budget}`,
        );
        if (partial.positions_url && partial.owners_url) return partial;
      } catch {}
    }
    await new Promise((resolve) => setTimeout(resolve, 1800));
    status = await requestJSON("/api/morphology/status");
    attempt++;
  }
  return token === state.overviewToken;
}
async function monitorMorphologyPreparation(token) {
  while (token === state.overviewToken) {
    try {
      const status = await requestJSON("/api/morphology/status");
      if (status.status === "ready") {
        $("#morphology-progress").textContent =
          "Complete source library ready · loading all covered neurons";
        if (state.morphologyMode === "overview") loadMorphologyOverview();
        return;
      }
      $("#morphology-progress").textContent =
        `Partial geometry displayed · ${morphologyProgressText(status)}`;
      if (["failed", "cancelled"].includes(status.status)) return;
    } catch {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 2500));
  }
}
async function loadMorphologyOverview() {
  const budget = Number($("#morphology-detail").value),
    token = ++state.overviewToken;
  $("#load-morphology").disabled = true;
  $("#morphology-status").classList.remove("error");
  $("#morphology-status").textContent = "Preparing real neurites…";
  try {
    const readiness = await waitForMorphologyLibrary(token, budget);
    if (!readiness) return;
    $("#morphology-progress").textContent =
      `Streaming ${formatNumber(budget)} real branch segments…`;
    const metadata =
      typeof readiness === "object"
        ? readiness
        : await requestJSON(`/api/morphology/overview?budget=${budget}`);
    if (!metadata.positions_url || !metadata.owners_url)
      throw new Error(
        metadata.message || "Whole-brain morphology assets unavailable",
      );
    const [positions, owners] = await Promise.all([
      requestArray(metadata.positions_url),
      requestArray(metadata.owners_url, Uint32Array),
    ]);
    if (token !== state.overviewToken) return;
    if (positions.length !== owners.length * 6)
      throw new Error("Morphology segment and owner arrays disagree");
    const attributes = new Float32Array(owners.length * 2),
      units = metadata.coordinate_units || metadata.units || "um";
    for (let i = 0; i < owners.length; i++) {
      if (owners[i] >= pointCount)
        throw new Error("Morphology owner is outside neuron table");
      attributes[2 * i] = owners[i];
      attributes[2 * i + 1] = owners[i];
      for (let j = 0; j < 6; j++)
        positions[i * 6 + j] = normalizedSkeletonCoordinate(
          positions[i * 6 + j],
          j % 3,
          units,
        );
    }
    const skeletonGeometry = new THREE.BufferGeometry();
    skeletonGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(positions, 3),
    );
    skeletonGeometry.setAttribute("aRegion", new THREE.BufferAttribute(Float32Array.from(attributes, owner => geometry.attributes.aRegion.array[owner]), 1));
    skeletonGeometry.setAttribute(
      "aOwner",
      new THREE.BufferAttribute(attributes, 1),
    );
    ensureMorphologyTexture();
    const shader = new THREE.ShaderMaterial({
      uniforms: {
        uNeurons: { value: morphologyTexture },
        uTextureSize: {
          value: new THREE.Vector2(
            morphologyTexture.image.width,
            morphologyTexture.image.height,
          ),
        },
        uActive: { value: 0 },
        uAbsolute: { value: 0 },
        uChemical: { value: 0 },
        uRange: { value: 5 },
      },
      vertexShader: `attribute float aOwner;uniform sampler2D uNeurons;uniform vec2 uTextureSize;uniform float uActive;uniform float uAbsolute; uniform float uChemical;uniform float uRange;varying vec3 vColor;varying float vAlpha;void main(){vec2 uv=(vec2(mod(aOwner,uTextureSize.x),floor(aOwner/uTextureSize.x))+0.5)/uTextureSize;vec4 neuron=texture2D(uNeurons,uv);float strength=clamp(abs(neuron.r)/max(uRange,0.001),0.0,1.0);vec3 hot=vec3(1.,.46,.28);vec3 cool=vec3(.25,.65,1.);vec3 responseColor=mix(vec3(.58,.64,.70),neuron.r>=0.0?hot:cool,pow(strength,.45));if(uAbsolute>.5){strength=clamp((neuron.r+90.0)/110.0,0.0,1.0);responseColor=mix(cool,hot,strength);}if(uChemical>.5){strength=clamp(neuron.r/max(uRange,0.000001),0.,1.);responseColor=mix(vec3(.12,.22,.24),vec3(.1,.78,.59),sqrt(strength));if(neuron.r<0.)responseColor=vec3(.61,.64,.66);}vColor=mix(neuron.gba,responseColor,uActive);vAlpha=mix(.32,.18+.55*pow(strength,.4),uActive);if(uActive>.5 && (neuron.r < -1e20 || (uChemical>.5 && neuron.r<0.))){vColor=vec3(.48,.55,.64);vAlpha=.20;}gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`,
      fragmentShader:
        "varying vec3 vColor;varying float vAlpha;void main(){gl_FragColor=vec4(vColor,vAlpha);}",
      transparent: true,
      depthWrite: false,
      blending: THREE.NormalBlending,
    });
    if (overviewLines) {
      scene.remove(overviewLines);
      overviewLines.geometry.dispose();
      overviewLines.material.dispose();
    }
    installSectionShader(shader, true);
    overviewLines = new THREE.LineSegments(skeletonGeometry, shader);
    overviewLines.visible = state.morphologyMode === "overview";
    scene.add(overviewLines);state.sceneDirty=true;
    state.overviewMetadata = metadata;
    state.overviewSegments = owners.length;
    if (overviewLines.visible) {
      material.uniforms.uCloudOpacity.value = 0;
      overviewDescription();
    }
    $("#morphology-progress").textContent =
      `${formatNumber(metadata.represented_neuron_count || metadata.represented_neurons || metadata.neuron_count || 0)} represented neurons · sampled real neurites · unclassified axon / dendrite`;
    updateOverviewActivity();
    if (metadata.status === "partial") monitorMorphologyPreparation(token);
  } catch (error) {
    if (token !== state.overviewToken) return;
    $("#morphology-status").textContent = error.message;
    $("#morphology-status").classList.add("error");
    $("#morphology-progress").textContent =
      "Real source geometry only. Retry after the local library is ready.";
    if (!overviewLines) material.uniforms.uCloudOpacity.value = 0.95;
  } finally {
    if (token === state.overviewToken) $("#load-morphology").disabled = false;
  }
}
function overviewDescription() {
  $("#visible-count").textContent =
    `${formatNumber(state.overviewSegments)} SEGMENTS`;
  $("#representation-label").textContent =
    state.overviewMetadata?.status === "partial"
      ? "REAL NEURITES · PARTIAL"
      : "REAL NEURITES";
  $("#morphology-status").textContent =
    `${state.overviewMetadata?.status === "partial" ? `Partial coverage: ${formatNumber(state.overviewMetadata.represented_neuron_count)} / ${formatNumber(pointCount)} neurons · ` : ""}${formatNumber(state.overviewSegments)} real segments · model values shared across each neuron’s branches`;
}
function ensureMorphologyTexture() {
  if (morphologyTexture) return;
  const width = 512,
    height = Math.ceil(pointCount / width),
    data = new Float32Array(width * height * 4),
    colors = geometry.attributes.aGroupColor.array;
  for (let i = 0; i < pointCount; i++) {
    data[4 * i + 1] = colors[3 * i];
    data[4 * i + 2] = colors[3 * i + 1];
    data[4 * i + 3] = colors[3 * i + 2];
  }
  morphologyTexture = new THREE.DataTexture(
    data,
    width,
    height,
    THREE.RGBAFormat,
    THREE.FloatType,
  );
  morphologyTexture.minFilter = THREE.NearestFilter;
  morphologyTexture.magFilter = THREE.NearestFilter;
  morphologyTexture.needsUpdate = true;
}
function updateOverviewActivity(values=currentValues()) {
  if (!overviewLines || !morphologyTexture) return;
  const live=!!(state.job&&state.liveFrame),display=brainDisplayPolicy(state.mode,{live,liveSignal:state.liveFrame?.signal,hasValues:!!values,hasChemistry:!!state.chemistry});
  applyBrainDisplayUniforms(overviewLines.material.uniforms,display,state.mode==='chemical'&&!live?chemicalRange():Number(state.summary?.activity?.color_range_mv||5));
  const data=morphologyTexture.image.data;
  for(let i=0;i<pointCount;i++)data[4*i]=display.available&&display.active&&Number.isFinite(values?.[i])?values[i]:-1e30;
  morphologyTexture.needsUpdate=true;
}
function updateMorphologyColor(values=currentValues()) {
  if (!morphologyLines) return;
  const value = values?.[activityOffset() + state.morphologyNeuron];
  if (state.mode === "chemical") {
    morphologyLines.material.color.set(!Number.isFinite(value)||value<0 ? "#9ca3a8" : "#1f383d");
    if(Number.isFinite(value)&&value>=0)morphologyLines.material.color.lerp(new THREE.Color("#1ac796"),Math.sqrt(Math.min(1,value/chemicalRange())));
    return;
  }
  if (!Number.isFinite(value) || state.mode === "anatomy") {
    morphologyLines.material.color.set(state.mode==='anatomy'?"#65b5ff":"#899caf");
    return;
  }
  const absolute = ["absolute", "baseline"].includes(state.mode),
    scale = Number(state.summary?.activity?.color_range_mv || 5);
  const strength = absolute
    ? Math.max(0, Math.min(1, (value + 90) / 110))
    : Math.max(0, Math.min(1, Math.abs(value) / scale));
  const color = new THREE.Color(absolute ? "#2e6aa4" : "#5c6670");
  color.lerp(
    new THREE.Color(absolute || value >= 0 ? "#b44f32" : "#2e6aa4"),
    strength,
  );
  morphologyLines.material.color.copy(color);
}
function updateInspectorValue(values=currentValues()) {
  const element = $("#inspector-voltage");
  if (!element) return;
  if(state.mode === "anatomy"){element.textContent="Source-annotated neuron";return;}
  const value = values?.[activityOffset() + state.selectedNeuron];
  if(state.mode === "chemical"){const c=state.chemistry,n=recordedNeuronIndex(state.selectedNeuron),m=c?.neuron_membership;const assignments=m&&n>=0?Array.from({length:m.indptr[n+1]-m.indptr[n]},(_,j)=>c.compartments[m.indices[m.indptr[n]+j]]).join(", "):"";element.textContent=Number.isFinite(value)&&value>=0?`${$("#chemical-species").value} ${value.toFixed(5)} a.u. · ${assignments} · weighted model exposure; branch owner value`:"Chemical exposure unavailable: no recorded/assigned compartment.";return;}
  element.textContent = Number.isFinite(value)
    ? `${signed(value)} mV ${state.mode === "absolute" ? "absolute" : state.mode === "baseline" ? "baseline" : "stimulus − baseline"}`
    : state.summary||state.liveFrame?"Activity unavailable: this neuron was not recorded.":"Anatomical annotation anchor";
}

function resizeCanvas(canvas) {
  const ratio = Math.min(devicePixelRatio || 1, 2);
  const width = Math.max(1, canvas.clientWidth),
    height = Math.max(1, canvas.clientHeight);
  if (
    canvas.width !== Math.round(width * ratio) ||
    canvas.height !== Math.round(height * ratio)
  ) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, width, height };
}
function stimulusAt(x, y, t, s) {
  const contrast = s.contrast ?? 0.8,
    mean = s.mean_luminance ?? 0.5;
  const amplitude = Math.min(mean, 1 - mean) * contrast;
  const axis =
    x * Math.cos(((s.direction_deg || 0) * Math.PI) / 180) +
    y * Math.sin(((s.direction_deg || 0) * Math.PI) / 180);
  const type = s.stimulus || s.type;
  const speed = s.speed_deg_s ?? 80;
  let signal = 0;
  if (type === "dark") return 0;
  else if (type === "grating") {
    signal = Math.sin(
      (2 * Math.PI * (axis - (speed * t) / 1000)) /
        (s.spatial_period_deg || 30),
    );
    if (s.grating_waveform !== "sine") signal = signal >= 0 ? 1 : -1;
  } else if (type === "flash")
    signal = t >= 0.25 * s.duration_ms && t < 0.75 * s.duration_ms ? 1 : -1;
  else if (type === "edge")
    signal = axis <= speed * (t / 1000 - s.duration_ms / 2000) ? 1 : -1;
  else if (type === "looming")
    signal = Math.hypot(x, y) <= 2 + (speed * t) / 1000 ? -1 : 1;
  else if (type === "apparent_motion") {
    const separation =
      (s.apparent_separation_columns ?? 1) * (s.eye_spacing_deg ?? 5.1);
    const direction = ((s.direction_deg || 0) * Math.PI) / 180;
    const dx = Math.cos(direction) * separation * 0.5,
      dy = Math.sin(direction) * separation * 0.5;
    const frameMs = s.apparent_flash_duration_ms ?? 1000 / 240;
    const interval =
      s.apparent_effective_interval_ms ??
      s.apparent_interval_ms_effective ??
      s.apparent_interval_ms ??
      4 * frameMs;
    const onset =
      s.apparent_effective_onset_ms ?? s.apparent_flash_onset_ms ?? 100;
    const radius = s.apparent_flash_radius_deg ?? 2.295;
    const frame = Math.floor(t / frameMs + 1e-9),
      onsetFrame = Math.floor(onset / frameMs + 0.5),
      intervalFrames = Math.floor(interval / frameMs + 0.5);
    const on1 = frame === onsetFrame;
    const on2 = frame === onsetFrame + intervalFrames;
    signal =
      (on1 && Math.hypot(x + dx, y + dy) <= radius) ||
      (on2 && Math.hypot(x - dx, y - dy) <= radius)
        ? 1
        : 0;
  }
  return Math.max(0, Math.min(1, mean + amplitude * signal));
}
function drawStimulus(now) {
  const { ctx, width, height } = resizeCanvas($("#stimulus-canvas"));
  const recorded = state.summary && !state.previewEdited;
  const s = recorded ? runSettings() : previewSettings();
  const time = recorded
    ? state.time
    : (now - state.previewStart) % s.duration_ms;
  const stored = state.stimulusFrames;
  const shape = state.summary?.stimulus_frames?.shape;
  if (recorded && stored && shape) {
    const [, rows, columns] = shape;
    stimulusFrameCanvas.width = columns;
    stimulusFrameCanvas.height = rows;
    const off = stimulusFrameCanvas.getContext("2d");
    const image = off.createImageData(columns, rows);
    const frameIndex = state.summary.stimulus_frames.dt_ms
      ? Math.floor(state.time / state.summary.stimulus_frames.dt_ms + 1e-9)
      : state.frame;
    const offset = Math.min(frameIndex, shape[0] - 1) * columns * rows;
    for (let i = 0; i < columns * rows; i++) {
      image.data[i * 4] = stored[offset + i];
      image.data[i * 4 + 1] = stored[offset + i];
      image.data[i * 4 + 2] = stored[offset + i];
      image.data[i * 4 + 3] = 255;
    }
    off.putImageData(image, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(stimulusFrameCanvas, 0, 0, width, height);
  } else {
    const step = 2;
    for (let y = 0; y < height; y += step)
      for (let x = 0; x < width; x += step) {
        const level = Math.round(
          stimulusAt(
            (x / width - 0.5) * 360,
            (0.5 - y / height) * 180,
            time,
            s,
          ) * 255,
        );
        ctx.fillStyle = `rgb(${level},${level},${level})`;
        ctx.fillRect(x, y, step, step);
      }
  }
  $("#preview-status").textContent = recorded
    ? "RECORDED INPUT"
    : state.summary
      ? "EDITED PREVIEW"
      : "PREVIEW";
  $("#stimulus-screen-title").textContent = (
    labels[s.stimulus] ||
    s.stimulus ||
    "STIMULUS"
  ).toUpperCase();
  drawEyes(time, s, recorded);
  updateLabPlayback(time, Boolean(recorded));
}
function eyeColumns() {
  if(state.summary?.eyes?.columns)return state.summary.eyes.columns;
  const modelId=state.metadata?.model_id||'flywire-783';
  if(state.eyeMap?.model_id===modelId)return state.eyeMap.columns||[];
  return state.metadata?.eye_columns||[];
}
function eyeReceptors(){return state.summary ? state.recordingMetadata?.analysis?.receptors||[] : state.eyeMap?.model_id===(state.metadata?.model_id||'flywire-783')&&state.eyeMap?.model_hash===state.metadata?.model_hash?state.eyeMap.receptors||[]:[];}
async function refreshEyeMap(){
  const modelId=state.metadata?.model_id||'flywire-783';
  if(state.summary?.eyes?.columns){workspaceOverview?.refresh();return;}
  try{
    const mapping=await requestJSON(`/api/model-eyes?model_id=${encodeURIComponent(modelId)}`);
    if(state.summary?.eyes?.columns)return;
    if((state.metadata?.model_id||'flywire-783')!==modelId)return;
    if(mapping.model_id!==modelId||mapping.model_hash&&state.metadata?.model_hash&&mapping.model_hash!==state.metadata.model_hash)throw Error('Eye mapping belongs to a different model version.');
    state.eyeMap=mapping;state.selectedEyeColumn=null;state.previewDirty=true;
    workspaceOverview?.refresh();drawStimulus(performance.now());
  }catch(error){if((state.metadata?.model_id||'flywire-783')===modelId){state.eyeMap=null;workspaceOverview?.refresh();$('#eye-note').textContent=`Eye map unavailable: ${error.message}`;}}
}
function drawEyes(time, s, recorded) {
  const { ctx, width, height } = resizeCanvas($("#eyes-canvas"));
  ctx.clearRect(0, 0, width, height);
  state.eyeHitTargets = [];
  const columns = eyeColumns();
  if (!columns.length) {
    ctx.fillStyle = "#a1adbe";
    ctx.font = "9px -apple-system, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("No eye columns available for this model", width / 2, height / 2);
    return;
  }
  let luminance = recorded
    ? state.summary.eyes?.luminance?.[state.frame]
    : null;
  if (recorded && state.eyeLuminance && state.summary.eyes?.shape) {
    const [frameCount, columnCount] = state.summary.eyes.shape;
    const frame = Math.min(
      frameCount - 1,
      Math.max(
        0,
        Math.floor(time / (state.summary.eyes.dt_ms || 1000 / 240) + 1e-9),
      ),
    );
    luminance = state.eyeLuminance.subarray(
      frame * columnCount,
      (frame + 1) * columnCount,
    );
  }
  const hemispheres = state.eyeOrientation === "facing" ? ["right", "left"] : ["left", "right"];
  $("#eye-left-label").textContent = `Fly's ${hemispheres[0]} eye`;
  $("#eye-right-label").textContent = `Fly's ${hemispheres[1]} eye`;
  hemispheres.forEach((side, sideIndex) => {
    const selected = columns
      .map((column, index) => ({ column, index }))
      .filter(({ column }) =>
        String(column.hemisphere || column.side)
          .toLowerCase()
          .startsWith(side[0]),
      );
    if (!selected.length) return;
    const coords = selected.map(({ column }) => {
      const p = Number(column.p ?? column.q ?? column.x ?? 0),
        q = Number(column.q ?? column.r ?? column.y ?? 0);
      return [(Math.sqrt(3) / 2) * (q - p), 0.5 * (p + q)];
    });
    const minX = Math.min(...coords.map((c) => c[0])),
      maxX = Math.max(...coords.map((c) => c[0])),
      minY = Math.min(...coords.map((c) => c[1])),
      maxY = Math.max(...coords.map((c) => c[1]));
    const scale = Math.min(
      (width * 0.44) / (maxX - minX + 2),
      (height * 0.9) / (maxY - minY + 2),
    );
    const midX = (minX + maxX) / 2,
      midY = (minY + maxY) / 2;
    selected.forEach(({ column, index }, k) => {
      const x =
          width * (sideIndex ? 0.75 : 0.25) + (coords[k][0] - midX) * scale,
        y = height / 2 - (coords[k][1] - midY) * scale;
      let level = luminance?.[index];
      if (!Number.isFinite(level)) {
        level = stimulusAt(
          Number(column.azimuth_deg || 0),
          Number(column.elevation_deg || 0),
          time,
          s,
        );
      }
      level = Math.max(0, Math.min(1, level));
      const gray = Math.round(35 + level * 195);
      ctx.fillStyle = `rgb(${gray},${gray},${gray})`;
      ctx.beginPath();
      const radius = Math.max(0.65, scale * 0.5);
      for (let j = 0; j < 6; j++) {
        const a = (Math.PI / 3) * j;
        const px = x + Math.cos(a) * radius,
          py = y + Math.sin(a) * radius;
        j ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
      }
      ctx.closePath();
      ctx.fill();
      state.eyeHitTargets.push({index, x, y, radius});
    });
  });
  const highlight = state.eyeHitTargets.find((p) => p.index === state.selectedEyeColumn);
  if (highlight) {
    ctx.beginPath();
    ctx.arc(highlight.x, highlight.y, Math.max(4, highlight.radius * 2), 0, Math.PI * 2);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#65b5ff";
    ctx.stroke();
  }
  $("#eye-sample-label").textContent = luminance ? "RECORDED" : "PREVIEW";
  $("#eye-note").textContent = luminance
    ? "Sampled luminance at the recorded frame. Source column coordinates; viewing angles are assumed."
    : "Preview sampled at column axes; recorded input includes optical smoothing.";
  $("#eye-count").textContent = formatNumber(columns.length);
}

function selectEyeColumn(index) {
  state.selectedEyeColumn = index;
  const column = eyeColumns()[index];
  if (!column) return;
  const receptors = eyeReceptors()
    .filter((r) => r.column_index === (column.column_index ?? index));
  $("#eye-selection-note").textContent = `${column.hemisphere || column.side} eye · column ${column.column_id ?? index} · ${receptors.length} mapped receptors`;
  $("#pin-eye-column").disabled = !state.eyeLuminance;
  $("#eye-receptor").disabled = !receptors.length;
  $("#pin-eye-receptor").disabled = !receptors.length || !state.summary;
  $("#eye-receptor").replaceChildren(...(receptors.length ? receptors.map((r) => {
    const option = document.createElement("option");
    option.value = r.index;
    option.textContent = `${r.cell_type} · ${r.index} · root ${r.root_id}`;
    return option;
  }) : [new Option("No assigned receptor", "")]));
  drawStimulus(performance.now());
  workspaceOverview?.sensory.refreshSelection();
}

function pinTrace(index) {
  const trace = tracesForView()[index];
  if (!trace) return;
  const group = state.readout === "regions" ? "region" : state.readout === "classes" ? "class" : "type";
  const key = {type: "traces", region: "region_traces", class: "class_traces"}[group];
  const source = state.summary[key]?.findIndex((item) => item.name === trace.name || (item.name === "None" && trace.name === "Unassigned ROI"));
  if (!(source >= 0)) return;
  const mode = state.mode === "absolute" ? "raw" : state.mode === "baseline" ? "baseline" : "delta";
  pinSignal(`trace:${group}:${source}:${mode}`);
}
async function pinSignal(id) {
  if (await analysisWorkbench?.addSignal(id)) {
    sequenceWorkspace?.show('analysis');
    $("#analysis-workspace").scrollIntoView({block: "nearest"});
  }
}

function buildClassTraces() {
  state.summary.class_traces=recordedClassTraces({groups:state.metadata?.groups||state.bootstrap.groups||[],
    groupIds:state.groups,mapping:state.recordedToAnatomy,frameCount:state.summary.frames.count,activity:state.activity});
}
function tracesForView() {
  let traces = state.summary?.traces || [];
  if (state.readout !== "types") {
    const regions =
      (state.readout === "regions"
        ? state.summary?.region_traces
        : state.summary?.class_traces) || [];
    traces = (Array.isArray(regions) ? regions : regions.traces || []).map(
      (trace) => ({
        ...trace,
        values: trace.values || trace.delta_mv,
        raw: trace.raw || trace.raw_mv,
        baseline: trace.baseline || trace.baseline_mv,
        description:
          trace.description ||
          (state.readout === "regions"
            ? "Synapse-weighted area mean voltage"
            : "Annotated cell class · mean voltage"),
      }),
    );
  }
  if (state.readout === "types") {
    const family = $("#trace-family")?.value || "pathway";
    const names = {
      pathway: ["R1-6", "L1", "Mi1", "T4a", "HS/VS", "Descending"],
      motion: ["T4a", "T4b", "T4c", "T4d", "T5a", "T5b", "T5c", "T5d"],
      input: ["R1-6", "R7/R8", "L1", "L2", "Mi1"],
      output: ["LPLC2", "HS/VS", "Descending"],
    }[family];
    if (names) traces = traces.filter((trace) => names.includes(trace.name));
  }
  if (state.readout !== "types") {
    const query = $("#trace-search").value.trim().toLowerCase();
    traces = traces.map((trace) => ({
      ...trace,
      name: trace.name === "None" ? "Unassigned ROI" : trace.name,
    }));
    if (query)
      traces = traces.filter((trace) =>
        `${trace.name} ${state.readout === "regions" ? regionLabel(trace.name) : ""}`.toLowerCase().includes(query),
      );
  }
  return traces;
}
function buildTraces() {
  const traces = tracesForView();
  const container = $("#traces-container");
  if (!traces.length) {
    container.innerHTML = `<div class="empty-readout"><svg viewBox="0 0 140 54" aria-hidden="true"><path d="M0 28h34l8-9 9 18 9-26 9 32 9-15h62"/></svg><h3>${state.summary ? "No traces in this group." : "Recorded neural responses"}</h3><p>${state.summary ? "This run does not include these readouts." : "Traces will show the engine’s recorded values after your experiment finishes."}</p></div>`;
    return;
  }
  container.innerHTML = traces
    .map(
      (trace, index) =>
        `<div class="trace-item" style="--trace-color:${escapeHTML(plotColor(trace.color, index))}"><div class="trace-head"><span class="trace-name"><i></i>${escapeHTML(state.readout === "regions" ? regionLabel(trace.name || trace.label) : trace.name || trace.label)}</span><span class="trace-value" id="trace-value-${index}">—</span><button class="pin-trace" data-pin-trace="${index}" aria-label="Compare ${escapeHTML(state.readout === "regions" ? regionLabel(trace.name || trace.label) : trace.name || trace.label)}">Chart</button></div><canvas id="trace-canvas-${index}" aria-label="${escapeHTML(trace.name)} recorded voltage trace"></canvas><div class="trace-subtitle"><span>${escapeHTML(trace.description || ((trace.n_recorded ?? trace.n_total) ? `${formatNumber(trace.n_recorded ?? trace.n_total)} neurons · mean voltage` : "Mean recorded voltage"))}</span><span>mV</span></div></div>`,
    )
    .join("");
  drawTraces();
}
function traceValues(trace) {
  return ["absolute","chemical"].includes(state.mode)
    ? trace.raw || trace.values
    : state.mode === "baseline"
      ? trace.baseline || trace.values
      : trace.values;
}
function drawTraces() {
  tracesForView().forEach((trace, index) => {
    const canvas = $(`#trace-canvas-${index}`);
    if (!canvas) return;
    const { ctx, width, height } = resizeCanvas(canvas);
    ctx.clearRect(0, 0, width, height);
    const values = traceValues(trace) || [];
    if (!values.length) return;
    const finite = (
      state.mode === "absolute"
        ? [...values, ...(trace.baseline || [])]
        : values
    ).filter(Number.isFinite);
    if (!finite.length) return;
    let min = Math.min(...finite),
      max = Math.max(...finite);
    if (!["absolute", "baseline"].includes(state.mode)) {
      min = Math.min(0, min);
      max = Math.max(0, max);
    }
    const pad = Math.max((max - min) * 0.13, 0.001);
    min -= pad;
    max += pad;
    const px = (i) => (i / Math.max(values.length - 1, 1)) * width,
      py = (v) => height - 3 - ((v - min) / (max - min)) * (height - 6);
    const zero = py(0);
    ctx.strokeStyle = "#343b48";
    ctx.lineWidth = 0.6;
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(0, Math.max(3, Math.min(height - 3, zero)));
    ctx.lineTo(width, Math.max(3, Math.min(height - 3, zero)));
    ctx.stroke();
    ctx.setLineDash([]);
    if (state.mode === "absolute" && trace.baseline?.length) {
      ctx.strokeStyle = "#6b737c";
      ctx.lineWidth = 0.8;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      trace.baseline.forEach((v, i) =>
        i ? ctx.lineTo(px(i), py(v)) : ctx.moveTo(px(i), py(v)),
      );
      ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.beginPath();
    values.forEach((value, i) =>
      i ? ctx.lineTo(px(i), py(value)) : ctx.moveTo(px(i), py(value)),
    );
    ctx.strokeStyle = plotColor(trace.color, index);
    ctx.lineWidth = 1.3;
    ctx.stroke();
    const frame = Math.min(state.frame, values.length - 1),
      x = px(frame),
      y = py(values[frame]);
    ctx.strokeStyle = "#78828d80";
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
    ctx.fillStyle = plotColor(trace.color, index);
    ctx.beginPath();
    ctx.arc(x, y, 2, 0, Math.PI * 2);
    ctx.fill();
    $(`#trace-value-${index}`).textContent = `${signed(values[frame])} mV`;
  });
}
function duration() {
  return Number(
    state.summary?.stimulus?.duration_ms ||
      state.summary?.frames?.time_ms?.at(-1) ||
      settings().duration_ms,
  );
}
function setTime(time) {
  const previousFrame = state.frame;
  state.time = Math.max(0, Math.min(duration(), time));
  if (state.summary) {
    const times = state.summary.frames?.time_ms;
    const dt = Number(state.summary.frames?.dt_ms || 20);
    state.frame = Math.min(
      Number(state.summary.frames?.count || 1) - 1,
      Math.max(0, Math.round(state.time / dt)),
    );
    if (times?.length) {
      let low=0,high=times.length;
      while(low<high){const mid=(low+high)>>>1;if(times[mid]<=state.time)low=mid+1;else high=mid;}
      state.frame=Math.max(0,low-1);
    }
  }
  $("#time-current").textContent = (state.time / 1000).toFixed(3);
  $("#timeline").value = String(state.time);
  $("#fly-timeline").value=String(state.time);
  $("#fly-time-label").textContent=state.summary?`${(state.time/1000).toFixed(3)} / ${(duration()/1000).toFixed(3)} s · recorded`:"No recording loaded";
  sequenceTimeline?.setTime(state.time);
  analysisWorkbench?.setTime(state.time);
  layoutWorkbench?.setTime(state.time);
  if (state.frame !== previousFrame) updateActivity();
  else drawChemicalReadout();
}
function setPlaying(playing) {
  if (!state.summary) return;
  state.playing = playing;
  sequenceTimeline?.setTime(state.time);
  $("#play-button").textContent = playing ? "Ⅱ" : "▶";
  $("#fly-play-button").textContent=playing?"Pause recorded activity":"Play recorded activity";
  $("#play-button").setAttribute(
    "aria-label",
    playing ? "Pause recorded simulation" : "Play recorded simulation",
  );
  const recordedCount=state.recordedToAnatomy?.length||pointCount;
  const coverage=state.metadata?.anatomy_scope==='recorded_historical'?' · HISTORICAL RECORDED ANATOMY ONLY':recordedCount<pointCount?` · ${formatNumber(recordedCount)} / ${formatNumber(pointCount)} neurons · gray = unavailable`:'';
  $("#recording-label").textContent=`${modelDisplayName(state.summary?.model_id||state.metadata?.model_id)} · ${playing?'Playback':'Results'}${coverage}`;
}
function setMode(mode) {
  brainDisplayPolicy(mode); // Validate before changing any controls or buffers.
  state.mode = mode;state.projectedFrame=null;state.chemicalCache=null;state.sceneDirty=true;
  $("#fly-color-mode").value=mode;
  $$("[data-mode]").forEach((button) =>
    {button.classList.toggle("active", button.dataset.mode === mode);button.setAttribute('aria-pressed',String(button.dataset.mode===mode));}
  );
  $("#readout-footnote").textContent = ({anatomy:"Source-annotated cell classes.",absolute:"Membrane voltage · mV",baseline:"Matched baseline · mV",chemical:"Modeled exposure · a.u. · gray = unavailable",delta:"Stimulus − baseline · mV · model stability unresolved"})[mode];
  if(mode==='chemical')workspaceOverview?.showChemicalInspector?.();
  try{updateActivity();}finally{if(state.sceneDirty)drawBrainScene();}
  if(state.brainDisplay?.unavailable)$("#readout-footnote").textContent=state.brainDisplay.unavailable;
}
async function refreshRuns() {
  const data = await requestJSON("/api/runs");
  const runs = Array.isArray(data) ? data : data.runs || [];
  state.bootstrap.runs = runs;
  const select = $("#saved-runs"),
    current = state.summary?.id || select.value;
  select.replaceChildren(
    new Option(
      runs.length ? "Choose a recorded run" : "No visual runs yet",
      "",
    ),
  );
  runs.forEach((run) => select.add(new Option(run.label || run.id, run.id)));
  if (current) select.value = current;
  return runs;
}
async function loadRun(id) {
  if (!id) return;
  if(state.job){toast('A simulation is active. Use a comparison panel to inspect saved recordings.');return;}
  const token = ++runLoadToken;
  state.runLoading = true;
  setPlaying(false);
  $("#connection-state").textContent = "Loading recorded activity…";
  try {
    const summary = await requestJSON(
      `/api/runs/${encodeURIComponent(id)}/summary.json`,
    );
    if(token!==runLoadToken)return;
    const mapping=await loadAnatomyForRecording(summary,()=>token===runLoadToken);
    if(token!==runLoadToken||!mapping)return;
    state.liveFrame = null;
    const activity = summary.activity || {};
    let chemistryError=null;
    const [delta, raw, baseline, stimulusFrames, eyeLuminance, chemistry] =
      await Promise.all([
        activity.delta_url ? requestArray(activity.delta_url) : null,
        activity.raw_url ? requestArray(activity.raw_url) : null,
        activity.baseline_url ? requestArray(activity.baseline_url) : null,
        summary.stimulus_frames?.url
          ? requestArray(summary.stimulus_frames.url, Uint8Array)
          : null,
        summary.eyes?.luminance_url
          ? requestArray(summary.eyes.luminance_url)
          : null,
        loadChemicalRecording(summary).catch(error=>{chemistryError=error.message;return null;}),
      ]);
    if (token !== runLoadToken) return;
    const recordedCount=summary.activity?.shape?.[1]||summary.neuron_count;
    const expected = (summary.frames?.count || 0) * recordedCount;
    if (delta && delta.length !== expected)
      throw new Error(
        `Recorded activity size does not match ${recordedCount} neurons × ${summary.frames.count} frames.`,
      );
    if (raw && raw.length !== expected)
      throw new Error("Absolute-voltage array is incomplete.");
    if(baseline&&baseline.length!==expected)throw Error('Baseline-voltage array is incomplete.');
    Object.assign(state,mapping);state.projectedFrame=null;
    state.summary = summary;
    if(summary.model_id&&summary.model_id!=='flywire-783'&&summary.metadata?.n_edges_released)$("#connection-count").textContent=formatNumber(summary.metadata.n_edges_released);
    if(summary.partial||summary.baseline_available===false||!summary.activity?.delta_url)state.mode='absolute';
    state.chemistry=chemistry;state.chemicalCache=null;state.chemistryError=chemistryError;
    configureChemicalReadout();
    state.activity = { delta, raw, baseline };
    state.stimulusFrames = stimulusFrames;
    state.eyeLuminance = eyeLuminance;
    state.lastInputFrame = -1;
    summary.stats = {
      ...summary.stats,
      clamps: summary.stats?.clamps ?? summary.stats?.clamp_count,
      baseline_clamps:
        summary.stats?.baseline_clamps ?? summary.stats?.baseline_clamp_count,
      spikes: summary.stats?.spikes ?? summary.stats?.spike_count,
    };
    buildClassTraces();
    state.previewEdited = false;
    $(".input-note").innerHTML =
      summary.activity?.baseline_url?"Paired stimulus and baseline runs.<br>Model assumptions remain visible.":"Recorded raw activity.<br>Matched-control differences are unavailable.";
    $(".input-note").classList.remove("edited");
    state.frame = 0;
    state.time = 0;
    const options = summary.stimulus || {};
    const type = options.type || options.stimulus;
    if (type && labels[type]) $("#stimulus-type").value = type;
    for (const [control, key, scale] of [
      ["direction", "direction_deg", 1],
      ["speed", "speed_deg_s", 1],
      ["contrast", "contrast", 100],
      ["duration", "duration_ms", 1],
      ["mean-luminance", "mean_luminance", 1],
      ["spatial-period", "spatial_period_deg", 1],
    ])
      if (options[key] !== undefined)
        $(`#${control}`).value = options[key] * scale;
    $("#grating-waveform").value = options.grating_waveform || "square";
    if (options.apparent_interval_ms !== undefined)
      $("#apparent-interval").value =
        (options.apparent_interval_ms * 240) / 1000;
    if (options.apparent_separation_columns !== undefined)
      $("#apparent-separation").value = options.apparent_separation_columns;
    restoreLabOptions(options);
    restoreChemicalOptions(options);
    setLabRecording(summary.stimulation, options.duration_ms);
    updateControls();
    $("#run-title").textContent =
      summary.label ||
      `${labels[type] || "Visual experiment"} · paired baseline`;
    $("#play-button").disabled = false;
    $("#timeline").disabled = false;
    $("#timeline").max = String(duration());
    $("#fly-timeline").max=String(duration());$("#fly-timeline").disabled=false;$("#fly-play-button").disabled=false;
    $("#time-total").textContent = (duration() / 1000).toFixed(3);
    $("#timeline-mid").textContent = formatNumber(Math.round(duration() / 2));
    $("#timeline-end").textContent = `${formatNumber(duration())} ms`;
    $("#clamp-count").textContent = formatNumber(summary.stats?.clamps);
    $("#baseline-clamp-count").textContent = formatNumber(
      summary.stats?.baseline_clamps,
    );
    $("#spike-count").textContent = formatNumber(summary.stats?.spikes);
    $("#readout-state").textContent = "Recorded engine output";
    $("#playback-note").textContent =
      `${summary.frames?.dt_ms?`${summary.frames.dt_ms} ms snapshots`:'Exact recorded timestamps'} · ${summary.activity?.baseline_url?'paired runs share the same initial state':summary.partial?'partial raw recording':'raw protocol recording; no matched control'} · ${formatNumber(summary.stats?.clamps)} clamp events.`;
    $("#recording-label").textContent = recordedCount<pointCount?`RECORDED · ${formatNumber(recordedCount)} / ${formatNumber(pointCount)} neurons · gray = unavailable`:"RECORDED";
    $("#connection-state").textContent = state.metadata?.anatomy_scope==='recorded_historical'?"Saved recording · historical recorded anatomy only":"Engine connected · saved locally";
    if(state.metadata?.anatomy_note){$("#playback-note").textContent+=` ${state.metadata.anatomy_note}`;$("#playback-note").title=state.metadata.anatomy_unavailable_reason||'';}
    $("#saved-runs").value = id;
    buildTraces();
    analysisWorkbench?.refresh();
    sequenceTimeline?.refresh();
    workspaceOverview?.refresh();
    workspaceNotes?.refresh();
    layoutWorkbench?.refresh();
    if (state.selectedEyeColumn !== null) selectEyeColumn(state.selectedEyeColumn);
    setMode(state.mode);
    setTime(0);
    setPlaying(false);
    $("#global-engine-status").textContent="STOPPED · recording ready";
    state.runLoading = false;
    showRunWarnings(summary);
  } catch (error) {
    if (token !== runLoadToken) return;
    state.runLoading = false;
    $("#connection-state").textContent = "Could not load recorded run";
    toast(error.message);
    throw error;
  }
}
function showRunWarnings(summary) {
  if (summary.stats?.clamps > 0)
    $("#clamp-count").closest("span").title =
      "Voltage bounds were reached. This run is experimental and has not passed numerical stability validation.";
}
async function runSimulation(override) {
  if (state.job || state.submitting) return false;
  let options;
  try {options=override?.model_id||override?.from_checkpoint?override:settings(true);} catch(error){toast(error.message);return false;}
  state.submitting = true;
  sequenceTimeline?.setLiveFrame?.({phase:'preparing',model_time_ms:0});
  $("#global-engine-status").textContent="RUNNING · explicit request";
  setPlaying(false);
  $("#run-button").disabled = true;
  setLabRunning(true);
  $("#run-button-text").textContent = "Running experiment";
  $("#job-progress").hidden = false;
  $("#job-message").textContent = "Preparing stimulus and matched baseline…";
  $(".job-progress>div>span").style.width = "0%";
  try {
    await switchModelAnatomy(options.model_id||'flywire-783');
    const job = await requestJSON("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
    });
    state.job = job.id || job.job_id;
    experimentControls?.updateJob(job);
    experimentControls?.stream(state.job);
    state.submitting = false;
    $("#cancel-job").hidden = false;
    $("#cancel-job").disabled = false;
    $("#cancel-job").textContent = "Stop experiment";
    return await pollJob(state.job);
  } catch (error) {
    finishJob();
    toast(`Simulation stopped: ${error.message}`);
    $("#job-progress").hidden = false;
    $("#job-message").textContent = error.message;
    return false;
  }
}
async function pollJob(id) {
  const job = await requestJSON(`/api/jobs/${encodeURIComponent(id)}`);
  if (state.job !== id) return;
  experimentControls?.updateJob(job);
  if (job.status === "cancelled") {
    finishJob();
    if(job.run_id){await refreshRuns();await loadRun(job.run_id);}
    toast(job.run_id?"Stopped. Committed partial samples are ready for inspection.":"Experiment stopped. Checkpoint and previous recordings remain available.");
    return false;
  }
  if (job.status === "failed") {
    throw new Error(
      job.error || job.message || "The engine reported a failed run.",
    );
  }
  if (job.status === "complete") {
    finishJob();
    await refreshRuns();
    await loadRun(job.run_id);
    toast("Recorded experiment ready and stopped. Press Play to inspect it.");
    return true;
  }
  await new Promise((resolve) => setTimeout(resolve, 750));
  return pollJob(id);
}
function finishJob() {
  state.submitting = false;
  state.job = null;
  state.liveFrame = null;
  state.liveVoltage = null;
  sequenceTimeline?.setLiveFrame?.(null);
  updateActivity();
  experimentControls?.stream(null);
  experimentControls?.updateJob(null);
  experimentControls?.refresh();
  $("#global-engine-status").textContent="STOPPED";
  $("#cancel-job").hidden = true;
  $("#run-button").disabled = false;
  setLabRunning(false);
  $("#run-button-text").textContent = "Run simulation";
  $("#job-progress").hidden = true;
}
function showDetails(run = false) {
  const summary = state.summary;
  $("#dialog-title").textContent =
    run && summary
      ? summary.label || "Recorded experiment"
      : "Experimental, inspectable, local.";
  let content = `<div class="warning-box"><strong>Experimental · stability check failed.</strong><br>The uniform hybrid model has not passed its numerical stability gate. Visual experiments can be inspected, but they do not establish validated biological behavior.</div><h3>What is real</h3><p>FlyWire v783 connectivity, ${formatNumber(state.bootstrap?.neuron_count || 138639)} neurons, and annotation positions from the released dataset. Each point is one neuron’s annotation anchor, not its branching morphology. Missing positions are omitted from the view.</p><h3>What the colors mean</h3><p><strong>Stimulus − baseline</strong> shows membrane voltage in the stimulated simulation minus its matched baseline at the same time. <strong>Absolute voltage</strong> retains the ongoing model dynamics. <strong>Baseline</strong> displays the paired constant-luminance control. Delta colors saturate at the recorded 99.5th percentile (minimum 0.05 mV); the scale shows those limits. Anatomy colors show annotated neuron groups.</p><h3>Virtual electrodes &amp; morphology</h3><p>Electrode placements use a declared mapping from the schematic fly body to brain-neuron groups. They do not model electric fields or tissue conduction. Branching views load source skeleton geometry when available; voltage remains one recorded state per neuron.</p><h3>Model boundaries</h3><ul><li>Point neurons with experimental graded and spiking dynamics; one female fruit-fly connectome.</li><li>Eye geometry and phototransduction include assumptions. The eye preview is an input visualization, not a camera reconstruction of fly vision.</li><li>Paired subtraction can reveal stimulus-dependent differences; it does not repair unstable dynamics or establish causation in an animal.</li><li>All clamp counts remain visible. Direction selectivity and other biological gates are not yet validated.</li></ul>`;
  if (run && summary) {
    const stats = summary.stats || {};
    content = `<div class="warning-box"><strong>Experimental recorded run.</strong> Numerical stability remains unresolved. Inspect the absolute baseline alongside the paired response.</div><table class="detail-table">${Object.entries(
      stats,
    )
      .map(
        ([key, value]) =>
          `<tr><td>${escapeHTML(key.replaceAll("_", " "))}</td><td>${escapeHTML(typeof value === "number" ? value.toLocaleString("en-US") : value)}</td></tr>`,
      )
      .join(
        "",
      )}</table><h3>Recorded stimulus</h3><table class="detail-table">${Object.entries(
      summary.stimulus || {},
    )
      .map(
        ([key, value]) =>
          `<tr><td>${escapeHTML(key.replaceAll("_", " "))}</td><td>${escapeHTML(typeof value === "object" ? JSON.stringify(value) : value)}</td></tr>`,
      )
      .join(
        "",
      )}</table><h3>Warnings &amp; assumptions</h3><ul>${(summary.warnings || []).map((warning) => `<li>${escapeHTML(typeof warning === "string" ? warning : JSON.stringify(warning))}</li>`).join("") || "<li>See the model assumptions and original validation report.</li>"}</ul><p><a href="/api/runs/${encodeURIComponent(summary.id)}/summary.json" target="_blank">Open recorded run metadata</a></p>`;
  }
  $("#dialog-content").innerHTML = content;
  $("#details-dialog").showModal();
}

function initializeDesktopAndNotes() {
  const host=document.createElement('aside');host.id='workspace-notes-rail';host.setAttribute('aria-label','Notes');document.body.append(host);document.body.classList.add('has-workspace-notes');
  workspaceNotes=initializeWorkspaceNotes({host,getContext:()=>({runId:state.summary?.id||null,modelId:state.metadata?.model_id||'flywire-783',modelHash:state.metadata?.model_hash||null,timeMs:state.time,status:$('.session-metrics')?.textContent||'Ready'}),
    onVisibilityChange:visible=>{document.body.classList.toggle('has-workspace-notes',visible);desktopWorkspace?.refresh();},
    onStatus:toast,onNavigate:async anchor=>{if(anchor.run_id&&anchor.run_id!==state.summary?.id)await loadRun(anchor.run_id);$('#simulation-tab').click();setPlaying(false);if(Number.isFinite(anchor.time_ms))setTime(anchor.time_ms);if(anchor.element_id==='editor-curve-analysis'||anchor.element_id?.startsWith('analysis-')||anchor.element_id?.startsWith('signal-chart-'))sequenceWorkspace.show('analysis');else if(anchor.element_id?.startsWith('seq-curve-'))sequenceWorkspace.show('sequence');},
    onSaveSession:async notes=>{
      const readSaved=key=>{try{return JSON.parse(localStorage.getItem(key)||'null');}catch{return null;}};
      const workspace={schema_version:1,run_id:state.summary?.id||null,model_id:state.metadata?.model_id,model_hash:state.metadata?.model_hash,time_ms:state.time,mode:state.mode,
        options:settings(),draft:experimentControls.draft(),layout:readSaved('cognesia.workspace.layout.v2'),display:readSaved('cognesia.workspace.preferences.v1'),
        charts:analysisWorkbench.exportState({includeSamples:false}),brain_camera:camera?{position:camera.position.toArray(),up:camera.up.toArray(),target:controls.target.toArray()}:null,section:{...sectionState},selected_neuron:state.selectedNeuron};
      const result=await requestJSON('/api/workspace-sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({notes,workspace})});
      if(window.__COGNESIA_DESKTOP__){const link=document.createElement('a');link.href=result.download_url;link.download=`${result.session_id}.cognesia-session.zip`;link.click();}
      return result;
    }});
  const buttons=[...document.querySelectorAll('.session-toolbar>button')],executionButtons=Object.fromEntries(['run','pause','resume','step','checkpoint','stop'].map((key,index)=>[key,buttons[index]]));
  const actions={'toggle-notes':()=>workspaceNotes.toggleVisible(),'new-note':()=>workspaceNotes.newNote(),'save-session':()=>workspaceNotes.saveSession(),simulate:()=>$('#simulation-tab').click(),parameters:()=>$('#parameters-tab').click(),layout:()=>layoutWorkbench.open(),settings:()=>workspaceSettings.open(),'stop-all':async()=>{const result=await stopAll();toast(result.active_jobs?'Stopping…':'Stopped. Recordings saved.');}};
  for(const[key,button]of Object.entries(executionButtons))actions[key]=()=>{$('#simulation-tab').click();button.click();};
  desktopWorkspace=initializeDesktopWorkspace({actions,executionButtons,isReady:()=>workspaceReadyForReload,getChecked:()=>({'toggle-notes':workspaceNotes.isVisible()}),onStatus:toast});
  const statusObserver=new MutationObserver(()=>workspaceNotes.refresh());statusObserver.observe($('.session-metrics'),{childList:true,subtree:true,characterData:true});
}

function createSequenceWorkspace() {
  const element=document.createElement('section');element.className='panel editor-sequence-panel';
  const tabs=document.createElement('div');tabs.className='editor-sequence-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Timeline workspace');
  const sequence=document.createElement('div');sequence.id='sequence-timeline';sequence.className='editor-sequence-content';
  const analysis=document.createElement('div');analysis.id='editor-curve-analysis';analysis.className='editor-sequence-content';analysis.append($("#analysis-workspace"));
  const views={sequence,analysis},buttons={};
  function show(key){for(const[id,view]of Object.entries(views)){view.hidden=id!==key;buttons[id].setAttribute('aria-selected',String(id===key));buttons[id].tabIndex=id===key?0:-1;}if(key==='analysis')analysisWorkbench?.setTime(state.time);}
  for(const[key,title]of [['sequence','Timeline'],['analysis','Curve analysis']]){
    const button=document.createElement('button');button.type='button';button.textContent=title;button.id=`editor-${key}-tab`;button.setAttribute('role','tab');button.setAttribute('aria-controls',views[key].id);button.addEventListener('click',()=>show(key));
    button.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=key==='sequence'?'analysis':'sequence';show(next);buttons[next].focus();}});
    views[key].setAttribute('role','tabpanel');views[key].setAttribute('aria-labelledby',button.id);buttons[key]=button;tabs.append(button);
  }
  element.append(tabs,sequence,analysis);
  $("#experiment-view").append(element);show('sequence');return{element,show};
}

function wireUI() {
  chemicalControls=initializeChemicalControls({host:$("#chemical-controls"),onEdited:markPreviewEdited});
  for(const option of $("#chemical-species").options){const key=option.value;option.value=key;option.textContent=speciesLabel(key);}
  try {flyBodyPanel=createFlyBodyPanel({THREE,OrbitControls,host:$("#whole-fly-host")});flyBodyPanel.ready.catch(error=>toast(`Fly surface: ${error.message}`));}
  catch(error){$("#whole-fly-host").textContent=`Fly surface unavailable: ${error.message}`;}
  const signalAdapter = createSignalAdapter({getState: signalState, requestJSON});
  analysisWorkbench = initializeAnalysis({
    ...signalAdapter,
    getTime: () => state.time,
    getCurrentRunId: () => state.summary?.id,
    onSeek: (time) => { setPlaying(false); setTime(time); },
    onStatus: toast,
  });
  experimentControls = initializeExperimentControls({host:$("#session-controls"),requestJSON,onStatus:toast,
    runDraft:runSimulation,getRunOptions:()=>settings(true),onRestoreOptions:restoreWorkspaceOptions,
    getSelectedNeuron:()=>state.selectedNeuron,getSelectedTarget:async modelId=>{
      if(state.selectedNeuron===null)throw Error('Select a neuron in the anatomy view first.');
      const displayed=state.metadata?.model_id||'flywire-783';
      if(displayed!==modelId)throw Error('The selected neuron belongs to a different model. Choose the draft model before picking a target.');
      const neuron=await selectedNeuronAnnotation(state.selectedNeuron);
      return {kind:'root_ids',root_ids:[neuron.root_id]};
    },getBaseOptions:()=>({duration_ms:Number($("#duration").value)}),
    onLiveFrame:applyLiveFrame,onModelChanged:async modelId=>{
      try {
        if(state.submitting||state.job){toast('Model choice saved for the next run.');return;}
        const custom=modelId!=="flywire-783";
        $("#chemical-plasticity").disabled=custom;
        if(custom){$("#chemical-plasticity").checked=false;toast("Regional chemistry; legacy learning unavailable.");}
        await switchModelAnatomy(modelId);
      }catch(error){toast(error.message);}
    }});
  workspaceOverview = initializeWorkspaceOverview({host:$("#experiment-view"),experimentControls,onSettings:()=>workspaceSettings?.open(),sensoryOptions:{
    requestJSON,getModelId:()=>state.metadata?.model_id||experimentControls.draft().model_id,
    getEyeModelId:()=>state.summary?.model_id||state.metadata?.model_id||experimentControls.draft().model_id,
    getEyeAudit:()=>state.summary?state.summary.metadata?.eye_audit:state.eyeMap?.model_id===state.metadata?.model_id?state.eyeMap?.audit:null,
    getEyeColumns:eyeColumns,getReceptors:eyeReceptors,getSelectedEyeColumn:()=>state.selectedEyeColumn,onSelectEyeColumn:selectEyeColumn}});
  sequenceWorkspace = createSequenceWorkspace();
  sequenceTimeline = initializeSequenceTimeline({host:$("#sequence-timeline"),experimentControls,...signalAdapter,
    getTime:()=>state.time,getCurrentRunId:()=>state.summary?.id,getState:()=>state,
    onSeek:time=>{setPlaying(false);setTime(time);},onPlay:playing=>{if(playing&&state.time>=duration())setTime(0);setPlaying(playing);},
    onAnalyzeSignal:pinSignal,onStatus:toast});
  layoutWorkbench = initializeLayoutWorkbench({host:$("#experiment-view"),toolbar:$(".top-right"),secondaryContent:workspaceOverview.secondary,
    panels:[{id:"inputs",title:"Experiment",element:workspaceOverview.panel},{id:"brain",title:"Brain",element:$(".brain-panel")},
      {id:"readouts",title:"Measurements",element:$(".readout-panel")},{id:"fly",title:"Fly body",element:$("#whole-fly-panel")},
      {id:"analysis",title:"Timeline & curves",element:sequenceWorkspace.element,controller:analysisWorkbench}],
    analysisOptions:{...signalAdapter,getTime:()=>state.time,getCurrentRunId:()=>state.summary?.id,onSeek:time=>{setPlaying(false);setTime(time);},onStatus:toast},
    getContext:()=>({modelId:state.metadata?.model_id||'flywire-783',modelHash:state.metadata?.model_hash,recordedNeuronIndex,recordedToAnatomy:state.recordedToAnatomy,recordingMetadata:state.recordingMetadata,runId:state.job?null:state.summary?.id,positions:state.positions,visibleIndices:state.visibleIndices,values:state.liveFrame?state.liveVoltage:currentValues()?.subarray(activityOffset(),activityOffset()+pointCount),
      timeMs:state.liveFrame?.model_time_ms??state.time,mode:state.liveFrame?"absolute":state.mode,summary:state.summary,chemistry:state.chemistry,
      selectedNeuron:state.selectedNeuron,liveFrame:state.liveFrame,session:state.job,metadata:state.metadata,fetchJSON:requestJSON}),onStatus:toast});
  workspaceSettings=initializeWorkspaceSettings({toolbar:$(".top-right"),onLayout:()=>layoutWorkbench.open(),onParameters:()=>$("#parameters-tab").click()});
  window.addEventListener('cognesia-anatomy-ready',()=>workspaceSettings.apply());
  flyBodyPanel?.ready.then(()=>workspaceSettings.apply()).catch(()=>{});
  $("#duration").addEventListener('change',()=>sequenceTimeline.refresh());
  initializeDesktopAndNotes();
  $("#open-comparison").addEventListener("click", () => {
    sequenceWorkspace.show('analysis');
    $("#simulation-tab").click();
    $("#analysis-workspace").scrollIntoView({block: "start"});
  });
  try { state.eyeOrientation = localStorage.getItem("cognesia-eye-orientation") === "facing" ? "facing" : "fly"; } catch {}
  $("#eye-orientation").value = state.eyeOrientation;
  $("#eye-orientation").addEventListener("change", () => {
    state.eyeOrientation = $("#eye-orientation").value;
    try { localStorage.setItem("cognesia-eye-orientation", state.eyeOrientation); } catch {}
    drawStimulus(performance.now());
  });
  $("#eyes-canvas").addEventListener("click", (event) => {
    const rect = event.currentTarget.getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top;
    const closest = state.eyeHitTargets.reduce((best, hit) => {
      const distance = Math.hypot(hit.x - x, hit.y - y);
      return !best || distance < best.distance ? {...hit, distance} : best;
    }, null);
    if (closest && closest.distance <= Math.max(8, closest.radius * 3)) selectEyeColumn(closest.index);
  });
  $("#pin-eye-column").addEventListener("click", () => {
    if (state.selectedEyeColumn !== null) pinSignal(`eye:column:${state.selectedEyeColumn}`);
  });
  $("#pin-eye-receptor").addEventListener("click", () => {
    if ($("#eye-receptor").value) {
      const index=Number($("#eye-receptor").value);
      if(index>=0)pinSignal(`neuron:${index}:raw`);else toast('This receptor was not recorded in the loaded experiment.');
    }
  });
  $("#traces-container").addEventListener("click", (event) => {
    const button = event.target.closest("[data-pin-trace]");
    if (button) pinTrace(Number(button.dataset.pinTrace));
  });
  initializeLab({
    requestJSON,
    onActiveJob: async (job) => {
      if (
        !state.positions || !job?.id ||
        !["queued", "running", "paused", "pause_requested", "preparing", "checkpointing"].includes(job.status) ||
        state.job ||
        state.submitting
      )
        return;
      state.submitting=true;
      try{await switchModelAnatomy(job.model_id||'flywire-783');}catch(error){state.submitting=false;toast(error.message);return;}
      state.submitting=false;state.job = job.id;
      experimentControls?.updateJob(job);
      experimentControls?.stream(job.id);
      $("#run-button").disabled = true;
      setLabRunning(true);
      $("#run-button-text").textContent = "Running experiment";
      $("#job-progress").hidden = false;
      $("#cancel-job").hidden = false;
      $("#cancel-job").disabled = Boolean(job.cancel_requested);
      $("#cancel-job").textContent = job.cancel_requested
        ? "Stopping…"
        : "Stop experiment";
      pollJob(job.id).catch((error) => {
        finishJob();
        toast(`Simulation stopped: ${error.message}`);
      });
    },
    onEdited: () => {
      markPreviewEdited();
      updateControls();
    },
  });
  $("#anchor-view-button").addEventListener("click", () =>
    setMorphologyMode("anchors"),
  );
  $("#morphology-view-button").addEventListener("click", () =>
    setMorphologyMode("overview"),
  );
  $("#arbor-view-button").addEventListener("click", () =>
    setMorphologyMode("arbor"),
  );
  $("#load-morphology").addEventListener("click", loadMorphologyOverview);
  $("#brain-inspector").addEventListener("click", (event) => {
    if (event.target.closest("#neuron-chart-button") && state.selectedNeuron !== null) {
      const index=recordedNeuronIndex(state.selectedNeuron);
      if(index>=0)pinSignal(`neuron:${index}:raw`);else toast('This neuron was not recorded in the loaded experiment.');
    }
    if (
      event.target.closest("#neuron-electrode-button") &&
      state.selectedNeuron !== null
    )
      addNeuronElectrode(state.selectedNeuron);
  });
  for (const id of [
    "stimulus-type",
    "grating-waveform",
    "mean-luminance",
    "spatial-period",
    "direction",
    "speed",
    "contrast",
    "duration",
    "apparent-interval",
    "apparent-separation",
  ])
    $(`#${id}`).addEventListener("input", () => {
      markPreviewEdited();
      updateControls();
    });
  $$("[data-direction]").forEach((button) =>
    button.addEventListener("click", () => {
      $("#direction").value = button.dataset.direction;
      markPreviewEdited();
      updateControls();
    }),
  );
  $$("[data-view]").forEach((button) =>
    button.addEventListener("click", () => setCameraView(button.dataset.view)),
  );
  $("#reset-view").addEventListener("click", () => setCameraView("overview"));
  $("#rotate-button").addEventListener("click", () => {
    state.cameraView = "custom";
    controls.autoRotate = !controls.autoRotate;
    $("#rotate-button").classList.toggle("active", controls.autoRotate);
  });
  $("#fullscreen-button").addEventListener("click", async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await $(".brain-panel").requestFullscreen();
    } catch {
      toast("Full-screen viewing is not available in this browser.");
    }
  });
  $$("[data-mode]").forEach((button) =>
    button.addEventListener("click", () => setMode(button.dataset.mode)),
  );
  $("#trace-family").addEventListener("change", buildTraces);
  $("#trace-search").addEventListener("input", buildTraces);
  $$("[data-readout]").forEach((button) =>
    button.addEventListener("click", () => {
      state.readout = button.dataset.readout;
      $("#trace-family").hidden = state.readout !== "types";
      $("#trace-search").hidden = state.readout === "types";
      $("#trace-search").value = "";
      $("#trace-search").placeholder =
        state.readout === "regions"
          ? "Find regions by their full names"
          : "Filter neuron classes";
      $$("[data-readout]").forEach((item) =>
        item.classList.toggle("active", item === button),
      );
      buildTraces();
    }),
  );
  $("#play-button").addEventListener("click", () => {
    if (state.time >= duration()) setTime(0);
    setPlaying(!state.playing);
  });
  $("#fly-play-button").addEventListener("click",()=>{if(state.time>=duration())setTime(0);setPlaying(!state.playing);});
  $("#fly-timeline").addEventListener("input",()=>{setPlaying(false);setTime(Number($("#fly-timeline").value));});
  $("#fly-color-mode").addEventListener("change",()=>setMode($("#fly-color-mode").value));
  $("#timeline").addEventListener("input", () => {
    setPlaying(false);
    setTime(Number($("#timeline").value));
  });
  $("#playback-speed").addEventListener(
    "change",
    () => (state.playbackSpeed = Number($("#playback-speed").value)),
  );
  $("#run-button").addEventListener("click", runSimulation);
  $("#stop-all").addEventListener("click",()=>stopAll().catch(error=>toast(error.message)));
  $("#clear-cache").addEventListener("click",clearDisplayCache);
  for(const id of ["chemical-species","chemical-condition","chemical-compartment","state-trace-variable"])$("#"+id).addEventListener("change",()=>{state.chemicalCache=null;updateActivity();drawChemicalReadout();});
  $("#pin-chemical").addEventListener("click",()=>{if(state.chemistry)pinSignal(`chemical:${state.chemistry.species.indexOf($("#chemical-species").value)}:${$("#chemical-compartment").value}:${$("#chemical-condition").value}`);});
  $("#pin-state").addEventListener("click",()=>{if(state.chemistry)pinSignal(`state:${$("#state-trace-variable").value}:${$("#chemical-condition").value}`);});
  $("#cancel-job").addEventListener("click", async () => {
    if (!state.job) return;
    $("#cancel-job").disabled = true;
    $("#cancel-job").textContent = "Stopping…";
    try {
      await requestJSON(`/api/jobs/${encodeURIComponent(state.job)}/cancel`, {
        method: "POST",
      });
    } catch (error) {
      toast(error.message);
      $("#cancel-job").disabled = false;
    }
  });
  $("#saved-runs").addEventListener("change", () =>
    loadRun($("#saved-runs").value).catch(() => {}),
  );
  $("#refresh-runs").addEventListener("click", () =>
    refreshRuns().catch((error) => toast(error.message)),
  );
  for (const id of ["about-button", "assumptions-button"])
    $(`#${id}`).addEventListener("click", () => showDetails());
  $("#details-button").addEventListener("click", () => showDetails(true));
  for (const id of ["close-dialog", "done-dialog"])
    $(`#${id}`).addEventListener("click", () => $("#details-dialog").close());
  $("#details-dialog").addEventListener("click", (event) => {
    if (event.target === $("#details-dialog")) {
      const rect = $("#details-dialog").getBoundingClientRect();
      if (
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom
      )
        $("#details-dialog").close();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (
      event.code === "Space" &&
      !["INPUT", "SELECT", "BUTTON", "TEXTAREA"].includes(
        document.activeElement.tagName,
      ) &&
      !$("#details-dialog").open
    ) {
      event.preventDefault();
      if (state.time >= duration()) setTime(0);
      setPlaying(!state.playing);
    }
  });
  window.addEventListener("resize", () => {
    drawTraces();
    drawChemicalReadout();
    drawStimulus(performance.now());
  });
  updateControls();
}
function drawBrainScene(now=performance.now()) {
  if(!renderer||!scene||!camera||$("#experiment-view").hidden)return false;
  const box=renderer.domElement.getBoundingClientRect();
  if(!box.width||!box.height||renderer.getContext().isContextLost())return false;
  updateOrientation();regionAtlas?.render();renderer.render(scene,camera);state.sceneDirty=false;
  renderer.domElement.dataset.renderState='drawn';renderer.domElement.dataset.lastDrawMs=String(Math.round(now));renderingHealth.draws++;renderingHealth.lastDrawMs=now;
  return true;
}
function animate(now) {
  renderingHealth.rafCalls++;renderingHealth.lastRafMs=now;
  requestAnimationFrame(animate);
  const elapsed = Math.min(now - lastRender, 80);
  lastRender = now;
  if (state.playing && state.summary) {
    const next = state.time + elapsed * state.playbackSpeed;
    if (next >= duration()) {
      setTime(duration());
      setPlaying(false);
    } else setTime(next);
  }
  const recordedInput = state.summary && !state.previewEdited;
  const inputDt =
    state.summary?.eyes?.dt_ms ||
    state.summary?.stimulus_frames?.dt_ms ||
    1000 / 240;
  const inputFrame = Math.floor(state.time / inputDt + 1e-9);
  if (
    recordedInput ? inputFrame !== state.lastInputFrame : state.previewDirty || (!state.previewStopped && now - lastPreview > 40)
  ) {
    drawStimulus(state.previewStopped ? state.previewStart : now);
    lastPreview = now;state.previewDirty=false;
    state.lastInputFrame = recordedInput ? inputFrame : -1;
  }
  if (controls) controls.update();
  if(state.sceneDirty||state.playing||controls?.autoRotate)drawBrainScene(now);
}
async function initialize() {
  wireUI();
  let reloadSnapshot = null;
  try {
    const saved=JSON.parse(sessionStorage.getItem(LIVE_RELOAD_SNAPSHOT)||'null');
    if(saved?.version===1 && saved.options)reloadSnapshot=saved;
  } catch {}
  try {
    setupScene();
    requestAnimationFrame(animate);
    const bootstrap = await requestJSON("/api/bootstrap");
    state.bootstrap = bootstrap;
    configureLab(bootstrap);
    workspaceOverview?.refresh();
    $("#neuron-count").textContent = formatNumber(
      bootstrap.neuron_count || 138639,
    );
    const anatomy = bootstrap.anatomy || {};
    const [positions, groups, metadata, visibleIndices] = await Promise.all([
      requestArray(anatomy.positions_url || "/api/anatomy/positions.bin"),
      requestArray(anatomy.groups_url || "/api/anatomy/groups.bin", Uint8Array),
      requestJSON(anatomy.metadata_url || "/api/anatomy/metadata.json"),
      anatomy.visible_indices_url
        ? requestArray(anatomy.visible_indices_url, Uint32Array)
        : null,
    ]);
    state.positions = positions;
    state.groups = groups;
    state.metadata = metadata;
    state.visibleIndices = visibleIndices;
    state.anatomyUrl = anatomy.metadata_url || "/api/anatomy/metadata.json";
    makePointCloud();
    $("#connection-state").textContent = "Engine connected · ready";
    $("#eye-note").textContent =
      "Column geometry appears when a recorded experiment loads.";
    await refreshRuns();
    await experimentControls.ready;
    if (reloadSnapshot?.runId) await loadRun(reloadSnapshot.runId);
    else {
      const custom=experimentControls.draft().model_id!=='flywire-783';
      $('#chemical-plasticity').disabled=custom;
      if(custom)$('#chemical-plasticity').checked=false;
      await switchModelAnatomy(experimentControls.draft().model_id);
      setMode('anatomy');
      $("#run-title").textContent = "Ready";
      if(!state.eyeMap)await refreshEyeMap();
    }
    try {
      const morphologyStatus = await requestJSON("/api/morphology/status");
      if (morphologyStatus.status === "ready") setMorphologyMode("overview");
    } catch {}
    if(reloadSnapshot) {
      restoreWorkspaceOptions(reloadSnapshot.options);
      if(reloadSnapshot.mode)setMode(reloadSnapshot.mode);
      if(Number.isFinite(reloadSnapshot.timeMs))setTime(reloadSnapshot.timeMs);
      sessionStorage.removeItem(LIVE_RELOAD_SNAPSHOT);
    }
  } catch (error) {
    console.error(error);
    $("#connection-state").textContent = "Connection needs attention";
    if (!points) {
      $("#stage-loading").innerHTML =
        `<strong>Could not load the brain</strong><span>${escapeHTML(error.message)}</span><span>Start the local Flybrain server and reload this page.</span>`;
    }
    toast(error.message);
  } finally {
    workspaceReadyForReload = true;
    desktopWorkspace?.refresh();
  }
}
window.cognesia = {
  get state() {
    return {
      neuronCount: pointCount,
      recordedCount: state.recordedToAnatomy?.length||0,
      anatomyModelHash: state.metadata?.model_hash,
      visibleCount: state.visibleIndices?.length || pointCount,
      runId: state.summary?.id,
      frame: state.frame,
      timeMs: state.time,
      playing: state.playing,
      mode: state.mode,
      chemicalSpecies: $("#chemical-species")?.value,
      chemistryAvailable: !!state.chemistry,
      chemistryError: state.chemistryError,
      job: state.job,
      webgl: !!renderer,
      activityCount: state.activity.delta?.length,
      summary: state.summary,
    };
  },
  setTime,
  setMode,
  loadRun,
};
initialize();
