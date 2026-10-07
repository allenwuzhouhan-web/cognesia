import { regionLabel, speciesLabel } from "./brain-region-names.js";
import { chemicalTrace, stateTrace } from "./chemistry.js";
// Read only the saved arrays. Preview luminance is deliberately excluded.
export function createSignalAdapter({ getState, requestJSON }) {
  const neuronNames = new Map();
  const sideOf = (value) => ["left", "right", "both"].includes(value) ? value : "unknown";
  const titleSide = (side) => side[0].toUpperCase() + side.slice(1);
  const receptorTable = (s) => s.metadata?.analysis?.receptors || [];
  const columns = (s) => s.summary?.eyes?.columns || [];
  const checkRun = (s, runId) => {
    if (s.summary?.id !== runId) throw new Error("The recording changed. Select this signal again.");
  };
  function listSignals() {
    const s = getState(), runId = s.summary?.id;
    if (!runId) return [];
    const signals = [];
    for (const side of ["left", "right"]) {
      if (columns(s).some((c) => (c.hemisphere || c.side) === side) && s.eyeLuminance) {
        signals.push({ id: `eye:${side}:mean`, label: `${titleSide(side)} eye · mean light input`,
          group: "Eye light input", side, unit: "normalized luminance", kind: "eye", runId });
      }
      if (receptorTable(s).some((r) => r.side === side)) {
        for (const mode of ["raw", "delta"]) signals.push({ id: `receptors:${side}:${mode}`,
          label: `${titleSide(side)} photoreceptors · mean ${mode === "raw" ? "voltage" : "stimulus − baseline"}`,
          group: "Receptor populations", side, unit: "mV", kind: "population", runId });
      }
    }
    if (s.eyeLuminance) columns(s).forEach((column, index) => {
      const side = sideOf(column.hemisphere || column.side);
      signals.push({ id: `eye:column:${index}`, label: `${titleSide(side)} eye · column ${column.column_id ?? index} · light input`,
        group: "Eye light input", side, unit: "normalized luminance", kind: "eye", runId });
    });
    receptorTable(s).forEach((r) => signals.push({ id: `neuron:${r.index}:raw`,
      label: `${titleSide(sideOf(r.side))} ${r.cell_type} · neuron ${r.index} · root ${r.root_id}${r.column_index === null ? " · unmapped light input" : ""}`,
      group: "Individual photoreceptors", side: sideOf(r.side), unit: "mV", kind: "neuron", runId }));
    for (const [group, key, title] of [["type", "traces", "Cell types"], ["region", "region_traces", "Brain areas"], ["class", "class_traces", "Cell classes"]]) {
      (s.summary[key] || []).forEach((trace, index) => {
        const name = trace.name || trace.label || `${title} ${index}`;
        const side = /_L$/.test(name) ? "left" : /_R$/.test(name) ? "right" : "both";
        for (const mode of (s.summary.activity?.baseline_url?["delta", "raw", "baseline"]:["raw"])) signals.push({ id: `trace:${group}:${index}:${mode}`,
          label: `${group === "region" ? regionLabel(name) : name === "None" ? "Unassigned region" : name} · ${mode === "delta" ? "stimulus − baseline" : mode === "raw" ? "voltage" : "baseline"}`,
          group: title, side, unit: "mV", kind: "population", runId });
      });
    }
    if(s.chemistry){const c=s.chemistry;for(let si=0;si<c.species.length;si++)for(let ci=0;ci<c.compartments.length;ci++)for(const mode of ["stimulated","baseline"])signals.push({id:`chemical:${si}:${ci}:${mode}`,label:`${speciesLabel(c.species[si])} · ${regionLabel(c.compartments[ci])} · ${mode}`,group:"Chemical model fields",side:"both",unit:"a.u.",kind:"chemical",runId});for(const name of c.state_names)for(const mode of ["stimulated","baseline"])signals.push({id:`state:${name}:${mode}`,label:`${name} · ${mode} model state`,group:"Internal state assumptions",side:"both",unit:name==="circadian_phase"?"cycles":"normalized",kind:"state",runId});}
    if(s.chemistry?.enzymes?.enabled){const c=s.chemistry;for(const [axis,names,unit] of [['pools',c.enzymes.pool_names,'a.u.'],['flux',c.enzymes.flux_names,'a.u./ms']])names.forEach((name,i)=>c.compartments.forEach((compartment,ci)=>{for(const mode of ['stimulated','baseline'])signals.push({id:`enzyme:${axis}:${i}:${ci}:${mode}`,label:`${name.replaceAll('_',' ')} · ${regionLabel(compartment)} · ${mode}`,group:axis==='pools'?'Enzyme pools':'Enzyme reaction flux',side:'both',unit,kind:'enzyme',runId});}));}
    const organ=s.summary.peripheral;
    if(organ?.enabled)organ.modules.forEach((module,i)=>organ.state_names.forEach((name,si)=>{for(const mode of ['stimulated','baseline'])signals.push({id:`organ:${i}:${si}:${mode}`,label:`${module.label||module.id} · ${name.replaceAll('_',' ')} · ${mode}`,group:'Peripheral organ dynamics',side:'both',unit:name==='cumulative_effort_au_s'?'a.u.·s':'normalized',kind:'organ',runId});}));
    return signals;
  }
  function extract(data, nFrames, width, indices) {
    if (!data || data.length !== nFrames * width || !indices.length)
      throw new Error("This recording does not contain the selected signal.");
    if (indices.some((i) => !Number.isInteger(i) || i < 0 || i >= width))
      throw new Error("Signal index is outside the recorded array.");
    const result = new Float64Array(nFrames);
    for (let f = 0; f < nFrames; f++) {
      let sum = 0;
      for (const index of indices) sum += data[f * width + index];
      result[f] = sum / indices.length;
    }
    return result;
  }
  async function resolveSignal(id) {
    const s = getState(), summary = s.summary;
    if (!summary) throw new Error("Load a completed recording before opening charts.");
    const parts = id.split(":"), runId = summary.id;
    let label, unit = "mV", description, values, timeMs = summary.frames.time_ms;
    let side = "unknown";
    const count = summary.frames.count, width = summary.activity.shape[1];
    if(parts[0] === 'enzyme') {
      const c=s.chemistry,axis=parts[1],i=Number(parts[2]),ci=Number(parts[3]),baseline=parts[4]==='baseline';
      const names=axis==='pools'?c?.enzymes?.pool_names:axis==='flux'?c?.enzymes?.flux_names:null;
      const data=c?.[(baseline?'baseline_':'')+'enzyme_'+(axis==='pools'?'pools_au':'flux_au_per_ms')];
      if(!names||!Number.isInteger(i)||i<0||i>=names.length||!Number.isInteger(ci)||ci<0||ci>=c.compartments.length||!data)throw Error('Enzyme signal is not recorded.');
      values=Float64Array.from(c.time_ms,(_,f)=>data[(f*names.length+i)*c.compartments.length+ci]);timeMs=c.time_ms;unit=axis==='pools'?'a.u.':'a.u./ms';side='both';
      label=`${names[i].replaceAll('_',' ')} · ${regionLabel(c.compartments[ci])} · ${baseline?'baseline':'stimulated'}`;
      description='Recorded intracellular pool or reaction flux under normalized assumed kinetics. Intracellular pools are separate from released chemical fields.';
    } else if(parts[0] === 'organ') {
      const organ=summary.peripheral,i=Number(parts[1]),si=Number(parts[2]),baseline=parts[3]==='baseline';
      if(!organ?.enabled||!Number.isInteger(i)||!organ.modules[i]||!Number.isInteger(si)||!organ.state_names[si])throw Error('Peripheral signal is not recorded.');
      const data=baseline?organ.baseline_state_values:organ.state_values;
      values=Float64Array.from(organ.time_ms,(_,f)=>data[f][i][si]);timeMs=organ.time_ms;unit=organ.state_names[si]==='cumulative_effort_au_s'?'a.u.·s':'normalized';side='both';
      label=`${organ.modules[i].label||organ.modules[i].id} · ${organ.state_names[si]} · ${baseline?'baseline':'stimulated'}`;
      description='Recorded peripheral module equation output. Anatomical identities and explicitly modeled functional links retain separate provenance; these normalized dynamics are not calibrated organ physiology.';
    } else if(parts[0] === "chemical") {
      const c=s.chemistry,si=Number(parts[1]),ci=Number(parts[2]),baseline=parts[3]==="baseline";
      if(!c||!Number.isInteger(si)||si<0||si>=c.species.length||!Number.isInteger(ci)||ci<0||ci>=c.compartments.length)throw Error("Chemical signal is not recorded.");
      values=chemicalTrace(c,si,ci,baseline);timeMs=c.time_ms;unit="a.u.";side="both";
      label=`${speciesLabel(c.species[si])} · ${regionLabel(c.compartments[ci])} · ${baseline?"baseline":"stimulated"}`;
      description="Recorded compartment model concentration. Receptor/source parameters are assumptions; this is not molecule imaging or a measured absolute concentration.";
    } else if(parts[0] === "state") {
      const c=s.chemistry;if(!c)throw Error("Internal state is not recorded.");const baseline=parts[2]==="baseline";
      values=stateTrace(c,parts[1],baseline);timeMs=c.time_ms;unit=parts[1]==="circadian_phase"?"cycles":"normalized";side="both";
      label=`${parts[1]} · ${baseline?"baseline":"stimulated"} model state`;description="Recorded endocrine/state equation output under declared assumed boundary conditions; not measured physiology.";
    } else if (parts[0] === "eye") {
      const eye = summary.eyes, list = columns(s), shape = eye.shape;
      if (!shape || !s.eyeLuminance) throw new Error("Recorded eye input is unavailable for this run.");
      const selected = parts[1] === "column" ? [Number(parts[2])] : list.flatMap((c, i) => (c.hemisphere || c.side) === parts[1] ? [i] : []);
      values = extract(s.eyeLuminance, shape[0], shape[1], selected);
      timeMs = eye.time_ms;
      const column = parts[1] === "column" ? list[selected[0]] : null;
      side = sideOf(column?.hemisphere || column?.side || parts[1]);
      label = `${titleSide(side)} eye · ${column ? `column ${column.column_id ?? selected[0]}` : "mean light input"}`;
      unit = "normalized luminance";
      description = column ? `Recorded Gaussian-smoothed optical input; azimuth ${Number(column.azimuth_deg).toFixed(2)}°, elevation ${Number(column.elevation_deg).toFixed(2)}°. This is light input, not membrane voltage.` : `Mean recorded light input across ${selected.length} optical columns. This is not the average voltage of photoreceptor neurons.`;
    } else if (parts[0] === "neuron") {
      const index = Number(parts[1]), mode = parts[2] || "raw";
      if (!["raw", "baseline", "delta"].includes(mode)) throw new Error("Unknown voltage channel.");
      values = extract(s.activity[mode], count, width, [index]);
      let neuron = receptorTable(s).find((r) => r.index === index) || neuronNames.get(`${runId}:${index}`);
      if (!neuron) {
        const query=new URLSearchParams({model_id:summary.model_id||'flywire-783',run_id:runId});
        neuron = await requestJSON(`/api/neuron/${index}?${query}`);
        checkRun(getState(), runId);
        neuronNames.set(`${runId}:${index}`, neuron);
      }
      side = sideOf(neuron.side);
      label = `${titleSide(side)} ${neuron.cell_type || "neuron"} · ${index} · ${mode === "raw" ? "voltage" : mode === "baseline" ? "baseline" : "stimulus − baseline"}`;
      description = `Root ${neuron.root_id}. Recorded model membrane voltage, one state per neuron.${neuron.column_index === null ? " Optical column unassigned; no mapped light input." : ""}${neuron.assignment_source ? ` Column mapping: ${neuron.assignment_source}.` : ""}`;
    } else if (parts[0] === "receptors") {
      side = sideOf(parts[1]);
      const mode = parts[2], selected = receptorTable(s).filter((r) => r.side === side).map((r) => r.index);
      if (!["raw", "baseline", "delta"].includes(mode)) throw new Error("Unknown voltage channel.");
      values = extract(s.activity[mode], count, width, selected);
      label = `${titleSide(side)} photoreceptors · ${mode === "raw" ? "mean voltage" : "mean stimulus − baseline"}`;
      description = `Arithmetic mean of ${selected.length} annotated photoreceptor neuron voltages, including neurons without mapped optical input.`;
    } else if (parts[0] === "trace") {
      const key = {type: "traces", region: "region_traces", class: "class_traces"}[parts[1]];
      const trace = key && summary[key]?.[Number(parts[2])], mode = parts[3];
      if (!trace || !["raw", "baseline", "delta"].includes(mode)) throw new Error("Unknown population trace.");
      values = trace[{raw: "raw", baseline: "baseline", delta: "values"}[mode]] || trace[`${mode}_mv`];
      label = `${parts[1] === "region" ? regionLabel(trace.name || trace.label) : trace.name || trace.label} · ${mode === "raw" ? "voltage" : mode === "baseline" ? "baseline" : "stimulus − baseline"}`;
      side = /_L$/.test(trace.name) ? "left" : /_R$/.test(trace.name) ? "right" : "both";
      description = parts[1] === "region" ? "Synapse-endpoint-fraction weighted mean model voltage in this brain area." : "Mean recorded membrane voltage of the annotated population.";
    } else throw new Error("Unknown recorded signal.");
    if (!timeMs || !values || timeMs.length !== values.length)
      throw new Error("Recorded signal and sampling times do not match.");
    return {id, label, unit, timeMs: Float64Array.from(timeMs), values: Float64Array.from(values), runId,
      runLabel: summary.label, description, side, isCurrentRun: true};
  }
  return {listSignals, resolveSignal};
}
