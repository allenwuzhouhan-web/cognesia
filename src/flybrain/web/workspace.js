const STORAGE_KEY = "cognesia.workspace.layout.v1";
const DIVIDER_WIDTH = 8;
let workspace = null;

const clamp = (value, minimum, maximum) =>
  Math.round(Math.max(minimum, Math.min(Math.max(minimum, maximum), value)));
const finiteNumber = (value, fallback) =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;

function layoutMode(viewportWidth) {
  return viewportWidth <= 620 ? "stacked" : viewportWidth <= 1100 ? "narrow" : "wide";
}

function defaultLayout() {
  const viewportHeight = window.innerHeight || 800;
  const mode = layoutMode(window.innerWidth);
  return {
    version: 1,
    widths: {
      wide: { input: window.innerWidth >= 1650 ? 240 : 224, readout: window.innerWidth >= 1650 ? 280 : 256 },
      narrow: { input: 205 },
    },
    heights: {
      brain: mode === "stacked" ? 370 : window.innerWidth <= 800 ? 420 : clamp(viewportHeight * 0.55, 390, 630),
      input: clamp(viewportHeight - 175, 470, 800),
      readout: mode === "wide" ? clamp(viewportHeight - 175, 500, 850) : 510,
    },
  };
}

function restoredLayout() {
  const defaults = defaultLayout();
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (!saved || saved.version !== 1) return defaults;
    for (const [mode, fields] of Object.entries(defaults.widths)) {
      for (const key of Object.keys(fields)) {
        fields[key] = finiteNumber(saved.widths?.[mode]?.[key], fields[key]);
      }
    }
    for (const key of Object.keys(defaults.heights)) {
      defaults.heights[key] = finiteNumber(saved.heights?.[key], defaults.heights[key]);
    }
  } catch {
    // A disabled or full browser store must not prevent pane resizing.
  }
  return defaults;
}

function fitWidths(width, mode, preferences) {
  if (mode === "stacked") return { input: width, readout: width, brain: width };
  if (mode === "narrow") {
    const available = width - DIVIDER_WIDTH;
    const input = clamp(preferences.widths.narrow.input, 170, Math.min(360, available - 300));
    return { input, readout: width, brain: available - input };
  }
  const available = width - DIVIDER_WIDTH * 2;
  const input = clamp(preferences.widths.wide.input, 180, Math.min(480, available - 220 - 320));
  const readout = clamp(preferences.widths.wide.readout, 220, Math.min(640, available - input - 320));
  return { input, readout, brain: available - input - readout };
}

function heightBounds(key) {
  return {
    minimum: key === "brain" ? 220 : key === "input" ? 260 : 220,
    maximum: Math.min(2200, Math.max(key === "brain" ? 1000 : 1200, (window.innerHeight || 800) * 2)),
  };
}

function limitsFor(key) {
  if (key.endsWith("-height")) return heightBounds(key.replace("-height", ""));
  const { mode, width, fitted } = workspace;
  if (key === "input-width") {
    return {
      minimum: mode === "wide" ? 180 : 170,
      maximum: Math.min(mode === "wide" ? 480 : 360, width - DIVIDER_WIDTH * (mode === "wide" ? 2 : 1) - (mode === "wide" ? fitted.readout + 320 : 300)),
    };
  }
  return { minimum: 220, maximum: Math.min(640, width - DIVIDER_WIDTH * 2 - fitted.input - 320) };
}

function currentValue(key) {
  return key.endsWith("-height")
    ? workspace.fitted.heights[key.replace("-height", "")]
    : workspace.fitted[key.replace("-width", "")];
}

function saveLayout() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(workspace.preferences));
  } catch {
    workspace.status.textContent = "Layout changed. This browser could not save the layout.";
  }
}

function scheduleLayout(notify = false) {
  if (!workspace) return;
  workspace.notify = workspace.notify || notify;
  if (workspace.animationFrame) return;
  workspace.animationFrame = requestAnimationFrame(() => {
    workspace.animationFrame = 0;
    applyLayout();
  });
}

