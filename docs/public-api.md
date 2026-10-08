# Cognesia API access

## Customer website and individual keys

The customer website now presents Cognesia's capabilities and includes an API
console. Each customer receives a separately generated 256-bit API access key,
with expiry, permissions, revocation and an explicitly dedicated workspace.
These bearer API keys are not WebAuthn passkeys. There is no paywall.

See [Customer website and key administration](customer-website.md) for setup,
commands, security boundaries and the public HTTPS deployment steps. Production
mode requires customer keys; it refuses the local shared-password mode below.
Website construction and local verification do not establish public deployment.

## Local owner password mode

Cognesia keeps its existing local GUI and adds a password-protected tool API.
There is no payment requirement or per-session tool allowance. Everyone who knows
an instance's password deliberately shares that instance's selected Cognesia
workspace, including its saved experiments, recordings, checkpoints and controls.

This is a private research gateway, not an isolation boundary between people
sharing its password. To keep different researchers' data separate, run separate
gateway instances with distinct passwords, state files, backend ports and
workspace roots. The local owner-mode research agent may also use the same tool
adapter directly against the loopback GUI without starting this gateway.

## Create the password and start the API

Generate the password once. Both output files are created with mode 0600; neither
may already exist. The command prints no password or hash.

```sh
.venv/bin/python -m flybrain.public_api \
  --password-file build/private/api-password-hash.json \
  init-password --output build/private/api-password.json
```

`build/private/api-password.json` contains the generated 256-bit password; keep it
private and enter it in the research agent's API password field. The service reads
only `build/private/api-password-hash.json`, a random-salt scrypt verifier
(N=32768, r=8, p=1, 32-byte output). It never stores the plaintext password in its
SQLite state. These files live inside the existing ignored `build/` directory.
Keep the password output securely: the service cannot recover it from its verifier.

With the normal Cognesia GUI running on port 8794:

```sh
.venv/bin/python -m flybrain.public_api \
  --password-file build/private/api-password-hash.json \
  --state-file build/private/tool-gateway.sqlite3 \
  serve --backend http://127.0.0.1:8794 --port 8796
```

The selected backend is explicit and cannot be changed by a tool caller. The API
binds to `127.0.0.1:8796`; its CLI has no public-bind option. The GUI remains at
`127.0.0.1:8794`. For an intentional password change, generate a new pair under new
filenames and restart the gateway with the new verifier; never overwrite a live
credential file blindly. A running gateway loads its verifier at startup.

The state file is a fresh, dedicated tool replay cache. The gateway rejects a
file containing an unrelated database schema. Existing private archives from
previous configurations are preserved and are not loaded automatically.

## HTTP contract

Use `Authorization: Bearer <credential>` for every route except health. The
credential is an individual customer API key in customer mode, or the local
workspace password in owner mode. Customer discovery returns only tools allowed
by the key's scopes; unknown, expired and revoked keys receive the same 401 error.
Tool calls require `Content-Type: application/json` and an `Idempotency-Key`
containing 16–160 letters, digits, hyphens or underscores. Generate a fresh UUID
for each distinct operation and keep the same key when retrying that operation.

| Route | Request / result | Access |
|---|---|---|
| `GET /health` | Service, API version, `authentication:"password"`, `billing:false` | Public metadata only |
| `GET /v1/access` | `{authenticated:true,workspace:"shared_private",billing:false}` | Password |
| `GET /v1/tools` | `{tools:[...]}` in OpenAI Chat Completions function format | Password |
| `POST /v1/tools/call` | `{name,arguments}` → `{result}` | Password + idempotency |

Example request body:

```json
{
  "name": "cognesia_start",
  "arguments": {
    "options": {
      "stimulus": "dark",
      "duration_ms": 300,
      "neural_overrides": {"seed": 42}
    }
  }
}
```

The result contains the native experiment `id`. Read it with
`cognesia_session` using `{"experiment_id":"..."}`. Request a graceful stop with
`cognesia_command` using
`{"experiment_id":"...","command":{"action":"stop"}}`. A step command uses
`duration_ms`, up to 100 ms and aligned to the native integration quantum.

