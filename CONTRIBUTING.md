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

**All rights reserved except the scientific, educational and personal-use
permissions in [LICENSE](LICENSE).** You may prepare and submit bug fixes and
other contributions within those permissions without requesting prior approval.
Preserve the required copyright and third-party notices, and submit contributions
under the same grant. Include only material you have the right to contribute.
Bug reports and reproducibility feedback are welcome.
