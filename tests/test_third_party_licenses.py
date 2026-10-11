"""Verify license acquisition and, when supplied, an actual built wheel."""
import hashlib
import io
import json
import os
from pathlib import Path
import zipfile

import pytest

from flybrain import fetch as acquisition


ROOT = Path(__file__).resolve().parents[1]
LICENSE_RELATIVE = Path("src/flybrain/licenses/shiu-drosophila-brain-model-LICENSE.txt")
UPSTREAM_LICENSE_SHA256 = "3621f6d6476189190e2960fa43f11b275ba4eca848fdac50a1ba2925de6223e8"


def prepare_cached_reference(tmp_path, monkeypatch):
    raw, build = tmp_path / "data/raw", tmp_path / "build"
    raw.mkdir(parents=True)
    build.mkdir()
    cached = {"model.py": b"# already acquired reference fixture\n",
              "zenodo_record_10676866.json": b'{"files": []}\n'}
    previous = {}
    for name, content in cached.items():
        (raw / name).write_bytes(content)
        previous[name] = {"sha256": hashlib.sha256(content).hexdigest()}
    (build / "downloads.json").write_text(json.dumps({"files": previous}))
    monkeypatch.setattr(acquisition, "SOURCES", {
        acquisition.SHIU_LICENSE_NAME: acquisition.SHIU_LICENSE_URL,
        **{name: "https://example.invalid/" + name for name in cached},
    })
    monkeypatch.setattr(acquisition, "check_memory", lambda: None)
    return raw, build, cached


def test_bundled_shiu_license_preserves_exact_upstream_bytes():
    content = (ROOT / LICENSE_RELATIVE).read_bytes()
    assert hashlib.sha256(content).hexdigest() == UPSTREAM_LICENSE_SHA256
    assert b"Copyright (c) 2023 Philip Shiu and Nico Spiller" in content


def test_fetch_adds_license_to_existing_reference_and_preserves_cache(tmp_path, monkeypatch):
    raw, build, cached = prepare_cached_reference(tmp_path, monkeypatch)
    calls = []

    def open_license(request, *, timeout):
        assert request.full_url == acquisition.SHIU_LICENSE_URL
        calls.append(request.full_url)
        return io.BytesIO((ROOT / LICENSE_RELATIVE).read_bytes())

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", open_license)
    for _ in range(2):
        records = acquisition.fetch(tmp_path, neuropils=False)
        assert (raw / acquisition.SHIU_LICENSE_NAME).read_bytes() == (ROOT / LICENSE_RELATIVE).read_bytes()
        assert records[acquisition.SHIU_LICENSE_NAME]["publisher_checksum"] == "sha256:" + UPSTREAM_LICENSE_SHA256
        assert records[acquisition.SHIU_LICENSE_NAME]["url"] == acquisition.SHIU_LICENSE_URL
        for name, content in cached.items():
            assert (raw / name).read_bytes() == content
            assert records[name]["sha256"] == hashlib.sha256(content).hexdigest()
    assert calls == [acquisition.SHIU_LICENSE_URL]
    assert set(json.loads((build / "downloads.json").read_text())["files"]) == set(cached) | {acquisition.SHIU_LICENSE_NAME}


@pytest.mark.parametrize("preexisting", [False, True])
def test_fetch_rejects_modified_license_without_overwriting_it(tmp_path, monkeypatch, preexisting):
    raw, build, cached = prepare_cached_reference(tmp_path, monkeypatch)
    original = (ROOT / LICENSE_RELATIVE).read_bytes()
    changed = original.replace(b"2023", b"2024")  # Same length, different attribution.
    target = raw / acquisition.SHIU_LICENSE_NAME
    if preexisting:
        target.write_bytes(changed)

    def open_license(request, *, timeout):
        assert not preexisting, "An existing license must never be silently replaced"
        assert request.full_url == acquisition.SHIU_LICENSE_URL
        return io.BytesIO(changed)

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", open_license)
    before_manifest = (build / "downloads.json").read_bytes()
    with pytest.raises(ValueError, match="Publisher checksum failed"):
        acquisition.fetch(tmp_path, neuropils=False)
    if preexisting:
        assert target.read_bytes() == changed
    else:
        assert not target.exists()
    assert not target.with_suffix(target.suffix + ".part").exists()
    assert (build / "downloads.json").read_bytes() == before_manifest
    failure = json.loads((build / "integrity_failures.json").read_text())[acquisition.SHIU_LICENSE_NAME]
    assert failure["observed_sha256"] == (hashlib.sha256(changed).hexdigest() if preexisting else None)
    for name, content in cached.items():
        assert (raw / name).read_bytes() == content


def test_built_wheel_retains_licenses_and_notices():
    """Run with COGNESIA_LICENSE_WHEEL set to the freshly built wheel path."""
    wheel_path = os.environ.get("COGNESIA_LICENSE_WHEEL")
    if not wheel_path:
        pytest.skip("Set COGNESIA_LICENSE_WHEEL to verify an actual freshly built wheel")
    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())
        metadata_name, = [name for name in names if name.endswith(".dist-info/METADATA")]
        dist_info = metadata_name.rsplit("/", 1)[0]
        metadata = wheel.read(metadata_name).decode()
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            assert wheel.read(f"{dist_info}/licenses/{name}") == (ROOT / name).read_bytes()
            assert f"License-File: {name}\n" in metadata
        for relative in (
            LICENSE_RELATIVE,
            Path("src/flybrain/licenses/README.md"),
            Path("src/flybrain/web/vendor/THREE-LICENSE.txt"),
            Path("src/flybrain/web/assets/fly/LICENSE-APACHE-2.0.txt"),
            Path("src/flybrain/web/assets/fly/SOURCE-NOTICE.txt"),
            Path("src/flybrain/web/assets/fly/NOTICE.md"),
        ):
            assert wheel.read(relative.relative_to("src").as_posix()) == (ROOT / relative).read_bytes()
        assert not any("data/raw/" in name for name in names)