The same idempotency key and identical arguments return the saved result for
24 hours, without executing the tool again. A key reused for different arguments
returns 409. An in-flight retry also returns 409. After a restart during execution,
the gateway retains an unknown-outcome result and never redispatches that key;
inspect the native experiment before attempting another mutation. This is
**at-most-once dispatch**, not a guarantee that a remote simulation completed.

After 24 hours, cached result bodies become small 410 tombstones. Old keys still
never execute again; use a fresh read call to inspect the recording. State must
remain intact to preserve these guarantees. Do not delete it while clients might
retry old requests.

401 indicates a missing, invalid, expired or revoked credential; 403 indicates a
forbidden host, origin, permission or operator-only tool; 409 indicates an idempotency conflict/in-flight
operation; 410 indicates an expired cached response; 429 indicates request,
authentication, concurrency or result-cache capacity. Native scientific validation
errors remain visible. There are no account, checkout or quota-management routes.

## Tools and scientific controls

`src/flybrain/api_tools.py` supplies the 36 function schemas and explicit routing.
The existing viewer validates native options, and its failed biological gates,
clamp counts, modeled/measured distinctions and source provenance remain visible.
No tool accepts arbitrary external URLs, filesystem paths or shell commands.

| Capability | Tools |
|---|---|
| Lab options, limits and scientific gates | `cognesia_bootstrap` |
| Model versions and provenance | `cognesia_models`, `cognesia_model` |
| Evidence-tagged chemical messengers | `cognesia_messengers` |
| Worker resources | `cognesia_resources` |
| Neuron, region, eye and peripheral inspection | `cognesia_neuron`, `cognesia_region`, `cognesia_eyes`, `cognesia_peripheral` |
| Connectivity and selection estimates | `cognesia_connectivity`, `cognesia_preview` |
| In-memory protocol imports | `cognesia_import_protocol` |
| Reproducible replicate drafts | `cognesia_plan_replicates` |
| Simulations, overrides, chemistry, interventions, timelines and recording | `cognesia_start` |
| Experiment status, frames and controls | `cognesia_sessions`, `cognesia_session`, `cognesia_frame`, `cognesia_command`, `cognesia_cancel` |
| Checkpoints and branch drafts | `cognesia_checkpoints`, `cognesia_branch` |
| Recordings and recorded evidence | `cognesia_runs`, `cognesia_run_summary` |
| Compact paper evidence and data-backed chart snapshots | `cognesia_report_data`, `cognesia_capture_figure` |
| Recorded interval analysis | `cognesia_analyze_interval` |
| Portable workspace archives | `cognesia_save_workspace`, `cognesia_read_asset` |
| Morphology | `cognesia_morphology_status`, `cognesia_morphology_neuron`, `cognesia_morphology_overview` |
| Model preparation | `cognesia_prepare_model`, `cognesia_prepare_morphology`, `cognesia_model_job` |
| Stop all jobs and derived-cache maintenance | `cognesia_stop_all`, `cognesia_clear_cache` |

`cognesia_report_data` returns active stimulus options, explicit units, recorded
control and co-interventions, source identity, sample counts, warnings and trace
names. `cognesia_capture_figure` takes `run_id`, `group` (`type`, `region`, `class`),
an exact `trace` name, and `series` (`raw`, `baseline`, `delta`). It returns a PNG
as `png_base64` alongside statistics computed from the plotted recording. The
local research console retains image bytes separately and sends the numeric
evidence to GPT-OSS. Its final `cognesia_write_report` call and PDF download are
local console operations, outside the gateway's simulation tool catalog.

Model preparation and cache maintenance are hidden by default. Enable them with
`--allow-operator-tools` only when the instance's password holders should have
those maintenance capabilities. Host hardware consent and compute-profile changes
remain local GUI/operator actions. The gateway does not expose raw viewer pages,
live-reload controls, browser-local layout preferences or WebSocket transport;
`cognesia_frame` polls the latest recorded experiment frame.

`cognesia_read_asset` returns base64 chunks of 1–262,144 bytes with `next_offset`
and `eof`. Its allowed kinds are `run`, `model_anatomy`, `run_anatomy`, `workspace`,
`morphology_neuron` and `morphology_overview`. Read numeric dimensions and types
from run summaries or anatomy metadata. Never infer them from bytes alone.

