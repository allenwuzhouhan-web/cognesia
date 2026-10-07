# Cognesia v0.0.1 preparation checks

Checked on 2026-10-07. This records local source-release preparation, not a
published release or new biological validation.

| Check | Result |
| --- | --- |
| Clean source copy, Python tests excluding `integration` and `slow` | 707 passed, 9 deselected in 81.26 seconds |
| Browser modules and native desktop JavaScript bridge | 150 passed |
| Public release tools | 4 tests passed; included in the Python total |
| Python wheel | `flybrain-0.0.1-py3-none-any.whl` built successfully |
| Wheel contents | Version metadata, root license, browser UI, Three.js notice and fly geometry present |
| Package and source version | Both 0.0.1; native bundle reads package version |
| Public documentation links | New relative file links resolve |
| GitHub Actions files | Both workflow files parse as YAML; cloud execution not yet run |
| Static project page | Built with a test repository URL; template substitution, canonical URL, JSON-LD and sitemap checked |
| Local browser preview | Rendered and inspected; Cognesia branding, v0.0.1 and scientific status visible |
| Upload scan | No configured credential-pattern, home-path, forbidden-path or oversized-file findings |
| Historical credential-pattern scan | No configured pattern matches; old Git history is excluded from the upload snapshot regardless |

Python checks ran from a disposable source copy without the working project's
cached datasets, recordings or build artifacts, using the existing Python 3.12
environment. This is not a fresh dependency installation or a new full dataset
acquisition test. No model simulation or scientific validation gate was rerun.
The existing numerical and biological limitations remain unchanged.

Commands:

```sh
python -m pytest -q -m 'not integration and not slow'
node --test tests/test_web_*.mjs macos/test_desktop_bridge.mjs
uv build --wheel --out-dir build/public-release-dist
python scripts/prepare_public_release.py --check
```

A bounded pattern scan cannot establish the absence of every possible secret.
The source export omits `.git`, virtual environments, datasets, recordings,
checkpoints and generated build outputs. The exporter writes a separate file
manifest and archive SHA-256 alongside the clean folder and ZIP.

The project remains local. Repository visibility, GitHub Pages deployment,
v0.0.1 tag/release creation and Google indexing have not been performed or
verified. Follow [publishing instructions](PUBLISHING.md) after choosing the
real GitHub repository.
