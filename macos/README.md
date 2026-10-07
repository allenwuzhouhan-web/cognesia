# Cognesia for macOS

The native app opens the existing Cognesia workbench in a dedicated Mac window.
It reconnects to the local server or starts it automatically. No terminal needs
to stay open. A new experiment starts only when you select **Run simulation**.

## Build and install

From the project folder, run:

```sh
.venv/bin/python macos/build_app.py --install
```

The builder uses Apple's Command Line Tools, creates a vector-derived icon at
each required resolution, and signs the app locally. It installs in
`/Applications` when writable, otherwise `~/Applications`. Open **Cognesia** from
Applications or Spotlight. You can drag it from Applications to the Dock.

This is a local desktop installation, not a portable distribution. The bundle
uses this checkout, its `.venv`, its Python runtime, and its existing simulation
data. Keep those files in place. After moving the project, rebuild and reinstall
the app so its project path is updated.

The app automatically follows edits in `cgnsa`: web scripts, styles, HTML and
assets refresh after saving; Python, configuration and protocol edits restart
the server and reconnect the window. Changes are checked every half second and
grouped after a brief quiet period. The footer shows **Live updates enabled** or
explains why an update is waiting. Saved drafts and layout preferences survive
the refresh. Finish editing a focused input to allow the page to refresh.

Running or paused experiments, model builds and morphology preparation defer
updates until they finish or you stop them. An automatic update never starts a
simulation. Invalid Python/YAML/JSON/TOML edits keep the current viewer running
and show the file error; correcting the file resumes updates. If an import or
startup error occurs, the launcher stays available and retries after another
source edit. The `runs`, `data`, `build`, `.venv` and Git directories are excluded
from watching, so generated recordings do not cause restart loops.

This follows the existing installed Python environment; dependency changes may
still require installing dependencies. Native Swift or icon changes require
rebuilding the bundle. **View → Reload Workspace** remains available, and
`flybrain view --no-watch` starts a viewer without automatic updates. When
upgrading an already running older server, restart it once while idle to enable
live updates.

Quitting Cognesia closes its window but leaves the local server and any running
experiment available. The app never stops an existing server on launch or quit.
Saved experiments stay in the project's `runs` directory. Native-window layout
and web preferences are stored separately from those in another browser.

The app's server logs are in `~/Library/Logs/Cognesia`. A server started through
another launcher continues to use that launcher's log destination.

## Native workspace menus

The desktop window uses dark native chrome and macOS menus for the workspace
actions. The browser version retains its web navigation.

| Menu | Actions and shortcuts |
| --- | --- |
| Cognesia | Settings (**⌘,**) |
| File | New Note (**⌘N**), Save Session (**⌘S**), browser/project/log access |
| View | Simulate (**⌘1**), Parameters (**⌘2**), Layout, Settings, Reload (**⌘R**) |
| Simulation | Run (**⇧⌘R**), Pause, Resume, Step, Save Checkpoint, Stop Simulation |
| Simulation | **Stop All — Emergency (⌥⌘.)**, always enabled |

Workspace commands use the same current-state checks as their web controls;
the menu can reflect enabled/disabled states sent by the workspace. Saving or
exporting a file continues through the native Save dialog and preserves an
existing destination until the complete download succeeds.

Emergency Stop All remains available during loading and after a WebKit failure.
If the workspace cannot acknowledge it within two seconds, the app verifies the
local service identity and sends the visualizer's bounded stop request directly.
The result distinguishes a confirmed stop from a request still finishing; a
connection failure does not claim that an experiment stopped. Saved recordings
are preserved. Quitting still leaves the local simulator running.

The main-frame document-start bridge marks trusted loopback pages with
`html.cognesia-desktop` and `window.__COGNESIA_DESKTOP__`. Native menu actions
dispatch a cancelable `cognesia-desktop-command` event on `window` with
`detail.action`. The workspace acknowledges accepted commands synchronously with
`preventDefault()` and reports command availability via
`cognesia-desktop-state`, whose detail is
`{ready: true, enabled: {run: true, pause: false}}`. Native code accepts state
messages only from the configured local service's main frame and known command
names. The bridge is recreated on every document load, including live reloads.

Run the injected-script regressions with:

```sh
node --test macos/test_desktop_bridge.mjs
```

## Artwork

`Tools/GenerateIcon.swift` defines the icon as editable vector geometry: a
Cognesia **C** with a branching neural motif in navy, ivory, and muted green.
There are no gradients. Building exports `Cognesia.svg`, a 1024-pixel PNG, a
preview PNG, and all macOS icon sizes into `build/macos/artwork`.

The application does not change the simulator's equations, scientific status,
or validation results. It provides a native window and launch lifecycle for the
existing experimental model.

## Verification

The Apple-silicon build passed compilation with warnings treated as errors and
strict local code-signature verification. Native app checks covered:

- Reusing the existing server without changing its process.
- Starting a fresh server on an isolated test port and loading the workbench.
- Quitting and reopening the app while leaving the server available.
- Rendering the brain with WebGL and entering/exiting the expanded brain view.
- Exporting an actual 240-sample recorded eye signal through the native Save
  dialog, including keeping the dialog open beyond the page's Blob URL lifetime.
- Generating all ten macOS icon resolutions with transparent corners.

The isolated test server was stopped after verification. No new simulation was
started by these checks.
