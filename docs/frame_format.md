# Console transport schema 1

The console is a local browser client at `http://127.0.0.1:8795`. One engine thread owns the actual core runtime. HTTP handlers enqueue controls; they do not mutate engine arrays. Snapshot copies are published after complete simulation blocks. The asynchronous bridge samples the latest published snapshot at up to 30 Hz. Slow integration slows model time; frames may be skipped without replacing measurements or changing integration dt. Same-origin localhost checks protect HTTP controls and WebSocket connections.

`/ws` sends a JSON schema message whenever the array layout changes, then binary frames. Every binary frame is little-endian float32:

| Header index | Meaning |
|---:|---|
| 0 | Schema version, 1 |
| 1 | Simulation time, ms |
| 2 | Fast-network integration dt, ms |
| 3 | Measured runtime model seconds / compute wall seconds |
| 4 | Transport frame counter |
| 5 | Number of following float32 values |

JSON layout entries specify each payload field's offset and length. Consumers must use those entries, rather than assuming fixed offsets.

1. Scalars: MBON valence, session KC active fraction, observed minimum/maximum voltage, voltage-bound sample count, spike count, cumulative absolute plastic-weight movement in synapse-count-equivalent units.
2. KC subtype rates, empirical-compartment DAN rates, MBON type rates, flattened species-by-compartment concentrations, mean relative weights per MB compartment, and flattened compartment-by-KC-subtype relative weight heatmap.
3. Actual rates and voltages at 1,200 fixed, evenly spaced core indices. `/api/metadata` supplies `atlas.sample_indices`. Other neurons' instantaneous activity remains unknown. The sample is for display, not a statistical estimator.

Unavailable values use IEEE NaN in binary and null in JSON. Empty empirical compartments render as gaps or hatching. Time and counters use the requested float32 wire format; JSON status retains their original precision. Status JSON normally accompanies a frame twice per second; changed controls, transport status or session identity trigger an earlier status message before its matching binary sample. Static labels, coordinates and provenance come from `/api/metadata`.

HTTP routes:

| Route | Meaning / bounds |
|---|---|
| `GET /api/status` | Latest actual snapshot, including loading/error/paused state. |
| `GET /api/metadata` | Released soma coordinates, type labels, source annotations, fixed activity-sample indices and coverage. |
| `GET /api/evidence` | Rechecks saved evidence against current source/configuration/code signatures, dependencies and artifacts on each request; absence is NOT-RUN. Includes current field-reference fixtures only when V-NM-D remains PASS. |
| `POST /api/control` | `{control_id, value}` at an integer simulation-time boundary. `dan.pulse` accepts 1–60,000 integer simulation ms; retriggering supersedes the pending turnoff. Manual 1 ms steps honor scheduled pulse and protocol boundaries. |
| `POST /api/protocol` | `{yaml}`; valid protocol starts a fresh seeded recording after sealing the prior nonempty session. |
| `GET /api/raster` | `cell_type=all` or an actual KC subtype; `duration_ms` in `(0,5000]`, `end_ms` within recorded time (default current time), `max_points` in `[1,20000]`. |
| `GET /api/weights` | `compartment=all` or an actual MB name, `kc_type=all` or an actual KC subtype, nonnegative `offset`, `limit` in `[1,2000]` (default 200). |
| `GET /api/session` | Seals the current endpoint and downloads its session-specific ZIP. |
| `GET /api/sessions` | Discoverable sealed-session index with duration, seed, configuration identity and reason. |
| `GET /api/sessions/{id}` | Download an indexed archive; arbitrary filesystem paths are not accepted. |

Raster queries run on the engine owner thread, flush spike files, and memory-map the actual sorted int64 base-step and int32 core-index logs. The interval is `[start,end)`. Responses identify core indices and root IDs, give actual event times in ms, and separately report matching, retained and omitted spike counts. Capped queries retain the most recent events. No points are synthesized. Raw weight queries return actual indexed KC→MBON edges, pre/post root IDs, types, compartment, initial/current weights, change and relative weight. Pagination is deterministic core edge order, not random sampling. Query timing and configuration identity accompany each response.

The browser's timeline displays stimulus, KC/DAN/MBON grouped rates, selected-species field, relative weights, valence, energy/hydration, explicit missing body output and recorded controls. Click places a playhead on the nearest actual sample; dragging selects an interval for CSV export. Captioned PNGs are rendered into a separate canvas using the same selected samples and first/last timestamps as the CSV, with seed/configuration identity. The live plot stays unchanged. Before/current/difference learning views preserve absent-edge cells as null. The weight-history plot uses sampled actual weights. The forgetting readout is labelled ASSUMPTION and reports the instantaneous frozen-DA half-life from the configured equation; it is not a measured future prediction.

The WebGL atlas (Canvas fallback on the same coordinates) colors actual sampled rates or voltages, or empirical MB membership. Hover shows known and predicted transmitter annotations and actual sampled activity when present. Field overlays are convex extents of assigned neurons' released soma x/y coordinates, weighted by the selected species' model concentration. They are explicitly labelled schematic membership extents, not anatomical compartment volumes or measured release geometry. Missing or degenerate coordinate sets do not acquire invented hulls.

Before interactive reset or protocol replacement, the bridge exports the prior nonempty session, preserving its numerical endpoint, binary spikes, events, frames, configuration and manifest. The archive remains indexed by its unique session ID. Exported `protocol.yaml` reconstructs the actual model controls as zero-duration generic control blocks and a terminal rest ending at the exact recorded duration. Equal-time event order is retained; wall-clock pause/step/reset commands are transport-only and remain in the authoritative event log. A supplied design is preserved as `requested_protocol.yaml`. Exact replay uses `events.jsonl` plus `session.yaml` and their output digests.

Session playback reads exported ZIP/JSONL frames without a simulation engine and disables live mutations. Per-neuron activity and raw-edge history absent from sampled recording files remain unavailable; complete raw spike logs and endpoint weights remain in the archive. The browser independently integrates the pinned plasticity fixture and the eight unit-source field pulse/decay fixtures against Python exports. These are numerical software checks, not evidence of biological sparseness or learned behaviour.

Recording loads clear the previous snapshot, labels, atlas samples, raster, raw-edge result, selection and live gate evidence. Each playback frame replaces the current snapshot: an omitted field remains unavailable rather than inheriting a prior live or recorded value. Late live HTTP/metadata/query responses are ignored after playback begins. Without recording metadata, cell labels/index mappings remain unknown; without matching saved validation evidence, live gates and reference checks are not attributed to the recording. Write controls are disabled during playback.

CSV/PNG figure exports use `POST /api/exports` to persist the browser-selected content beneath `runs/exports`. Accepted JSON fields are `filename`, `content_type` (`text/csv` or `image/png`), the matching `text` or base64 payload, and optional numerical/session context. Files are limited to 6 MiB; filenames cannot contain path separators. The response gives a persistent same-origin `/api/exports/{name}` download URL, absolute saved path and byte count. A sidecar JSON records the context and identifies this as a presentation artifact. The console displays the saved link even if the embedded browser blocks an automatic download. Static offline playback without the bridge falls back to an attached native blob anchor and explicitly asks the user to verify the browser download; it does not claim server storage succeeded.

Schematic hull overlays are off by default. Their low-opacity fill and outlines can be enabled without hiding the actual sampled rate/voltage points. A frame without voltage-bound diagnostics displays an unavailable note rather than claiming an unclamped trajectory.