function applyLayout() {
  if (!workspace?.root.isConnected) return;
  const width = workspace.root.getBoundingClientRect().width;
  if (width <= 0) return;
  workspace.width = width;
  workspace.mode = layoutMode(window.innerWidth);
  workspace.fitted = fitWidths(width, workspace.mode, workspace.preferences);
  workspace.fitted.heights = {};
  workspace.root.dataset.layout = workspace.mode;
  workspace.root.style.setProperty("--workspace-input-width", `${workspace.fitted.input}px`);
  workspace.root.style.setProperty("--workspace-readout-width", `${workspace.fitted.readout}px`);
  for (const [key, requested] of Object.entries(workspace.preferences.heights)) {
    const { minimum, maximum } = heightBounds(key);
    const value = clamp(requested, minimum, maximum);
    workspace.fitted.heights[key] = value;
    workspace.root.style.setProperty(`--workspace-${key}-height`, `${value}px`);
  }
  workspace.handles.forEach((handle, key) => {
    const available = key === "input-width" ? workspace.mode !== "stacked" : key === "readout-width" ? workspace.mode === "wide" : true;
    handle.hidden = !available;
    if (!available) return;
    const { minimum, maximum } = limitsFor(key), value = currentValue(key);
    handle.setAttribute("aria-valuemin", String(minimum));
    handle.setAttribute("aria-valuemax", String(Math.max(minimum, Math.floor(maximum))));
    handle.setAttribute("aria-valuenow", String(value));
    handle.setAttribute("aria-valuetext", `${value} pixels ${key.endsWith("-width") ? "wide" : "high"}`);
  });
  if (workspace.notify) {
    workspace.notify = false;
    // Existing canvases listen for resize; mark this event to avoid recursion here.
    const event = new Event("resize");
    event.workspaceLayoutResize = true;
    window.dispatchEvent(event);
    workspace.root.dispatchEvent(new CustomEvent("workspace:layoutchange", { bubbles: true, detail: { mode: workspace.mode, ...workspace.fitted } }));
  }
}

function setValue(key, requested) {
  const { minimum, maximum } = limitsFor(key);
  const value = clamp(requested, minimum, maximum);
  if (key.endsWith("-height")) workspace.preferences.heights[key.replace("-height", "")] = value;
  else workspace.preferences.widths[workspace.mode][key.replace("-width", "")] = value;
  scheduleLayout(true);
}

function resetDivider(key) {
  const defaults = defaultLayout();
  setValue(key, key.endsWith("-height") ? defaults.heights[key.replace("-height", "")] : defaults.widths[workspace.mode][key.replace("-width", "")]);
  saveLayout();
  workspace.status.textContent = "Pane size reset.";
}

function beginDrag(event, key, handle) {
  if (event.button !== 0 || workspace.drag || handle.hidden) return;
  applyLayout();
  event.preventDefault();
  handle.focus({ preventScroll: true });
  const horizontalMovement = key.endsWith("-width");
  const startPosition = horizontalMovement ? event.clientX : event.clientY;
  const startValue = currentValue(key);
  const startPreferences = structuredClone(workspace.preferences);
  const direction = key === "readout-width" ? -1 : 1;
  workspace.drag = { key, handle, pointerId: event.pointerId };
  handle.classList.add("is-resizing");
  document.body.classList.add("workspace-resizing");
  document.body.style.setProperty("--workspace-resize-cursor", horizontalMovement ? "col-resize" : "row-resize");
  try { handle.setPointerCapture(event.pointerId); } catch {}

  const move = (moveEvent) => {
    if (moveEvent.pointerId !== event.pointerId) return;
    const position = horizontalMovement ? moveEvent.clientX : moveEvent.clientY;
    setValue(key, startValue + (position - startPosition) * direction);
  };
  const finish = (finishEvent, cancelled = false) => {
    if (finishEvent?.pointerId !== undefined && finishEvent.pointerId !== event.pointerId) return;
    if (!workspace.drag) return;
    workspace.drag = null;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", finish);
    window.removeEventListener("pointercancel", cancel);
    window.removeEventListener("blur", finish);
    window.removeEventListener("keydown", escape);
    handle.removeEventListener("lostpointercapture", finish);
    handle.classList.remove("is-resizing");
    document.body.classList.remove("workspace-resizing");
    document.body.style.removeProperty("--workspace-resize-cursor");
    if (cancelled) workspace.preferences = startPreferences;
    try { if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId); } catch {}
    scheduleLayout(true);
    if (!cancelled) saveLayout();
  };
  const cancel = (cancelEvent) => finish(cancelEvent, true);
  const escape = (keyEvent) => {
    if (keyEvent.key !== "Escape") return;
    keyEvent.preventDefault();
    finish(null, true);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", finish);
  window.addEventListener("pointercancel", cancel);
  window.addEventListener("blur", finish);
  window.addEventListener("keydown", escape);
  handle.addEventListener("lostpointercapture", finish);
}

