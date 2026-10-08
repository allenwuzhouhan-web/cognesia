# Research papers and saved chats — 2026-10-07

## Implemented

- Reserved `cognesia_write_report` function call with a validated five-section schema: Abstract, Methodology, Data, Analysis, Futures. Experimental design, units, controls, interpretation, limitations and generalization are explicit fields.
- A readable paper view with large bold headings, safe text rendering, captured figures and a downloadable A4 PDF. Native **Research → Download Paper PDF…** uses the Mac Save dialog.
- `cognesia_report_data` and `cognesia_capture_figure`: compact source metadata, exact recorded controls, numeric trace statistics and a PNG made from the same samples. Numeric analysis works with text-only GPT-OSS; arbitrary image interpretation is not implemented.
- A persistent **Past chats** sidebar, **New chat**, independent selection while another study runs, historical trace/PDF/figure exports, restart recovery and credential-redacted atomic local storage.
- **Generate paper / Retry paper** formats a saved chat without repeating research calls. The report writer excludes the unverified free-form conclusion and receives specific correction feedback with a bounded repair attempt.

## Executed checks

Final focused suite: **112 Python tests passed; 10 JavaScript tests passed**.

```sh
.venv/bin/python -m pytest -q tests/test_research_history.py tests/test_research_paper.py tests/test_local_agent.py tests/test_public_api.py tests/test_visual_server.py tests/test_research_agent_launcher.py
node --test tests/test_web_agent_report.mjs tests/test_web_agent_history.mjs macos/test_research_bridge.mjs
```

Tests cover actual HTTP tool/report paths, finite trace statistics and plot reduction, required sections/reference checks, bounded report repair, repeat-free report generation, historical export during an active study, restart recovery, corrupt/missing files, credential redaction, and selected-chat UI/native export behavior.

The native app was built, signed and installed at `/Applications/Cognesia.app`. The live app showed the sidebar, opened the original saved chat during an active study, and opened a fresh draft with concurrent execution disabled. A subsequent real service restart preserved both the original chat and the new report with its figure. The model was reconnected and left ready, with no study running.

## Real-model and PDF evidence

The actual local GPT-OSS-20B inspected existing recording `20261001T024631Z_visual_grating_172a17` and captured its T4a difference trace. It made exactly two read-only research calls; no simulations were submitted. The selected trace contains 1,462 model neurons and 50 time samples. A forced report call produced the five required sections. An unsupported inference was rejected during an earlier attempt; saved evidence was subsequently formatted without repeating those research calls.

The example's generated prose was then reviewed against the returned recording and chart statistics. Review corrected the distinction between positive maximum and maximum absolute magnitude, distinguished a not-executed stability gate from measured failure, clarified units and the shared chemical clamp, and made future controls explicit. The original model report arguments and review note remain in the saved trace. The unreviewed output is preserved locally in `build/report-upgrade/model-generated-unreviewed.json`.

Artifacts:

- `output/pdf/cognesia-research-paper.pdf` — reviewed example, three pages.
- `output/pdf/cognesia-native-download.pdf` — saved through the actual Mac Save dialog.
- `build/report-upgrade/real-model-study.json` — final selected chat and evidence trace.
- `build/report-upgrade/pdf-download-verification.json` — native download text and embedded image match the reviewed example; all five sections present.

Every final PDF page was rendered and visually inspected. No clipping or overlapping body/footer text was observed. Per-download PDF metadata can differ; extracted text and image data match.

These checks establish software operation and export quality. They do not establish biological validation or complete semantic verification of future model prose. The observed prose corrections demonstrate why scientific interpretations still require review. Numerical figures and statistics are source-derived; failed or unexecuted scientific gates remain visible in each report.
