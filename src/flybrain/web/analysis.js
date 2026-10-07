import { analyzeSignal, describeFourierFit, selectSignalInterval, serverFourierResult, MAX_SIGNAL_SAMPLES } from "./signals.js";
let nextWorkbenchId = 1;

const MAX_CARDS = 6;
const MAX_OVERLAYS = 4;
const RESULT_LIMIT = 250;
const COLORS = ["#72b9ff", "#efa979", "#69cfa8", "#c3a1ec"];
const MODES = { time: "Time curve", spectrum: "Fourier spectrum", reconstruction: "Fourier reconstruction" };
const shortNumber = (value) => {
  if (!Number.isFinite(value)) return "—";
  if (value === 0) return "0";
  const absolute = Math.abs(value);
  return absolute >= 1e5 || absolute < 0.001 ? value.toExponential(2) : Number(value.toPrecision(4)).toString();
};
const make = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const csvCell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
const nearestIndex = (values, x) => {
  let lo = 0, hi = values.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (values[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 && Math.abs(values[lo - 1] - x) < Math.abs(values[lo] - x) ? lo - 1 : lo;
};

/** Pin compact, immutable signal snapshots; refresh never changes existing cards. */
export function initializeAnalysis({ listSignals, resolveSignal, getTime, getCurrentRunId, onSeek, onStatus, host = document.getElementById("analysis-workspace"), autoDefaults = true }) {
  const workbenchId = nextWorkbenchId++;
  let disposed = false, worker = null, requestId = 0;
  const workerRequests = new Map();
  try {
    worker = new Worker(new URL("./signal-worker.js", import.meta.url), { type: "module" });
    worker.onmessage = ({ data }) => { const request = workerRequests.get(data.id); if (!request) return; workerRequests.delete(data.id); data.error ? request.reject(new Error(data.error)) : request.resolve(data); };
    worker.onerror = () => { for (const request of workerRequests.values()) request.reject(new Error("Signal analysis worker stopped. Reload to retry.")); workerRequests.clear(); };
  } catch {}
  if (!host) throw new Error("Analysis workspace is missing.");
  host.classList.add("analysis-workspace");
  host.innerHTML = `
    <div class="analysis-heading"><div><h2>Signal comparison</h2><p>Compare recorded inputs and neural responses across experiments.</p></div><span class="analysis-card-count">0 / 6 charts</span></div>
    <details class="analysis-picker-disclosure" open><summary>Add signal</summary><div class="analysis-picker">
      <label class="analysis-search">Find signal<input type="search" placeholder="Name, neuron ID, or column…" aria-label="Find recorded signal" /></label>
      <label>Source<select class="analysis-group" aria-label="Signal source group"><option value="">All sources</option></select></label>
      <label>Side<select class="analysis-side" aria-label="Signal side"><option value="">All sides</option><option value="left">Left</option><option value="right">Right</option><option value="both">Both</option><option value="unknown">Unknown</option></select></label>
      <label class="analysis-signal-field">Recorded signal<select class="analysis-signals" aria-label="Recorded signal" disabled><option>No recording loaded</option></select><span class="analysis-match-count"></span></label>
      <label>Destination<select class="analysis-destination" aria-label="Chart destination"><option value="new">New chart</option></select></label>
      <button class="analysis-add" disabled>Add chart</button>
    </div></details>
    <p class="analysis-status" role="status" aria-live="polite">Load a recording to explore its signals.</p>
    <div class="analysis-cards"></div>
    <div class="analysis-empty"><strong>No signals pinned</strong><span>Open a saved experiment or run a simulation, then choose a signal above. Charts retain their recorded data when you switch experiments.</span></div>
    <p class="analysis-footer">Each chart is a saved signal snapshot. Drag its lower-right corner to resize; use Move left and Move right to arrange charts. Time cursors follow the active recording only.</p>`;
  const query = (selector) => host.querySelector(selector);
  const search = query("input[type=search]");
  const group = query(".analysis-group");
  const side = query(".analysis-side");
  const select = query(".analysis-signals");
  const destination = query(".analysis-destination");
  const addButton = query(".analysis-add");
  const status = query(".analysis-status");
  const grid = query(".analysis-cards");
  const pickerDisclosure = query(".analysis-picker-disclosure");
  let catalog = [];
  const cards = [];
  let nextCardId = 1;
  let pendingCount = 0;
  let catalogLoading = false;
  let refreshVersion = 0;
  let defaultsAdded = false;
  let cursorMs = Number(getTime?.() ?? 0);
  let redrawFrame = null;
  let catalogRunId = null;
  let compactMode = null;

  function syncCompactMode() {
    const compact = !!host.closest(".dock-primary-grid");
    if (compact === compactMode) return;
    compactMode = compact;
    pickerDisclosure.open = !compact;
    for (const card of cards) {
      card.element.querySelector(".analysis-card-tools").open = !compact;
      card.element.querySelector(".analysis-fit-result").open = !compact;
    }
  }

  const report = (message, error = false) => {
    status.textContent = message;
    status.classList.toggle("analysis-error", error);
    if (error) onStatus?.(message);
  };
  const currentRun = () => getCurrentRunId?.() ?? catalogRunId;
  const isCurrent = (signal) => signal.runId != null && signal.runId === currentRun();
  const scheduleDraw = () => {
    if (disposed || redrawFrame !== null) return;
    syncCompactMode();
    redrawFrame = requestAnimationFrame(() => {
      redrawFrame = null;
      for (const card of cards) draw(card);
    });
  };
  const resizeObserver = typeof ResizeObserver !== "undefined" ? new ResizeObserver(scheduleDraw) : null;

  function updatePicker() {
    const selectedId = select.value;
    const term = search.value.trim().toLowerCase();
    let matches = 0;
    const visible = [];
    for (const entry of catalog) {
      if (group.value && entry.group !== group.value) continue;
      if (side.value && (entry.side || "unknown") !== side.value) continue;
      if (term && !entry.searchText.includes(term)) continue;
      matches++;
      if (visible.length < RESULT_LIMIT) visible.push(entry);
    }
    select.replaceChildren();
    for (const entry of visible) {
      const option = new Option(entry.label, entry.id);
      option.title = `${entry.label} · ${entry.unit} · ${entry.side || "unknown"}`;
      select.add(option);
    }
    if (visible.some((entry) => entry.id === selectedId)) select.value = selectedId;
    if (!visible.length) select.add(new Option(catalog.length ? "No matching signals" : "No recording loaded", ""));
    select.disabled = !visible.length;
    query(".analysis-match-count").textContent = matches > RESULT_LIMIT
      ? `${matches.toLocaleString()} matches · showing first ${RESULT_LIMIT}; narrow the search`
      : `${matches.toLocaleString()} signal${matches === 1 ? "" : "s"}`;
    updateAddButton();
  }

  function updateAddButton() {
    const overlay = destination.value !== "new";
    addButton.textContent = pendingCount ? "Loading…" : overlay ? "Overlay signal" : "Add chart";
    addButton.disabled = catalogLoading || pendingCount > 0 || select.disabled || (!overlay && cards.length >= MAX_CARDS);
  }

  function updateCards() {
    host.classList.toggle("analysis-has-cards", cards.length > 0);
    const selected = destination.value;
    destination.replaceChildren(new Option("New chart", "new"));
    for (const [index, card] of cards.entries()) {
      destination.add(new Option(`${index + 1}. ${card.signals[0].label}`, card.id));
      card.left.disabled = index === 0;
      card.right.disabled = index === cards.length - 1;
      card.element.setAttribute("aria-label", `Chart ${index + 1}: ${card.signals.map((s) => s.label).join(", ")}`);
      grid.append(card.element);
    }
    if (selected === "new" || cards.some((card) => card.id === selected)) destination.value = selected;
    query(".analysis-card-count").textContent = `${cards.length} / ${MAX_CARDS} charts`;
    query(".analysis-empty").hidden = cards.length > 0;
    updateAddButton();
    scheduleDraw();
  }

  function snapshot(source) {
    if (!source || !source.timeMs || !source.values) throw new Error("This signal has no recorded samples.");
    const timeMs = Float64Array.from(source.timeMs);
    const values = Float64Array.from(source.values);
    if (timeMs.length !== values.length || !timeMs.length) throw new Error("The signal's sample times and values do not match.");
    for (let i = 0; i < values.length; i++) {
      if (!Number.isFinite(values[i]) || !Number.isFinite(timeMs[i])) throw new Error("This signal contains non-finite samples and cannot be charted.");
      if (i && timeMs[i] <= timeMs[i - 1]) throw new Error("Signal sample times must increase.");
    }
    return {
      id: String(source.id), label: String(source.label || source.id),
      unit: String(source.unit || "a.u."), runId: source.runId ?? null,
      description: String(source.description || ""), side: source.side || "unknown",
      timeMs, values, analyses: new Map(), reconstructions: new Map(),
    };
  }

  async function addSignal(id, targetId = "new") {
    if (!id) return false;
    if (targetId === "new" && cards.length >= MAX_CARDS) {
      report("Six charts are open. Remove one or overlay a signal on an existing chart.", true);
      return false;
    }
    pendingCount++;
    updateAddButton();
    report("Loading recorded signal…");
    try {
      const signal = snapshot(await resolveSignal(id));
      const target = cards.find((card) => card.id === targetId);
      if (targetId !== "new" && !target) throw new Error("The destination chart was removed. Add this signal to a new chart.");
      if (target) {
        if (target.signals.length >= MAX_OVERLAYS) throw new Error("A chart can hold four signals. Add another chart to compare more.");
        if (target.signals[0].unit !== signal.unit) throw new Error(`This chart uses ${target.signals[0].unit}. Add a new chart for ${signal.unit} signals.`);
        if (target.signals.some((s) => s.id === signal.id && s.runId === signal.runId)) throw new Error("This recorded signal is already on that chart.");
        target.signals.push(signal);
        refreshCard(target);
      } else {
        if (cards.length >= MAX_CARDS) throw new Error("Six charts are already open. Remove one before adding another.");
        const card = createCard(signal);
        cards.push(card);
        resizeObserver?.observe(card.plot);
      }
      updateCards();
      report(`Pinned ${signal.label}. Charts retain their data when experiments change.`);
      return true;
    } catch (error) {
      report(error?.message || "The recorded signal could not be loaded.", true);
      return false;
    } finally {
      pendingCount--;
      updateAddButton();
    }
  }

  async function computeAnalysis(signal, card, selected) {
    const options = { demean: card.demean, window: card.hann ? "hann" : "none" };
    const harmonics = card.mode === "reconstruction" ? Math.min(card.harmonics, Math.floor(selected.values.length / 2)) : null;
    if (selected.values.length > MAX_SIGNAL_SAMPLES) {
      const response = await fetch("/api/analysis/interval", {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({
        time_ms: Array.from(selected.timeMs), values: Array.from(selected.values), start_ms: selected.startMs, end_ms: selected.endMs,
        harmonics: harmonics ?? 8, unit: signal.unit, source: {run_id:signal.runId,signal_id:signal.id}, ...options})});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The selected interval could not be analyzed.");
      const result=serverFourierResult(data,signal.unit);
      return {...result,fit:harmonics==null?null:result.fit};
    }
    if (worker) return new Promise((resolve,reject) => { const id = ++requestId; workerRequests.set(id,{resolve,reject}); worker.postMessage({id,timeMs:selected.timeMs,values:selected.values,options,harmonics,unit:signal.unit}); });
    await new Promise(resolve => setTimeout(resolve,0));
    const analysis = analyzeSignal(selected.timeMs, selected.values, options);
    return {analysis,fit:harmonics == null ? null : describeFourierFit(analysis,selected.values,harmonics,signal.unit)};
  }

  function analysisFor(signal, card, selected) {
    const key = `${selected.startIndex}:${selected.endIndex}:${card.demean}:${card.hann}:${card.mode === "reconstruction" ? card.harmonics : "spectrum"}`;
    if (!signal.analyses.has(key)) {
      const entry = {pending:true};
      signal.analyses.set(key,entry);
      // A bounded cache prevents retaining every range visited while dragging.
      if (signal.analyses.size > 12) signal.analyses.delete(signal.analyses.keys().next().value);
      computeAnalysis(signal, {...card}, selected).then(result => {entry.result=result;entry.pending=false;scheduleDraw();}, error => {entry.error=error;entry.pending=false;scheduleDraw();});
    }
    const entry = signal.analyses.get(key);
    if (entry.error) throw entry.error;
    if (entry.pending) throw new Error("Computing selected-interval Fourier analysis…");
    return entry.result;
  }

  function plottedSignals(card) {
    return card.signals.map((signal, index) => {
      let x = signal.timeMs, y = signal.values, analysis = null, fit = null, selected = null;
      if (card.mode !== "time") {
        if(card.drag?.moved)throw new Error("Release the interval boundary to update its Fourier fit.");
        selected = selectSignalInterval(signal.timeMs, signal.values, card.interval);
        ({analysis, fit} = analysisFor(signal, card, selected));
        if (card.mode === "spectrum") { x = analysis.frequenciesHz; y = analysis.amplitudes; }
        else { x = selected.timeMs; y = fit.fitted; }
      }
      return {signal,x,y,analysis,fit,selected,color:COLORS[index]};
    });
  }

  function setInterval(card, interval) {
    card.interval = interval ? [...interval].sort((a,b)=>a-b) : null;
    card.pendingEndpoint = null;
    const bounds = card.interval || [Math.min(...card.signals.map(s=>s.timeMs[0])),Math.max(...card.signals.map(s=>s.timeMs.at(-1)))];
    card.element.querySelector(".analysis-range-start").value = bounds[0];
    card.element.querySelector(".analysis-range-end").value = bounds[1];
    refreshCard(card);
  }

  function createCard(signal) {
    const card = { id: `signal-chart-${workbenchId}-${nextCardId++}`, signals: [signal], mode: "time", harmonics: 8, demean: false, hann: false, hoverX: null, plotBounds: null, interval:null, selectionMode:"inspect", pendingEndpoint:null };
    const element = make("article", "analysis-card");
    element.tabIndex = -1;
    element.id = card.id;
    element.innerHTML = `
      <div class="analysis-card-heading"><h3></h3><div class="analysis-card-actions"><button class="analysis-move-left" title="Move chart left" aria-label="Move chart left">Move left</button><button class="analysis-move-right" title="Move chart right" aria-label="Move chart right">Move right</button><button class="analysis-close" title="Remove chart" aria-label="Remove chart">×</button></div></div>
      <div class="analysis-legend"></div>
      <details class="analysis-card-tools" open><summary>Tools <span class="analysis-tool-state">Time curve</span></summary><div class="analysis-chart-controls">
        <label>View<select class="analysis-mode"><option value="time">Time curve</option><option value="spectrum">Fourier spectrum</option><option value="reconstruction">Fourier reconstruction</option></select></label>
        <label class="analysis-harmonics" hidden>Harmonics<input type="number" min="0" max="64" step="1" value="8" /></label>
        <button class="analysis-all-harmonics" hidden>All</button>
        <label class="analysis-spectrum-option" hidden><input class="analysis-demean" type="checkbox" />Remove mean</label>
        <label class="analysis-spectrum-option" hidden><input class="analysis-hann" type="checkbox" />Hann window</label>
        <button class="analysis-export" title="Export the samples shown in this chart">Export CSV</button>
      </div>
      <div class="analysis-range-controls"><label>Pointer<select class="analysis-pointer-mode"><option value="inspect">Inspect / seek</option><option value="select">Select interval</option></select></label><label>Start (ms)<input class="analysis-range-start" type="number" step="any"></label><label>End (ms)<input class="analysis-range-end" type="number" step="any"></label><button class="analysis-range-reset">Full recording</button><button class="analysis-fit-button">Fit interval</button></div>
      <div class="analysis-method-note"></div></details>
      <div class="analysis-plot"><canvas role="img"></canvas><div class="analysis-plot-error" hidden></div></div>
      <details class="analysis-fit-result" open hidden><summary>Formula &amp; residual</summary><div class="analysis-fit-summary"></div><pre class="analysis-equation"></pre><div class="analysis-fit-actions"><button class="analysis-copy-equation">Copy equation</button><button class="analysis-fit-export">Export fit JSON</button></div><canvas class="analysis-residual" aria-label="Original minus fitted signal"></canvas><small>Residual: original − fit. t is in seconds. This is a periodic approximation on the selected interval.</small></details>
      <div class="analysis-inspection" aria-live="off">Point to the chart to inspect values.</div>`;
    Object.assign(card, { element, plot: element.querySelector(".analysis-plot"), canvas: element.querySelector("canvas"), left: element.querySelector(".analysis-move-left"), right: element.querySelector(".analysis-move-right") });
    for (const disclosure of element.querySelectorAll("details")) {
      disclosure.open = !host.closest(".dock-primary-grid");
      disclosure.addEventListener("toggle", scheduleDraw);
    }
    const move = (step) => {
      const from = cards.indexOf(card), to = from + step;
      if (to < 0 || to >= cards.length) return;
      cards.splice(from, 1); cards.splice(to, 0, card); updateCards();
      (step < 0 ? card.left : card.right).focus();
    };
    card.left.addEventListener("click", () => move(-1));
    card.right.addEventListener("click", () => move(1));
    element.querySelector(".analysis-close").addEventListener("click", () => {
      resizeObserver?.unobserve(card.plot);
      cards.splice(cards.indexOf(card), 1); element.remove(); updateCards();
      report("Chart removed.");
    });
    element.querySelector(".analysis-mode").addEventListener("change", (event) => { card.mode = event.target.value; card.hoverX = null; refreshCard(card); });
    const harmonics = element.querySelector(".analysis-harmonics input");
    harmonics.addEventListener("change", () => {
      card.harmonics = Math.max(0, Math.min(Number(harmonics.max), Math.round(Number(harmonics.value) || 0)));
      harmonics.value = card.harmonics; scheduleDraw();
    });
    element.querySelector(".analysis-all-harmonics").addEventListener("click", () => {
      card.harmonics = Number(harmonics.max);
      harmonics.value = card.harmonics;
      scheduleDraw();
    });
    element.querySelector(".analysis-demean").addEventListener("change", (event) => { card.demean = event.target.checked; scheduleDraw(); });
    element.querySelector(".analysis-hann").addEventListener("change", (event) => { card.hann = event.target.checked; scheduleDraw(); });
    element.querySelector(".analysis-export").addEventListener("click", () => exportCard(card));
    element.querySelector(".analysis-pointer-mode").addEventListener("change", event => {card.selectionMode=event.target.value;card.pendingEndpoint=null;scheduleDraw();});
    for (const selector of [".analysis-range-start",".analysis-range-end"]) element.querySelector(selector).addEventListener("change",()=>{
      const a=Number(element.querySelector(".analysis-range-start").value),b=Number(element.querySelector(".analysis-range-end").value);
      if(Number.isFinite(a)&&Number.isFinite(b))setInterval(card,[a,b]);
    });
    element.querySelector(".analysis-range-reset").addEventListener("click",()=>setInterval(card,null));
    element.querySelector(".analysis-fit-button").addEventListener("click",()=>{const a=Number(element.querySelector(".analysis-range-start").value),b=Number(element.querySelector(".analysis-range-end").value);if(Number.isFinite(a)&&Number.isFinite(b))setInterval(card,[a,b]);card.mode="reconstruction";element.querySelector(".analysis-mode").value=card.mode;element.querySelector(".analysis-fit-result").open=true;if(compactMode)element.querySelector(".analysis-card-tools").open=false;refreshCard(card);});
    element.querySelector(".analysis-copy-equation").addEventListener("click",async()=>{
      try {const traces=plottedSignals(card);await navigator.clipboard.writeText(traces.map(t=>`${t.signal.label}: ${t.fit.equation} [${t.signal.unit}]; t in seconds; ${t.fit.startMs}–${t.fit.endMs} ms`).join("\n"));report("Copied the fitted equation.");}catch(error){report(error.message,true);}
    });
    element.querySelector(".analysis-fit-export").addEventListener("click",()=>{
      try {download(`cognesia-${card.id}-fit.json`,"application/json",JSON.stringify(plottedSignals(card).map(t=>({...t.fit,fitted:Array.from(t.fit.fitted),residual:Array.from(t.fit.residual),timeMs:Array.from(t.x),source:{runId:t.signal.runId,signalId:t.signal.id,label:t.signal.label},requestedIntervalMs:card.interval})),null,2));}catch(error){report(error.message,true);}
    });
    const pointerTime=event=>{const b=card.plotBounds,r=card.canvas.getBoundingClientRect();return b?b.xMin+Math.max(0,Math.min(1,(event.clientX-r.left-b.left)/(b.right-b.left)))*(b.xMax-b.xMin):null;};
    card.canvas.addEventListener("pointerdown",event=>{
      if(card.selectionMode!=="select"||card.mode==="spectrum"||event.button!==0||!card.plotBounds)return;
      event.preventDefault();const time=pointerTime(event),b=card.plotBounds,r=card.canvas.getBoundingClientRect(),x=event.clientX-r.left;
      const handle=card.interval?.findIndex(t=>Math.abs(b.left+(t-b.xMin)/(b.xMax-b.xMin)*(b.right-b.left)-x)<9)??-1;
      card.drag={id:event.pointerId,x:event.clientX,time,handle,original:card.interval?[...card.interval]:null,moved:false};card.canvas.setPointerCapture(event.pointerId);
    });
    card.canvas.addEventListener("pointerup",event=>{
      const drag=card.drag;if(!drag||drag.id!==event.pointerId)return;card.drag=null;
      try{card.canvas.releasePointerCapture(event.pointerId);}catch{}
      if(drag.moved){setInterval(card,card.interval);return;}
      const time=pointerTime(event);
      if(card.pendingEndpoint==null){card.pendingEndpoint=time;report("Start selected. Click the end, or drag to select an interval.");scheduleDraw();}
      else {setInterval(card,[card.pendingEndpoint,time]);report("Interval selected. Fit interval shows its equation and residual.");}
    });
    card.canvas.addEventListener("pointercancel",()=>{if(card.drag){card.interval=card.drag.original;card.drag=null;scheduleDraw();}});
    card.canvas.addEventListener("pointermove", (event) => {
      if(card.drag&&card.drag.id===event.pointerId){const d=card.drag;d.moved ||= Math.abs(event.clientX-d.x)>4;if(d.moved){const time=pointerTime(event);card.interval=d.handle>=0?[...d.original]:[d.time,time];if(d.handle>=0)card.interval[d.handle]=time;scheduleDraw();}return;}
      const bounds = card.plotBounds;
      if (!bounds) return;
      const rect = card.canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      card.hoverX = x >= bounds.left && x <= bounds.right ? bounds.xMin + (x - bounds.left) / (bounds.right - bounds.left) * (bounds.xMax - bounds.xMin) : null;
      scheduleDraw();
    });
    card.canvas.addEventListener("pointerleave", () => { card.hoverX = null; scheduleDraw(); });
    card.canvas.addEventListener("click", () => {
      if (card.selectionMode === "inspect" && card.mode !== "spectrum" && card.hoverX != null && card.signals.some(isCurrent)) onSeek?.(card.hoverX);
    });
    setInterval(card,null);
    return card;
  }

  function refreshCard(card) {
    card.element.querySelector("h3").textContent = card.signals.length === 1 ? card.signals[0].label : `${card.signals[0].label} + ${card.signals.length - 1}`;
    card.element.querySelector(".analysis-tool-state").textContent = MODES[card.mode];
    const legend = card.element.querySelector(".analysis-legend");
    legend.replaceChildren();
    for (const [index, signal] of card.signals.entries()) {
      const item = make("div", "analysis-legend-item");
      const swatch = make("i", "analysis-swatch"); swatch.style.backgroundColor = COLORS[index];
      const label = make("span", "analysis-legend-label", signal.label);
      item.dataset.signalId=signal.id;
      const run = make("span", "analysis-run", signal.runId || "Run unspecified");
      run.title = signal.runId || "No run identifier supplied";
      label.title = [signal.label, signal.description, signal.side, signal.unit].filter(Boolean).join(" · ");
      item.append(swatch, label, run);
      if (card.signals.length > 1) {
        const remove = make("button", "analysis-remove-overlay", "×");
        remove.setAttribute("aria-label", `Remove ${signal.label} from chart`);
        remove.addEventListener("click", () => { card.signals.splice(card.signals.indexOf(signal), 1); refreshCard(card); updateCards(); });
        item.append(remove);
      }
      legend.append(item);
    }
    const maxHarmonics = Math.min(...card.signals.map((s) => {try{return Math.floor(selectSignalInterval(s.timeMs,s.values,card.interval).values.length/2);}catch{return Math.floor(s.values.length/2);}}));
    const harmonicInput = card.element.querySelector(".analysis-harmonics input");
    harmonicInput.max = maxHarmonics;
    harmonicInput.title = `0–${maxHarmonics} harmonics`;
    const allHarmonics = card.element.querySelector(".analysis-all-harmonics");
    allHarmonics.title = `Use all ${maxHarmonics} harmonics${card.signals.length > 1 ? " shared by these signals" : " to reconstruct the original samples"}`;
    allHarmonics.setAttribute("aria-label", allHarmonics.title);
    allHarmonics.hidden = card.mode !== "reconstruction";
    card.harmonics = Math.min(card.harmonics, maxHarmonics);
    harmonicInput.value = card.harmonics;
    card.element.querySelector(".analysis-harmonics").hidden = card.mode !== "reconstruction";
    card.element.querySelectorAll(".analysis-spectrum-option").forEach((node) => { node.hidden = card.mode !== "spectrum"; });
    card.canvas.setAttribute("aria-label", `${MODES[card.mode]} of ${card.signals.map((s) => s.label).join(" and ")}. ${card.mode === "spectrum" ? "Frequency in hertz" : "Time in milliseconds"}; amplitude in ${card.signals[0].unit}. Export CSV for recorded values.`);
    scheduleDraw();
  }

  function draw(card) {
    const width = Math.floor(card.plot.clientWidth), height = Math.floor(card.plot.clientHeight);
    if (width < 80 || height < 50) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (card.canvas.width !== Math.round(width * dpr) || card.canvas.height !== Math.round(height * dpr)) {
      card.canvas.width = Math.round(width * dpr); card.canvas.height = Math.round(height * dpr);
    }
    const ctx = card.canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const errorBox = card.element.querySelector(".analysis-plot-error");
    let traces;
    try { traces = plottedSignals(card); errorBox.hidden = true; }
    catch (error) {
      card.element.querySelector(".analysis-fit-result").hidden=true;
      errorBox.hidden = false; errorBox.textContent = error?.message || "This signal cannot be transformed.";
      card.element.querySelector(".analysis-inspection").textContent = "Choose Time curve to view the original samples.";
      card.element.querySelector(".analysis-method-note").textContent = "";
      card.plotBounds = null; return;
    }
    updateFitResult(card,traces);
    const frequency = card.mode === "spectrum";
    const unit = card.signals[0].unit;
    const left = 65, right = width - 16, top = 22, bottom = height - 38;
    let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
    for (const trace of traces) {
      xMin = Math.min(xMin, trace.x[0]); xMax = Math.max(xMax, trace.x[trace.x.length - 1]);
      for (const value of trace.y) { yMin = Math.min(yMin, value); yMax = Math.max(yMax, value); }
      if(trace.fit)for(const value of trace.selected.values){yMin=Math.min(yMin,value);yMax=Math.max(yMax,value);}
    }
    if (xMax === xMin) xMax = xMin + 1;
    if (frequency) { yMin = 0; yMax = yMax > 0 ? yMax * 1.08 : 1; }
    else { const padding = yMax !== yMin ? (yMax - yMin) * 0.08 : Math.max(Math.abs(yMin) * .05, .01); yMin -= padding; yMax += padding; }
    const px = (x) => left + (x - xMin) / (xMax - xMin) * (right - left);
    const py = (y) => bottom - (y - yMin) / (yMax - yMin) * (bottom - top);
    card.plotBounds = { left, right, xMin, xMax };
    ctx.font = '10px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = top + (bottom - top) * i / 4;
      ctx.strokeStyle = "#343b47"; ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
      ctx.fillStyle = "#a4aebe"; ctx.textAlign = "right"; ctx.fillText(shortNumber(yMax - (yMax - yMin) * i / 4), left - 8, y + 3);
    }
    const tickCount = width < 400 ? 3 : 5;
    for (let i = 0; i <= tickCount; i++) {
      const x = left + (right - left) * i / tickCount;
      ctx.fillStyle = "#a4aebe"; ctx.textAlign = "center"; ctx.fillText(shortNumber(xMin + (xMax - xMin) * i / tickCount), x, bottom + 16);
    }
    ctx.strokeStyle = "#647085"; ctx.beginPath(); ctx.moveTo(left, top); ctx.lineTo(left, bottom); ctx.lineTo(right, bottom); ctx.stroke();
    ctx.fillStyle = "#bbc5d5"; ctx.textAlign = "left"; ctx.fillText(frequency ? `Amplitude (${unit})` : unit, left, 12);
    ctx.textAlign = "center"; ctx.fillText(frequency ? "Frequency (Hz)" : "Time (ms)", (left + right) / 2, height - 5);
    ctx.save(); ctx.beginPath(); ctx.rect(left, top - 1, right - left, bottom - top + 2); ctx.clip();
    if (!frequency && (card.interval || card.pendingEndpoint != null)) {
      const range=card.interval||[card.pendingEndpoint,card.pendingEndpoint],a=px(Math.min(...range)),b=px(Math.max(...range));
      ctx.fillStyle="rgba(104,169,255,.14)";ctx.fillRect(a,top,b-a,bottom-top);ctx.strokeStyle="#72b9ff";ctx.lineWidth=2;
      for(const x of [a,b]){ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,bottom);ctx.stroke();ctx.fillStyle="#72b9ff";ctx.fillRect(x-4,top,8,8);}
    }
    for (const trace of traces) {
      if(trace.fit){ctx.strokeStyle="#9aa3ab";ctx.lineWidth=1;ctx.beginPath();for(let i=0;i<trace.selected.values.length;i++){const x=px(trace.x[i]),y=py(trace.selected.values[i]);if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y);}ctx.stroke();}
      ctx.strokeStyle = trace.color; ctx.lineWidth = 1.5; ctx.beginPath();
      // Preserve extrema when a long recording has more samples than pixels.
      if (trace.x.length > (right - left) * 2) {
        let bucket = -1, min = Infinity, max = -Infinity, bucketX = 0, first = 0, last = 0, started = false;
        const flush = () => {
          if (bucket < 0) return;
          if (started) ctx.lineTo(bucketX, py(first)); else ctx.moveTo(bucketX, py(first));
          ctx.lineTo(bucketX, py(min)); ctx.lineTo(bucketX, py(max)); ctx.lineTo(bucketX, py(last));
          started = true;
        };
        for (let i = 0; i < trace.x.length; i++) {
          const x = px(trace.x[i]), next = Math.floor(x);
          if (next !== bucket) { flush(); bucket = next; min = max = first = last = trace.y[i]; bucketX = x; }
          else { min = Math.min(min, trace.y[i]); max = Math.max(max, trace.y[i]); last = trace.y[i]; }
        }
        flush();
      } else {
        for (let i = 0; i < trace.x.length; i++) {
          const x = px(trace.x[i]), y = py(trace.y[i]);
          if (!i) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
      }
      ctx.stroke();
      if (trace.x.length === 1) { ctx.beginPath(); ctx.arc(px(trace.x[0]), py(trace.y[0]), 2, 0, Math.PI * 2); ctx.fillStyle = trace.color; ctx.fill(); }
    }
    if (!frequency && card.signals.some(isCurrent) && cursorMs >= xMin && cursorMs <= xMax) {
      ctx.strokeStyle = "#a4aebe"; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(px(cursorMs), top); ctx.lineTo(px(cursorMs), bottom); ctx.stroke(); ctx.setLineDash([]);
    }
    if (card.hoverX != null) {
      ctx.strokeStyle = "#a2aab2"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(px(card.hoverX), top); ctx.lineTo(px(card.hoverX), bottom); ctx.stroke();
      for (const trace of traces) {
        if (card.hoverX < trace.x[0] || card.hoverX > trace.x[trace.x.length - 1]) continue;
        const index = nearestIndex(trace.x, card.hoverX);
        ctx.fillStyle = trace.color; ctx.beginPath(); ctx.arc(px(trace.x[index]), py(trace.y[index]), 3, 0, 2 * Math.PI); ctx.fill();
      }
    }
    ctx.restore();
    const inspection = card.element.querySelector(".analysis-inspection");
    if (card.hoverX != null) {
      inspection.textContent = traces.map((trace, index) => {
        if (card.hoverX < trace.x[0] || card.hoverX > trace.x[trace.x.length - 1]) return `${index + 1}: outside recording`;
        const i = nearestIndex(trace.x, card.hoverX);
        return `${traces.length > 1 ? `${index + 1}: ` : ""}${shortNumber(trace.x[i])} ${frequency ? "Hz" : "ms"} · ${shortNumber(trace.y[i])} ${unit}`;
      }).join("   |   ");
    } else if(card.selectionMode==="select"&&!frequency)inspection.textContent=card.pendingEndpoint==null?"Click start, then end; or drag an interval. Drag either boundary to adjust.":`Start ${shortNumber(card.pendingEndpoint)} ms selected. Click the end.`;
    else inspection.textContent = !frequency && card.signals.some(isCurrent) ? `Cursor ${shortNumber(cursorMs)} ms · Click to seek the active recording` : frequency ? "Point to a frequency bin to inspect its amplitude." : "Saved recording · Point to inspect values";
    const notes = [];
    for (const [index, trace] of traces.entries()) {
      const n = trace.x.length;
      const sampling = trace.analysis;
      const prefix = traces.length > 1 ? `${index + 1}: ` : "";
      if (sampling) notes.push(`${prefix}Δt ${shortNumber(sampling.sampleIntervalMs)} ms · Nyquist ${shortNumber(sampling.nyquistHz)} Hz · bin spacing ${shortNumber(sampling.resolutionHz ?? sampling.frequencyResolutionHz)} Hz`);
      else notes.push(`${prefix}${n.toLocaleString()} samples · ${shortNumber(trace.x[0])}–${shortNumber(trace.x[n - 1])} ms`);
    }
    if (card.mode === "reconstruction") notes.push(`${card.harmonics} harmonics + original mean; unwindowed periodic Fourier reconstruction.`);
    if (card.mode === "spectrum") notes.push(`One-sided amplitude · ${card.demean ? "mean removed" : "DC retained"} · ${card.hann ? "Hann window, coherent-gain corrected" : "rectangular window"}.`);
    card.element.querySelector(".analysis-method-note").textContent = notes.join("\n");
  }

  function download(name,type,body) {
    const url=URL.createObjectURL(new Blob([body],{type}));const link=make("a");link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

  function updateFitResult(card,traces) {
    const host=card.element.querySelector(".analysis-fit-result");host.hidden=card.mode!=="reconstruction";if(host.hidden)return;
    card.element.querySelector(".analysis-fit-summary").textContent=traces.map(t=>`${t.signal.label}: RMSE ${shortNumber(t.fit.rmse)} ${t.signal.unit} · R² ${shortNumber(t.fit.rSquared)} · ${t.fit.sampleCount} samples · ${shortNumber(t.fit.startMs)}–${shortNumber(t.fit.endMs)} ms`).join(" | ");
    card.element.querySelector(".analysis-equation").textContent=traces.map(t=>t.fit.equation).join("\n");
    const canvas=card.element.querySelector(".analysis-residual"),width=Math.max(100,Math.round(canvas.clientWidth)),height=70;
    canvas.width=width;canvas.height=height;const ctx=canvas.getContext("2d");if(!ctx)return;ctx.clearRect(0,0,width,height);
    let scale=0;for(const t of traces)for(const v of t.fit.residual)scale=Math.max(scale,Math.abs(v));scale ||=1;
    ctx.strokeStyle="#394252";ctx.beginPath();ctx.moveTo(0,height/2);ctx.lineTo(width,height/2);ctx.stroke();
    for(const t of traces){ctx.strokeStyle=t.color;ctx.beginPath();for(let i=0;i<t.fit.residual.length;i++){const x=i/(t.fit.residual.length-1)*width,y=height/2-t.fit.residual[i]/scale*(height/2-5);if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y);}ctx.stroke();}
  }

  function exportCard(card) {
    try {
      const traces = plottedSignals(card);
      const rows = [["signal_id", "label", "run_id", "view", "x", "x_unit", "value", "value_unit", "harmonics", "remove_mean", "window"]];
      for (const { signal, x, y } of traces) for (let i = 0; i < x.length; i++) rows.push([
        signal.id, signal.label, signal.runId, MODES[card.mode], x[i], card.mode === "spectrum" ? "Hz" : "ms", y[i], signal.unit,
        card.mode === "reconstruction" ? card.harmonics : "", card.mode === "spectrum" ? card.demean : false,
        card.mode === "spectrum" && card.hann ? "hann" : "none",
      ]);
      const blob = new Blob([rows.map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = make("a"); link.href = url; link.download = `cognesia-${card.id}-${card.mode}.csv`;
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      report("Exported the displayed chart data as CSV.");
    } catch (error) { report(error?.message || "This chart could not be exported.", true); }
  }

  async function refresh() {
    const version = ++refreshVersion;
    catalogLoading = true;
    select.disabled = true;
    updateAddButton();
    report("Loading the recorded signal catalog…");
    try {
      const entries = await listSignals();
      if (version !== refreshVersion) return;
      if (!Array.isArray(entries)) throw new Error("The signal catalog is unavailable.");
      catalog = entries.map((entry) => ({ ...entry, id: String(entry.id), label: String(entry.label || entry.id), group: String(entry.group || "Other"), searchText: [entry.label, entry.id, entry.group, entry.side, entry.description].filter(Boolean).join(" ").toLowerCase() }));
      catalogRunId = catalog.find((entry) => entry.runId != null)?.runId ?? null;
      const selectedGroup = group.value;
      group.replaceChildren(new Option("All sources", ""));
      for (const name of [...new Set(catalog.map((entry) => entry.group))].sort()) group.add(new Option(name, name));
      if ([...group.options].some((option) => option.value === selectedGroup)) group.value = selectedGroup;
      updatePicker(); scheduleDraw();
      report(catalog.length ? `${catalog.length.toLocaleString()} recorded signals available. Pin charts to retain a comparison across runs.` : "Load a recording to explore its signals.");
      if (autoDefaults && !defaultsAdded && !cards.length && ["eye:left:mean", "eye:right:mean"].every((id) => catalog.some((entry) => entry.id === id))) {
        defaultsAdded = true;
        for (const id of ["eye:left:mean", "eye:right:mean"]) {
          if (version !== refreshVersion) break;
          await addSignal(id);
        }
      }
    } catch (error) {
      if (version !== refreshVersion) return;
      catalog = [];
      updatePicker();
      report(error?.message || "The recorded signal catalog could not be loaded.", true);
    } finally {
      if (version === refreshVersion) { catalogLoading = false; updateAddButton(); }
    }
  }

  search.addEventListener("input", updatePicker);
  group.addEventListener("change", updatePicker);
  side.addEventListener("change", updatePicker);
  destination.addEventListener("change", updateAddButton);
  addButton.addEventListener("click", async () => {
    if (await addSignal(select.value, destination.value) && compactMode) pickerDisclosure.open = false;
  });
  pickerDisclosure.addEventListener("toggle", scheduleDraw);
  // Docking moves this same instance between the compact grid and custom views.
  resizeObserver?.observe(host);
  syncCompactMode();
  window.addEventListener("resize", scheduleDraw);
  return {
    refresh, addSignal,
    addSignalSnapshot(source) {if(cards.length>=MAX_CARDS)return false;const card=createCard(snapshot(source));cards.push(card);resizeObserver?.observe(card.plot);updateCards();return true;},
    exportState({includeSamples=true}={}) {return cards.map(card=>({mode:card.mode,harmonics:card.harmonics,demean:card.demean,hann:card.hann,interval:card.interval,signals:card.signals.map(s=>({id:s.id,label:s.label,unit:s.unit,runId:s.runId,description:s.description,side:s.side,...(includeSamples?{timeMs:Array.from(s.timeMs),values:Array.from(s.values)}:{})}))}));},
    async restoreState(saved=[]) {for(const item of saved.slice(0,Math.max(0,MAX_CARDS-cards.length))){const signals=[];for(const source of item.signals||[]){try{if(!source.timeMs&&source.runId!=null&&source.runId!==currentRun())continue;signals.push(snapshot(source.timeMs?source:await resolveSignal(source.id)));}catch{}}if(!signals.length)continue;const card=createCard(signals[0]);card.signals=signals.slice(0,MAX_OVERLAYS);card.mode=Object.hasOwn(MODES,item.mode)?item.mode:"time";card.harmonics=Math.max(0,Math.round(item.harmonics??8));card.demean=!!item.demean;card.hann=!!item.hann;card.element.querySelector(".analysis-mode").value=card.mode;card.element.querySelector(".analysis-demean").checked=card.demean;card.element.querySelector(".analysis-hann").checked=card.hann;setInterval(card,item.interval);cards.push(card);resizeObserver?.observe(card.plot);}updateCards();},
    dispose() {disposed=true;refreshVersion++;resizeObserver?.disconnect();window.removeEventListener("resize",scheduleDraw);if(redrawFrame!==null)cancelAnimationFrame(redrawFrame);worker?.terminate();for(const r of workerRequests.values())r.reject(new Error("Chart closed."));workerRequests.clear();},
    setTime(ms) {
      const next = Number(ms);
      if (Number.isFinite(next) && next !== cursorMs) { cursorMs = next; scheduleDraw(); }
    },
  };
}
