# Contributing to Cognesia

Use the repository's Issues tab for bug reports and proposed improvements.
Include the Cognesia version, operating system, Python version, steps to
reproduce, expected behavior and relevant diagnostics. Remove credentials,
personal notes and private dataset paths before attaching logs or recordings.

For development, install with `python3.12 -m venv .venv` followed by
`.venv/bin/python -m pip install -e '.[test]'`. Run Python tests with
`.venv/bin/python -m pytest` and browser-module checks with
`node --test tests/test_web_*.mjs macos/test_desktop_bridge.mjs` (Node.js 22+).
Data-dependent validation requires separately acquired inputs; a skip is not a
scientific pass. Document the exact tests and inputs used in a pull request.

Keep measured anatomy separate from modeled links. Preserve failed gates and
provenance rather than weakening checks to obtain a passing result. Avoid
committing datasets, sessions, local environments or generated model artifacts.

Original Cognesia code and documentation are **All rights reserved**; see
`LICENSE`. Contact the repository owner about permission before proposing code
contributions. Bug reports and reproducibility feedback are welcome.
