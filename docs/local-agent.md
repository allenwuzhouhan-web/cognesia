# Cognesia local research agent

The dedicated research console uses the Cognesia workbench's compact charcoal panels and blue controls, with neutral graphite reading surfaces and a subtle grid underlay. It runs GPT-OSS-20B through a local OpenAI-compatible model server, exposes Cognesia's structured tools, and keeps an inspectable trace. It does not use Ollama.

Past chats stay on the left, Run/Stop stays at the top, and **Experiment trace** opens from the bottom dock. Instructions and the paper share a scrolling workspace. Expand **Study settings** beneath the prompt for call and response-token limits; the collapsed row shows the current values. **Model / connection** shows connection status at the foot of the sidebar and opens its own scrolling settings panel. Report text uses the dark app surface; downloaded PDFs retain their document layout.

Model weights are excluded from source releases and are not downloaded automatically by the console. A successful mocked integration test does not demonstrate real-model quality, physical hardware throughput, or biological validity.

## Prepared local installation — 7 October 2026

Open **Open Cognesia Research.command** in this checkout to start the workbench and research console. When the verified model manifest still matches the downloaded file's size and modification time, the launcher also starts the local model. Then select **Connect & verify tools**. **Unload model** stops the console-managed model and releases its memory; it does not stop already submitted Cognesia experiments.

