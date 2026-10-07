const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const lab = {
  configured: false,
  bootstrap: null,
  schema: [],
  targets: [],
  presets: [],
  hooks: null,
  preset: null,
  parameterGroup: "all",
  pollTimer: null,
  electrodes: [],
  selected: 0,
  nextId: 1,
  applyingPreset: false,
};
const electrodeFields = {
  voltage_mv: "electrode-amplitude",
  frequency_hz: "electrode-frequency",
  duty_percent: "electrode-duty",
  start_ms: "electrode-onset",
  end_ms: "electrode-end",
  phase_deg: "electrode-phase",
};
const defaultElectrode = () => ({
  id: `electrode-${lab.nextId++}`,
  target: { kind: "body_zone", name: "left_eye" },
  voltage_mv: 5,
  frequency_hz: 20,
  duty_percent: 50,
  start_ms: 100,
  end_ms: Number($("#duration").value),
  phase_deg: 0,
});
const groupOf = (entry) =>
  String(entry.group || "neural")
    .toLowerCase()
    .includes("opt")
    ? "optical"
    : "neural";
const schemaDefault = (key, fallback) =>
  lab.schema.find((e) => e.key === key)?.default ?? fallback;

export function initializeLab(hooks) {
  lab.hooks = hooks;
  lab.electrodes = [defaultElectrode()];
  $$("[data-input-tab]").forEach((button) =>
    button.addEventListener("click", () => {
      const selected = button.dataset.inputTab;
      $("#vision-controls").hidden = selected !== "vision";
      $("#electrode-controls").hidden = selected !== "electrical";
      $("#chemical-controls").hidden = selected !== "chemistry";
      $$("[data-input-tab]").forEach((item) =>
        item.classList.toggle("active", item === button),
      );
      drawPulse();
    }),
  );
  $$("[data-electrode-site]").forEach((site) => {
    const select = () => {
      if (!lab.configured) return;
      $("#electrode-target").value = site.dataset.electrodeSite;
      $("#electrical-enabled").checked = true;
      changed();
    };
    site.addEventListener("click", select);
    site.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select();
      }
    });
  });
  for (const id of [
    "electrical-enabled",
    "electrode-target",
    ...Object.values(electrodeFields),
  ])
    $("#" + id).addEventListener("input", changed);
  $("#electrode-polarity").addEventListener("input", () => {
    $("#electrode-amplitude").value =
      Math.abs(Number($("#electrode-amplitude").value)) *
      ($("#electrode-polarity").value === "negative" ? -1 : 1);
    changed();
  });
  $("#add-electrode").addEventListener("click", () => addElectrode());
  $("#remove-electrode").addEventListener("click", () => {
    saveEditor();
    lab.electrodes.splice(lab.selected, 1);
    lab.selected = Math.max(0, lab.selected - 1);
    if (!lab.electrodes.length) {
      lab.electrodes = [defaultElectrode()];
      $("#electrical-enabled").checked = false;
    }
    loadEditor();
    changed();
  });
  for (const id of ["compute-threads", "compute-snapshot", "compute-timestep"])
    $("#" + id).addEventListener("input", () => {
      lab.preset = null;
      changed();
    });
  $("#compute-duration").addEventListener("input", () => {
    $("#duration").value = $("#compute-duration").value;
    $("#duration").dispatchEvent(new Event("input", { bubbles: true }));
    lab.preset = null;
    changed();
  });
  $("#duration").addEventListener("input", () => {
    $("#compute-duration").value = $("#duration").value;
    if (!lab.applyingPreset) lab.preset = null;
    updateEstimate();
    drawPulse();
  });
  const workspaceTabs = [$("#simulation-tab"), $("#parameters-tab")];
  const selectWorkspace = (selected, focus = false) => {
    workspaceTabs.forEach((tab) => {
      const active = tab === selected;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      $("#" + tab.getAttribute("aria-controls")).hidden = !active;
    });
    const sessionControls = $("#session-controls");
    if (sessionControls) sessionControls.hidden = selected !== workspaceTabs[0];
    document.body.classList.toggle("parameters-page", selected === workspaceTabs[1]);
    window.scrollTo({top: 0});
    if (focus) selected.focus();
    requestAnimationFrame(() => {
      drawPulse();
      window.dispatchEvent(new Event("resize"));
    });
  };
  workspaceTabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectWorkspace(tab));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const target = event.key === "Home" ? 0 : event.key === "End" ? 1 : 1 - index;
      selectWorkspace(workspaceTabs[target], true);
    });
  });
  $("#open-workbench").addEventListener("click", () =>
    selectWorkspace(workspaceTabs[1], true),
  );
  $("#reset-lab").addEventListener("click", () => {
    restoreLabOptions({ duration_ms: Number($("#duration").value) });
    lab.hooks.onEdited?.();
  });
  $("#lab-run-button").addEventListener("click", () => {
    selectWorkspace(workspaceTabs[0]);
    $("#run-button").focus();
  });
  $$("[data-parameter-group]").forEach((button) =>
    button.addEventListener("click", () => {
      lab.parameterGroup = button.dataset.parameterGroup;
      $$("[data-parameter-group]").forEach((item) =>
        item.classList.toggle("active", item === button),
      );
      $$(".parameter-field").forEach(
        (field) =>
          (field.hidden =
            lab.parameterGroup !== "all" &&
            field.dataset.group !== lab.parameterGroup),
      );
    }),
  );
  window.addEventListener("resize", drawPulse);
  loadEditor();
}
export function configureLab(bootstrap) {
  lab.bootstrap = bootstrap;
  const schema = bootstrap.parameter_schema || [];
  lab.schema = Array.isArray(schema)
    ? schema
    : schema.parameters ||
      Object.values(schema).flatMap((v) => (Array.isArray(v) ? v : []));
  lab.targets = bootstrap.electrical_targets || [];
  lab.presets = bootstrap.performance_presets || [];
  lab.configured = Boolean(
    bootstrap.parameter_schema && bootstrap.electrical_targets,
  );
  if (lab.targets.length)
    $("#electrode-target").replaceChildren(
      ...lab.targets.map(
        (target) =>
          new Option(target.label || target.name || target.id, target.id),
      ),
    );
  renderParameters();
  renderPresets();
  const limits = bootstrap.simulation_limits || {},
    duration = limits.duration_ms || [300, 10000];
  for (const id of ["compute-duration", "duration"]) {
    const element = $("#" + id);
    element.min = duration[0];
    element.max = duration[1];
    element.step = limits.duration_step_ms || 20;
  }
  const threads = limits.max_threads || limits.logical_cpus || 64;
  $("#compute-threads").max = threads;
  $("#compute-threads").value = Math.min(threads, limits.threads || 16);
  fillChoices(
    "#compute-snapshot",
    limits.record_dt_ms_options ||
      limits.snapshot_ms_options || [2, 5, 10, 20, 50],
    limits.default_record_dt_ms || schemaDefault("display_sample_ms", 20),
    " ms",
  );
  fillChoices(
    "#compute-timestep",
    limits.dt_ms_options ||
      lab.schema.find((e) => e.key === "dt")?.choices || [0.05, 0.1, 0.2],
    schemaDefault("dt", 0.1),
    " ms",
  );
  $("#compute-duration").value = $("#duration").value;
  for (const input of $$(
    "#electrode-controls input, #electrode-controls select, #electrode-controls button, .compute-fields input, .compute-fields select, #reset-lab, #lab-run-button",
  ))
    input.disabled = !lab.configured;
  $$("[data-electrode-site]").forEach((site) =>
    site.setAttribute("aria-disabled", String(!lab.configured)),
  );
  $("#lab-settings-summary").textContent = lab.configured
    ? "Original model parameters"
    : "Advanced controls awaiting model API";
  $("#resource-status").textContent = lab.configured
    ? "CONNECTING"
    : "UNAVAILABLE";
  if (lab.configured) pollResources();
  loadEditor();
  updateEstimate();
}
function fillChoices(selector, values, current, suffix) {
  const items = Array.isArray(values) ? values : [values];
  const select = $(selector);
  select.replaceChildren(
    ...items.map((value) => new Option(`${value}${suffix}`, value)),
  );
  select.value = items.map(Number).includes(Number(current))
    ? current
    : items[0];
}
function renderParameters() {
  const container = $("#parameter-controls");
  if (!lab.schema.length) {
    container.innerHTML =
      '<p class="lab-loading">Parameter controls become available when the local model exposes its editable schema.</p>';
    return;
  }
  container.innerHTML = lab.schema
    .filter((entry) => !["dt", "display_sample_ms"].includes(entry.key))
    .map((entry, index) => {
      const key = entry.key || entry.name,
        group = groupOf(entry),
        value = entry.default ?? entry.value ?? 0,
        options = entry.options || entry.choices;
      const attrs = `data-parameter-key="${escapeHTML(key)}" id="lab-param-${index}"`;
      const input = options
        ? `<select ${attrs}>${options
            .map((option) => {
              const v = typeof option === "object" ? option.value : option,
                label = typeof option === "object" ? option.label || v : option;
              return `<option value="${escapeHTML(v)}" ${String(v) === String(value) ? "selected" : ""}>${escapeHTML(label)}</option>`;
            })
            .join("")}</select>`
        : `<input ${attrs} type="number" ${entry.min !== undefined ? `min="${entry.min}"` : ""} ${entry.max !== undefined ? `max="${entry.max}"` : ""} step="${entry.step ?? "any"}" value="${escapeHTML(value)}" />`;
      return `<div class="parameter-field" data-group="${group}" title="${escapeHTML(entry.help || "")}"><label for="lab-param-${index}">${escapeHTML(entry.label || key.replaceAll("_", " "))}<span>${escapeHTML(entry.unit || "")}</span></label>${input}<p>${escapeHTML(entry.help || entry.description || "")}</p><div class="parameter-provenance"><span>${group.toUpperCase()}</span><span>${escapeHTML(entry.source || "MODEL PARAMETER")}</span></div></div>`;
    })
    .join("");
  $$("[data-parameter-key]").forEach((input) =>
    input.addEventListener("input", changed),
  );
}
function renderPresets() {
  $("#performance-presets").innerHTML = lab.presets.length
    ? lab.presets
        .map(
          (p) =>
            `<button data-performance-preset="${escapeHTML(p.id)}"><strong>${escapeHTML(p.label || p.id)}</strong><span>${escapeHTML(p.description || `${p.threads} threads · ${p.duration_ms} ms`)}</span></button>`,
        )
        .join("")
    : '<span class="lab-loading">No compute presets advertised by this model.</span>';
  $$("[data-performance-preset]").forEach((button) =>
    button.addEventListener("click", () =>
      applyPreset(
        lab.presets.find((p) => p.id === button.dataset.performancePreset),
      ),
    ),
  );
}
function applyPreset(preset) {
  if (!preset) return;
  saveEditor();
  const values = preset.options || preset;
  lab.preset = preset.id;
  lab.applyingPreset = true;
  const previousDuration = Number($("#duration").value);
  for (const [key, id] of [
    ["threads", "compute-threads"],
    ["duration_ms", "compute-duration"],
    ["record_dt_ms", "compute-snapshot"],
    ["dt_ms", "compute-timestep"],
  ])
    if (values[key] !== undefined) $("#" + id).value = values[key];
  if (values.neural_overrides?.dt !== undefined)
    $("#compute-timestep").value = values.neural_overrides.dt;
  for (const entry of lab.schema) {
    const key = entry.key || entry.name,
      input = $$("[data-parameter-key]").find(
        (e) => e.dataset.parameterKey === key,
      ),
      value =
        values[
          groupOf(entry) === "optical" ? "visual_overrides" : "neural_overrides"
        ]?.[key];
    if (input && value !== undefined) input.value = value;
  }
  $("#duration").value = $("#compute-duration").value;
  $("#duration").dispatchEvent(new Event("input", { bubbles: true }));
  lab.applyingPreset = false;
  for (const e of lab.electrodes)
    if (e.end_ms === previousDuration) e.end_ms = Number($("#duration").value);
  loadEditor();
  changed();
}
function changed() {
  lab.recordingCurrent = false;
  saveEditor();
  lab.hooks?.onEdited?.();
  updateElectrode();
  updateEstimate();
  updateParameterCount();
  drawPulse();
}
function saveEditor() {
  const e = lab.electrodes[lab.selected];
  if (!e) return;
  const target = $("#electrode-target").value;
  if (target.startsWith("neuron:"))
    e.target = { kind: "indices", indices: [Number(target.split(":")[1])] };
  else if (target !== "custom") e.target = { kind: "body_zone", name: target };
  for (const [key, id] of Object.entries(electrodeFields))
    e[key] = Number($("#" + id).value);
}
function loadEditor() {
  const e = lab.electrodes[lab.selected];
  if (!e) return;
  let target =
    e.target.kind === "body_zone"
      ? e.target.name
      : e.target.kind === "indices" && e.target.indices.length === 1
        ? `neuron:${e.target.indices[0]}`
        : "custom";
  if (![...$("#electrode-target").options].some((o) => o.value === target))
    $("#electrode-target").add(
      new Option(
        target === "custom"
          ? "Recorded custom target"
          : `Selected neuron ${Number(e.target.indices[0]).toLocaleString()}`,
        target,
      ),
    );
  $("#electrode-target").value = target;
  for (const [key, id] of Object.entries(electrodeFields))
    $("#" + id).value = e[key];
  updateElectrode();
  drawPulse();
}
function addElectrode(target) {
  if (!lab.configured || lab.electrodes.length >= 16) return;
  saveEditor();
  const e = defaultElectrode();
  if (target) e.target = target;
  if (!$("#electrical-enabled").checked) {
    lab.electrodes = [e];
    lab.selected = 0;
  } else {
    lab.electrodes.push(e);
    lab.selected = lab.electrodes.length - 1;
  }
  $("#electrical-enabled").checked = true;
  loadEditor();
  changed();
}
export function addNeuronElectrode(index) {
  addElectrode({ kind: "indices", indices: [index] });
  $('[data-input-tab="electrical"]').click();
  $("#electrode-controls").scrollIntoView({
    behavior: "smooth",
    block: "center",
  });
}
function targetLabel(e) {
  if (e.target.kind === "body_zone")
    return (
      lab.targets.find((t) => t.id === e.target.name)?.label ||
      e.target.name.replaceAll("_", " ")
    );
  if (e.target.kind === "indices")
    return `Neuron ${e.target.indices[0].toLocaleString()}${e.target.indices.length > 1 ? " +" : ""}`;
  return "Custom target";
}
function updateElectrode() {
  const enabled = $("#electrical-enabled").checked,
    selected = $("#electrode-target").value,
    e = lab.electrodes[lab.selected];
  $$("[data-electrode-site]").forEach((site) => {
    site.classList.toggle(
      "active",
      enabled && site.dataset.electrodeSite === selected,
    );
    site.classList.toggle(
      "occupied",
      enabled &&
        lab.electrodes.some(
          (item) =>
            item.target.kind === "body_zone" &&
            item.target.name === site.dataset.electrodeSite,
        ),
    );
  });
  $("#electrode-enabled-dot").classList.toggle("on", enabled);
  $("#electrode-count").textContent =
    `${enabled ? lab.electrodes.length : 0} / 16`;
  $("#electrode-list").innerHTML = lab.electrodes
    .map(
      (item, index) =>
        `<button data-electrode-index="${index}" class="${index === lab.selected ? "active" : ""}">${index + 1} · ${escapeHTML(targetLabel(item))}</button>`,
    )
    .join("");
  $$("[data-electrode-index]").forEach((button) =>
    button.addEventListener("click", () => {
      saveEditor();
      lab.selected = Number(button.dataset.electrodeIndex);
      loadEditor();
    }),
  );
  $("#add-electrode").disabled = !lab.configured || lab.electrodes.length >= 16;
  $("#electrode-polarity").value =
    Number($("#electrode-amplitude").value) < 0 ? "negative" : "positive";
  const target = lab.targets.find((t) => t.id === selected),
    count = target?.count ?? target?.neuron_count;
  $("#electrode-mapping-note").textContent =
    e?.target.kind === "indices"
      ? `Direct model-neuron target · ${e.target.indices.length.toLocaleString()} neuron${e.target.indices.length === 1 ? "" : "s"}. Full arbor shares its point-neuron voltage.`
      : target
        ? `${target.mapping_note || target.description || target.label}${count !== undefined ? ` · ${Number(count).toLocaleString()} neurons` : ""}`
        : "Brain target mapping will be reported by the local model.";
  const frequency = Number($("#electrode-frequency").value);
  $("#pulse-preview-label").textContent =
    `${frequency === 0 ? "DC" : `${frequency} Hz · ${$("#electrode-duty").value}%`} · ${$("#electrode-amplitude").value} mV`;
}
function parameterOverrides() {
  const out = { neural_overrides: {}, visual_overrides: {} };
  for (const entry of lab.schema) {
    const key = entry.key || entry.name,
      input = $$("[data-parameter-key]").find(
        (e) => e.dataset.parameterKey === key,
      );
    if (!input) continue;
    const value = Number(input.value);
    if (value !== Number(entry.default ?? entry.value ?? 0))
      out[
        groupOf(entry) === "optical" ? "visual_overrides" : "neural_overrides"
      ][key] = value;
  }
  const dt = Number($("#compute-timestep").value);
  if (dt !== Number(schemaDefault("dt", 0.1))) out.neural_overrides.dt = dt;
  return out;
}
export function collectLabOptions() {
  if (!lab.configured) return {};
  saveEditor();
  return {
    ...parameterOverrides(),
    threads: Number($("#compute-threads").value),
    record_dt_ms: Number($("#compute-snapshot").value),
    electrodes: $("#electrical-enabled").checked
      ? lab.electrodes.map((e) => ({ ...e, target: structuredClone(e.target) }))
      : [],
  };
}
export function restoreLabOptions(options = {}) {
  if (!lab.configured) return;
  lab.electrodes = options.electrodes?.length
    ? options.electrodes.map((e) =>
        Object.fromEntries(
          ["id", "label", "target", ...Object.keys(electrodeFields)]
            .filter((key) => e[key] !== undefined)
            .map((key) => [key, structuredClone(e[key])]),
        ),
      )
    : [defaultElectrode()];
  lab.nextId = Math.max(
    lab.nextId,
    ...lab.electrodes.map(
      (e) => Number(e.id?.replace("electrode-", "")) + 1 || 1,
    ),
  );
  lab.selected = 0;
  $("#electrical-enabled").checked = Boolean(options.electrodes?.length);
  const limits = lab.bootstrap?.simulation_limits || {};
  $("#compute-threads").value = options.threads ?? limits.threads ?? 16;
  $("#compute-snapshot").value =
    options.record_dt_ms ?? schemaDefault("display_sample_ms", 20);
  $("#compute-timestep").value =
    options.neural_overrides?.dt ?? schemaDefault("dt", 0.1);
  $("#compute-duration").value = options.duration_ms ?? $("#duration").value;
  for (const entry of lab.schema) {
    const key = entry.key || entry.name,
      input = $$("[data-parameter-key]").find(
        (e) => e.dataset.parameterKey === key,
      );
    if (input)
      input.value =
        options[
          groupOf(entry) === "optical" ? "visual_overrides" : "neural_overrides"
        ]?.[key] ??
        entry.default ??
        entry.value ??
        0;
  }
  lab.preset = null;
  loadEditor();
  updateEstimate();
  updateParameterCount();
}
function updateParameterCount() {
  const p = parameterOverrides(),
    count =
      Object.keys(p.neural_overrides).length +
      Object.keys(p.visual_overrides).length;
  $("#parameter-change-count").textContent = count
    ? `${count} EDITED`
    : "DEFAULTS";
  if (lab.configured)
    $("#lab-settings-summary").textContent =
      `${$("#electrical-enabled").checked ? `${lab.electrodes.length} electrode${lab.electrodes.length === 1 ? "" : "s"} + visual drive` : "Visual drive"} · ${count ? `${count} edited parameters` : "model defaults"}`;
}
function updateEstimate() {
  const duration = Number($("#compute-duration").value),
    interval = Number($("#compute-snapshot").value) || 20,
    frames = Math.ceil(duration / interval),
    bytes = (lab.bootstrap?.neuron_count || 138639) * frames * 4 * 3;
  const recordingBudget =
    lab.bootstrap?.simulation_limits?.recording_budget_bytes ?? 3e9;
  $("#compute-estimate").textContent =
    `${Number.isFinite(frames) ? frames.toLocaleString() : "—"} whole-brain snapshots · paired playback ≈ ${bytes > 1e9 ? `${(bytes / 1e9).toFixed(2)} GB` : `${Math.round(bytes / 1e6)} MB`}.${bytes > recordingBudget ? ` Exceeds the ${(recordingBudget / 1e9).toFixed(1)} GB playback limit; increase record interval or shorten duration.` : " Smaller integration steps add real simulation work."}`;
  $("#compute-estimate").classList.toggle("error", bytes > recordingBudget);
  $("#compute-preset-name").textContent = lab.preset
    ? (
        lab.presets.find((p) => p.id === lab.preset)?.label || lab.preset
      ).toUpperCase()
    : "CUSTOM";
  $$("[data-performance-preset]").forEach((button) =>
    button.classList.toggle(
      "active",
      button.dataset.performancePreset === lab.preset,
    ),
  );
}
export function setLabRecording(stimulation, duration) {
  lab.stimulation = stimulation;
  lab.recordedDuration = duration;
  lab.recordingCurrent = true;
  lab.playbackTime = 0;
  drawPulse();
}
export function updateLabPlayback(time, recorded) {
  lab.playbackTime = time;
  if (!recorded) lab.recordingCurrent = false;
  if (!$("#electrode-controls").hidden) drawPulse();
}
export function setLabRunning(running) {
  $("#lab-run-button").disabled = running || !lab.configured;
  $("#lab-run-button").innerHTML = running
    ? "Computing experiment…"
    : "Review in Simulate";
}
function drawPulse() {
  const canvas = $("#pulse-canvas");
  if (!canvas?.clientWidth) return;
  const width = canvas.clientWidth,
    height = canvas.clientHeight,
    ratio = Math.min(devicePixelRatio, 2);
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);
  const amplitude = Number($("#electrode-amplitude").value),
    frequency = Number($("#electrode-frequency").value),
    duty = Number($("#electrode-duty").value) / 100,
    start = Number($("#electrode-onset").value),
    end = Number($("#electrode-end").value),
    phase = Number($("#electrode-phase").value) / 360,
    duration = Number($("#duration").value) || 600,
    enabled = $("#electrical-enabled").checked;
  ctx.strokeStyle = "#394252";
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(0, height / 2);
  ctx.lineTo(width, height / 2);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.strokeStyle = enabled ? "#72b9ff" : "#7f8da1";
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  for (let x = 0; x <= width; x++) {
    const time = (x / width) * duration,
      pulsePhase = (((time - start) * frequency) / 1000 + phase) % 1,
      on =
        enabled &&
        time >= start &&
        time < end &&
        (frequency === 0 || pulsePhase < duty);
    const value = on
        ? Math.sign(amplitude) * Math.min(1, Math.abs(amplitude) / 20)
        : 0,
      y = height / 2 - value * height * 0.34;
    x ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.stroke();
  const recording = lab.recordingCurrent && lab.stimulation?.input_mv?.length;
  const sourceIndex = recording
    ? lab.stimulation.definitions?.findIndex(
        (e) => e.id === lab.electrodes[lab.selected]?.id,
      )
    : -1;
  $("#pulse-source-label").textContent =
    sourceIndex >= 0 ? "RECORDED DRIVE · SAMPLED" : "PROGRAMMED DRIVE";
  if (sourceIndex >= 0) {
    ctx.clearRect(0, 0, width, height);
    ctx.strokeStyle = "#72b9ff";
    ctx.beginPath();
    const times = lab.stimulation.time_ms,
      values = lab.stimulation.input_mv,
      max = Math.max(
        1,
        ...values.map((row) => Math.abs(row[sourceIndex] || 0)),
      ),
      total = lab.recordedDuration || duration;
    for (let i = 0; i < times.length; i++) {
      const x = (times[i] / total) * width,
        y = height / 2 - ((values[i][sourceIndex] || 0) / max) * height * 0.34;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.stroke();
    const cursor = Math.min(width, (lab.playbackTime / total) * width);
    ctx.strokeStyle = "#efa979";
    ctx.setLineDash([2, 2]);
    ctx.beginPath();
    ctx.moveTo(cursor, 0);
    ctx.lineTo(cursor, height);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.fillStyle = "#a4aebe";
  ctx.font = "9px monospace";
  ctx.fillText("0 ms", 2, height - 3);
  ctx.textAlign = "right";
  ctx.fillText(`${duration} ms`, width - 2, height - 3);
}
async function pollResources() {
  clearTimeout(lab.pollTimer);
  const num = (x) => (x == null ? NaN : Number(x));
  try {
    const d = await lab.hooks.requestJSON("/api/resources"),
      cpu = num(d.cpu_percent),
      total = num(d.memory_total_gb),
      available = num(d.memory_available_gb),
      used =
        d.memory_used_gb == null ? total - available : num(d.memory_used_gb);
    lab.hooks?.onActiveJob?.(d.active_job);
    $("#resource-status").textContent = "LIVE";
    $("#resource-cpu").textContent = Number.isFinite(cpu)
      ? `${Math.round(cpu)}%`
      : "—";
    $("#resource-memory").textContent = Number.isFinite(used)
      ? `${used.toFixed(1)} GB`
      : "—";
    $("#resource-cpu-bar").style.width =
      `${Math.max(0, Math.min(100, cpu || 0))}%`;
    $("#resource-memory-bar").style.width =
      `${Math.max(0, Math.min(100, (used / total) * 100 || 0))}%`;
    $("#resource-process").textContent = Number.isFinite(num(d.rss_gb))
      ? `${num(d.rss_gb).toFixed(2)} GB`
      : "—";
    $("#resource-available").textContent = Number.isFinite(available)
      ? `${available.toFixed(1)} / ${total.toFixed(0)} GB`
      : "—";
    $("#resource-cores").textContent = d.logical_cpus ?? "—";
    $("#mini-cpu").textContent = Number.isFinite(cpu)
      ? `CPU ${Math.round(cpu)}%`
      : "CPU —";
    $("#mini-ram").textContent = Number.isFinite(used)
      ? `RAM ${used.toFixed(1)} GB`
      : "RAM —";
  } catch {
    $("#resource-status").textContent = "OFFLINE";
    $("#mini-cpu").textContent = "CPU —";
    $("#mini-ram").textContent = "RAM —";
  }
  lab.pollTimer = setTimeout(pollResources, 2500);
}