Replicate drafts do not execute experiments. Seeds currently vary optical ray
sampling in a deterministic engine; they do not create independent animals or
establish biological replication.

## Resource bounds and shared-workspace behavior

There is no paid tool quota. Operational limits protect the selected computer:

- Requests ≤1 MiB; serialized tool results ≤8 MiB; binary chunks ≤256 KiB.
- Four concurrent tool executions; two concurrent password-verification jobs.
- 120 HTTP requests per minute per connecting peer. Reverse proxies need their
  own client limits because the gateway does not trust forwarded IP headers.
- A 64 MiB replay-result cache with atomic worst-case reservations. Full-cache
  requests return 429 before execution; results expire after 24 hours.
- At most 100,000 permanent idempotency records per instance. Operator maintenance
  is required at that ceiling; preserve old state when migrating clients.
- API starts require explicit simulated duration ≤10,000 ms. Native parameter,
  recording and memory constraints still apply. Unbounded legacy protocols use
  the local workbench.
- Each API-started experiment gets a durable 15-minute wall-time lease. Expiry
  requests `cognesia_stop_all` on the selected shared workspace, including paused
  work. Everyone sharing that workspace must understand this stop policy.

The native viewer permits one active simulation. The lease stops work even if the
agent disconnects. A worker that cannot process stop still needs OS supervision;
the optional Linux worker template has a one-hour process lifetime and restarts
it. Hard restarts can interrupt experiments, so inspect saved evidence afterward.
Use this template for a dedicated remote workspace; it is not applied to the
owner's ordinary local GUI by installing the API.

## Planned public HTTPS deployment

**Updated requirement (2026-10-07):** A public website must explain Cognesia's
capabilities and provide API access through individually issued customer keys,
without a paywall. The customer site and authentication are prepared locally;
hosting and a domain have not yet been selected. The local endpoint is not the
final deployment. See the [customer deployment guide](customer-website.md).

The files in `deploy/` are templates, not an active internet deployment. For
remote access, provision a domain, TLS certificate, firewall and dedicated host.
Never send the workspace password over public plaintext HTTP.

1. Install Cognesia in `/opt/cognesia`. Create the `cognesia-api` OS account and a
   private `/var/lib/cognesia-api/` state directory with a filesystem quota.
2. Prepare an explicit workspace and loopback viewer, such as port 18800. For the
   worker template, create OS user `cognesia-worker-18800` and private root
   `/srv/cognesia/workspaces/18800` with the required model data and configuration.
   Apply a total disk quota in addition to the template's per-file size limit.
3. Issue a separate customer key using the customer guide. Keep its verifier
   registry under `/var/lib/cognesia-api/`, owned by `cognesia-api`, mode 0600.
   Transfer the one-time key privately to its intended customer. Each customer
   needs a distinct worker port and dedicated, non-overlapping workspace root.
4. Copy `deploy/.env.example` to `/etc/cognesia/api.env`, mode 0600, and set the
   HTTPS origin. Configure the service's private customer registry and replay
   state. Each credential's immutable registry record selects its own backend.
5. Build and install the static site and its generated security header include
   in `/var/www/cognesia`. Adapt/install the nginx and systemd templates. Nginx
   terminates TLS and adds per-client limits; only the four documented gateway
   routes are forwarded. Website and API share one origin. The raw viewer's
   `/api/` routes and worker ports stay private. The gateway checks Host and
   Origin as well as the customer key; `--production` requires an HTTPS origin.
6. Verify public TLS, invalid/expired/revoked key rejection, customer isolation,
   scopes, tool discovery, a read-only tool, idempotent retries, resource bounds
   and restart recovery before sharing the endpoint. This repository does not
   establish that live hosting is ready.

One gateway process owns each local SQLite state file; a process lock prevents a
second service owner. Back up state using SQLite's backup API, including its WAL
consistently. Do not copy only a live `.sqlite3` file. HTTP access logs are disabled
in the supplied templates; never log Authorization headers or credentials.