The requested model was downloaded from [ggml-org's GPT-OSS-20B GGUF distribution](https://huggingface.co/ggml-org/gpt-oss-20b-GGUF), revision `ef9b12f2ff56c69cf32153a02784e7a3c88bf524`, and saved locally at `data/models/gpt-oss-20b/gpt-oss-20b-MXFP4.gguf` (12,109,566,624 bytes). Its SHA-256 matches the distributor's published LFS object hash:

```text
27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901
```

The adjacent `.verified.json` records provenance and the full-file hash check. The launcher uses its size/time metadata for subsequent starts, rather than rehashing 12 GB every time; reverify the hash if the file is replaced. The runtime is Homebrew llama.cpp 0.4.1 for macOS arm64, build 10964, commit `b29c606e2`, with a 16,384-token context and four CPU threads.

Real inference passed the structured-tool probe and called `cognesia_resources` once, then correctly reported zero active experiments and the 40 GB simulation budget. The test deliberately exhausted its one-call limit and returned a conclusion. Evidence is saved in `build/gpt-oss-live-verification.json`. This confirms a real model-to-tool round trip; it is not a complex-study benchmark or biological validation. Both the weights and local verification artifacts remain outside Git/source exports.

## Start

From the Cognesia project, start the normal workbench first:

```sh
.venv/bin/flybrain view
```

Then start the dedicated console:

```sh
.venv/bin/python -m flybrain.local_agent --open
```

To prefill the setup panel with installed paths without executing the runtime or loading weights:

```sh
.venv/bin/python -m flybrain.local_agent --open \
  --llama-server /opt/homebrew/bin/llama-server \
  --model-file data/models/gpt-oss-20b/gpt-oss-20b-MXFP4.gguf
```

The console checks only those explicitly supplied paths for file presence and executable permission. It does not scan other folders, download weights, or treat file presence as proof of a complete download or loaded model. Paths stay in the console process and its loopback-only setup UI. Add `--start-model` to deliberately launch those provided paths at console startup; both path arguments are required. Otherwise select **Start local model** when ready.

The workbench uses `http://127.0.0.1:8794`; the agent console uses `http://127.0.0.1:8797`. The console always binds to loopback. `--port`, `--viewer-url`, `--gateway-url`, and `--model-url` configure endpoints. The viewer and model must be local; the public gateway can use HTTPS on a public hostname or local HTTP for development.

## Bring your GPT-OSS-20B model

Use a current [llama.cpp](https://github.com/ggml-org/llama.cpp) build and a GPT-OSS-20B GGUF file from your chosen trusted distribution or conversion. Keep the model's correct Harmony chat template. llama.cpp documents native GPT-OSS/Harmony function calling and requires `--jinja` for the OpenAI-compatible tool interface. [Function-calling documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md).

In **Model / connection → Set up GPT-OSS-20B**, enter the absolute executable and model paths, choose context and CPU thread limits, and select **Start local model**. The console starts that explicitly selected executable with fixed arguments, using loopback binding and no shell. It restricts CORS to local origins and generates a random runtime credential held only in server memory and the child process environment; it never appears in browser state, traces or command-line arguments and is never forwarded to a different endpoint. The model's terminal output remains in the terminal that started the console. Model loading may take time; select **Connect & verify tools** after the server is ready. A console-managed model exits when the console service exits.

Alternatively, start the runtime yourself:

```sh
llama-server --model /path/to/gpt-oss-20b.gguf \
  --host 127.0.0.1 --port 8080 \
  --alias gpt-oss-20b --jinja \
  --ctx-size 16384 --parallel 1 --no-webui \
  --cors-origins localhost --no-cors-credentials
```

Then connect to `http://127.0.0.1:8080/v1`, model ID `gpt-oss-20b`. The server owns tokenization and Harmony formatting; Cognesia sends normal role messages and structured tool calls. The console checks `/v1/models` and performs a harmless structured tool-call probe before allowing studies. Model IDs are server-reported aliases, not cryptographic verification of the downloaded weights. Preserve the distributor's provenance and checksums independently.

Model server flags, model aliases and the `/v1/chat/completions` interface are documented in the [official server reference](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). Do not enable the runtime's built-in agent tools or MCP proxies for this workflow; only Cognesia's tool runner is used.

The default 16,384-token context is a starting point, not a hardware guarantee. Context memory and model weights share resources with simulation; start with short studies and reserve enough memory for both. The managed launcher does not conduct a hardware scan or silently increase the simulation tier. Increase context if the model reports insufficient context for the catalog and results; shorter prompts and smaller result selections also help.

## Local and password-protected access

**My local workbench** uses the same tool catalog and validation directly against your own running workbench. Model preparation and cache maintenance tools are excluded from this autonomous agent mode; use the workbench's explicit controls for those operations.

**Password-protected API** uses your gateway endpoint and its workspace password. Every person with that password shares the operator-configured workspace, including its recordings and experiment controls. The console checks authenticated access and the available tools, then calls those tools directly. There are no accounts, codes, credits, charges, or payment sessions. The study's tool budget is a local execution limit you choose.

The workspace password stays in console-server memory. It is not written to files, browser storage, exported traces, or model messages. Restarting the console forgets it. Changing the gateway endpoint clears the password unless a new password is explicitly supplied for that endpoint. Endpoint results and errors are scrubbed for the known workspace password and managed-model credential before entering the model context or trace.

The managed llama.cpp runtime has a separate random private credential. The workspace password is sent only to the configured API gateway, while the runtime credential stays on the exact model routes owned by the console. The gateway's account-free authentication and password setup are described in the public API guide.

## Studies and evidence

The three templates cover readiness inspection, independent replicates and conservative chemical comparisons. Edit the instructions before starting. The model chooses concrete experiments from the available schemas and observed options. Templates guide the model; they do not guarantee successful experimental design or completion.

New studies default to **Unlimited (∞)** tool calls. There is no call-count or round-count cap in this mode; the model continues until it concludes the task or you select **Stop agent**. Choose **Custom limit** for any positive whole-number cap, including values above 50. The loopback `POST /api/run` API uses `"max_calls": null` (or an omitted `max_calls`) for unlimited, and a positive integer for a custom limit. Token limits per model response, validation errors and service/resource limits still apply.

Tools execute serially. With a custom limit, even if a model returns several calls at once, only calls within the remaining budget are sent; the final research turn receives `tool_choice: none` when that budget is exhausted. A reserved local report step then calls `cognesia_write_report`; it can repair a malformed report once and cannot run experiments. The trace shows each tool's name, arguments, result and any failures; **Export trace** downloads the selected study as JSON.

## Past chats

The **Past chats** sidebar saves each study's instructions, evidence trace, report and chart snapshots on this Mac. Select a chat to reopen its paper or export its trace/PDF; **New chat** opens a separate draft. Browsing an older chat does not change a running study. A new study cannot start while one is active. Native export commands follow the selected chat.

Chats are stored in `sessions/research/` under the project (excluded from Git and public release bundles). `--history-dir` can choose another local folder. Writes use atomic replacement; figures are saved before the study JSON, with private file permissions. Known workspace/runtime credentials are redacted and connection passwords are never persisted. Closing and reopening the service retains completed chats. A chat interrupted by a process restart is marked **Interrupted**; it does not automatically resume inference or experiments. Missing/corrupt files stay in place and produce a visible warning rather than being deleted. If saving fails, export the current trace before closing.

The loopback API exposes saved chats at `GET /api/history/{study_id}`, PDFs at `GET /api/report/{study_id}.pdf`, and figures at `GET /api/studies/{study_id}/figures/{figure_id}.png`. `/api/state` includes compact history summaries. Historical downloads remain available after starting a new study or restarting the service.

## Research papers and PDF export

Every completed conclusion is formatted through the `cognesia_write_report` tool into **Abstract**, **Methodology**, **Data**, **Analysis**, and **Futures**. The app renders large bold headings and a paper preview. Abstract gives the TLDR; Methodology describes methods, controls and experimental units; Data reports observations; Analysis interprets them with uncertainty and failures; Futures proposes specific next tests and conditions for generalization. The app adds counts of simulations submitted and saved recordings inspected, and states that this software study uses zero live organisms. Neurons and repeated time samples do not count as independent experimental bodies.

Use **Download PDF** beside the paper, or **Research → Download Paper PDF…** in the Mac app. The PDF contains the same sections, captured figures, units, source hashes, trace references and recording warnings. The Mac app opens a Save dialog. A malformed or interrupted report is not marked ready: the original findings and trace remain available, and the UI explains why no PDF is ready.

For an older unformatted chat or a failed report, use **Generate paper** / **Retry paper** after connecting the model. This formats the saved evidence without repeating research tool calls or submitting experiments. The CSRF-protected `POST /api/report` endpoint accepts `{"study_id":"..."}` and allows only the report tool. The report writer uses the returned observations, not the unverified free-form conclusion; rejected report fields and correction feedback remain in the trace. A repair is limited to one additional model call.

`cognesia_report_data` reads compact metadata and available trace names from an existing recording. It preserves the recorded control, active co-interventions and explicit units, and omits settings for inactive stimulus types. `cognesia_capture_figure` captures a chart snapshot for one exact population trace (cell type, region or class; experiment, control or experiment-minus-control voltage). It computes mean, range, temporal standard deviation and time integral from all recorded trace samples, while limiting long plots to an envelope of at most 2,000 points. Figure captions identify the recording, time samples and source summary SHA-256. Reports hold up to six figures.

The report call requires explicit experimental design, experimental units, control, interpretation, limitations, next experiments and generalization fields. These render as paragraphs within the five main sections. Schema and reference checks reject incomplete structure and invented evidence IDs; descriptive trace statistics cannot be presented as an established significance test or detection threshold. Generated scientific prose still requires review against the trace and source recording.

GPT-OSS receives the figure's numeric evidence and labels. It does not interpret the PNG pixels, photograph arbitrary screens, or analyze external uploaded images. The chart and statistics come from the same recorded samples; temporal variation is not uncertainty across independent specimens. Existing failed stability and biological gates remain part of the evidence. These are generated research summaries, and the PDF format does not establish publication or biological validity.

As a study grows, older complete tool exchanges roll out of the model's context while the original instructions, recent exchanges and a short archive preview remain. Call/response pairs stay together. The full trace remains saved, including evidence removed from inference context, and long archives can reopen beyond the former 8 MiB history limit. A report receives a bounded selection of recent evidence IDs for citations. Large individual tool results may still be truncated before entering the model; raw scientific recordings remain in Cognesia. Ask for narrower selections or use the API's chunked asset endpoint for complete recordings; a truncated preview is not complete data.

**Stop agent** cancels the current local inference/request and prevents further tool calls. It does not roll back a submitted mutation or guarantee that a running simulation stops. Use **Open workbench** to inspect the experiment and stop it gracefully. The trace explicitly records this boundary. A transport failure is not automatically retried; inspect the workspace before requesting another mutation.

For replicated studies, retain a master seed, replicate indices, distinct per-replicate seeds, full options, run identities and model/config/source provenance. Use matched controls, predeclare outcomes and keep failed or clamped runs in the analysis. Replaying an identical saved checkpoint with the same seed is a technical replay, not an independent replicate or biological replicate. More simulations can improve estimation of variability within this model; they do not resolve the current failed scientific gates.

## Verification

```sh
.venv/bin/python -m pytest -q tests/test_local_agent.py tests/test_research_paper.py tests/test_research_history.py
node --test tests/test_web_agent_report.mjs tests/test_web_agent_history.mjs macos/test_research_bridge.mjs
```

These tests use actual HTTP mock model/gateway servers to exercise multi-round tool execution, evidence returned to the model, password-only access, call limits, cancellation, rate limiting, credential redaction, unsupported templates/models, local-owner tool execution, CSRF and endpoint restrictions, and launcher argument safety. The separate real-model check above applies to this prepared local installation; other machines must verify their own runtime and weights.