function separatorKeydown(event, key) {
  if (event.altKey || event.ctrlKey || event.metaKey || workspace.drag) return;
  const width = key.endsWith("-width");
  if (!workspace.fitted || (width && workspace.mode === "stacked")) return;
  const step = event.shiftKey ? 40 : 10;
  const direction = key === "readout-width" ? -1 : 1;
  let requested;
  if (event.key === "Enter") {
    event.preventDefault();
    resetDivider(key);
    return;
  }
  if (event.key === "Home") requested = limitsFor(key).minimum;
  else if (event.key === "End") requested = limitsFor(key).maximum;
  else if (event.key === (width ? "ArrowLeft" : "ArrowUp")) requested = currentValue(key) - step * direction;
  else if (event.key === (width ? "ArrowRight" : "ArrowDown")) requested = currentValue(key) + step * direction;
  else return;
  event.preventDefault();
  setValue(key, requested);
  // Keep repeated arrow events cumulative even before the next animation frame.
  applyLayout();
  saveLayout();
}

function createSeparator(key, label, controls) {
  const element = document.createElement("div");
  const width = key.endsWith("-width");
  element.className = `workspace-splitter ${width ? "workspace-width-splitter" : "workspace-height-splitter"}`;
  element.dataset.resize = key;
  element.tabIndex = 0;
  element.setAttribute("role", "separator");
  element.setAttribute("aria-label", label);
  element.setAttribute("aria-orientation", width ? "vertical" : "horizontal");
  element.setAttribute("aria-controls", controls);
  element.setAttribute("aria-describedby", "workspace-resize-help");
  element.title = `${label}. Drag or use ${width ? "Left/Right" : "Up/Down"} arrows; Shift changes 40 pixels. Home/End set limits. Double-click or Enter resets.`;
  element.addEventListener("pointerdown", (event) => beginDrag(event, key, element));
  element.addEventListener("keydown", (event) => separatorKeydown(event, key));
  element.addEventListener("dblclick", () => resetDivider(key));
  workspace.handles.set(key, element);
  return element;
}

function wrapPane(pane, key, label) {
  const shell = document.createElement("div");
  shell.className = `workspace-pane-shell workspace-${key}-shell`;
  if (!pane.id) pane.id = `workspace-${key}-pane`;
  pane.before(shell);
  shell.append(pane, createSeparator(`${key}-height`, `${label} height`, key === "brain" ? "brain-stage" : pane.id));
  return shell;
}

export function resetLayout() {
  if (!workspace) return;
  workspace.preferences = defaultLayout();
  scheduleLayout(true);
  saveLayout();
  workspace.status.textContent = "All pane sizes reset to the default layout.";
}

export function initializeWorkspace() {
  if (workspace) return;
  const root = document.querySelector("#experiment-view");
  const input = root?.querySelector(".stimulus-panel");
  const brain = root?.querySelector(".brain-panel");
  const readout = root?.querySelector(".readout-panel");
  if (!root || !input || !brain || !readout) return;
  workspace = { root, preferences: restoredLayout(), handles: new Map(), fitted: null, mode: layoutMode(window.innerWidth), width: 0, animationFrame: 0, notify: false, drag: null };
  root.dataset.layout = workspace.mode;
  root.classList.add("workspace-resizable");

  const toolbar = document.createElement("div");
  toolbar.className = "workspace-layout-toolbar";
  const help = document.createElement("span");
  help.id = "workspace-resize-help";
  help.textContent = "Drag pane dividers to resize. Arrow keys adjust a focused divider; double-click resets it.";
  const reset = document.createElement("button");
  reset.id = "reset-workspace-layout";
  reset.type = "button";
  reset.textContent = "Reset layout";
  reset.addEventListener("click", resetLayout);
  const status = document.createElement("span");
  status.className = "workspace-layout-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  toolbar.append(help, reset, status);
  workspace.status = status;
  root.prepend(toolbar);

  const inputShell = wrapPane(input, "input", "Simulation pane");
  const brainShell = wrapPane(brain, "brain", "Neural view");
  const readoutShell = wrapPane(readout, "readout", "Measurements pane");
  const flyPanel = root.querySelector("#whole-fly-panel");
  if (flyPanel) readoutShell.append(flyPanel);
  inputShell.after(createSeparator("input-width", "Simulation pane width", input.id));
  brainShell.after(createSeparator("readout-width", "Measurements pane width", readout.id));

  window.addEventListener("resize", (event) => {
    if (!event.workspaceLayoutResize) scheduleLayout(true);
  });
  document.addEventListener("fullscreenchange", () => scheduleLayout(true));
  let observedWidth = -1;
  workspace.resizeObserver = new ResizeObserver((entries) => {
    const width = entries[0]?.contentRect.width || 0;
    if (Math.abs(width - observedWidth) < 0.5) return;
    observedWidth = width;
    scheduleLayout(true);
  });
  workspace.resizeObserver.observe(root);
  workspace.visibilityObserver = new MutationObserver(() => scheduleLayout(true));
  workspace.visibilityObserver.observe(root, { attributes: true, attributeFilter: ["hidden"] });
  scheduleLayout(true);
}
