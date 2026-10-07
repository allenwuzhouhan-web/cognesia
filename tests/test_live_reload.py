import os
from pathlib import Path

import pytest

from flybrain.live_reload import ProjectWatcher


@pytest.fixture
def project(tmp_path):
    source = tmp_path / "src" / "flybrain"
    (source / "web").mkdir(parents=True)
    (source / "engine.py").write_text("value = 1\n")
    (source / "web" / "app.js").write_text("const value = 1;\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text("value: 1\n")
    (tmp_path / "protocols").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
    return tmp_path, source


def test_initial_revisions_are_stable_and_poll_uses_stat_cache(project, monkeypatch):
    root, source = project
    first = ProjectWatcher(root, source)
    assert first.snapshot() == ProjectWatcher(root, source).snapshot()

    def no_read(*args, **kwargs):
        pytest.fail("Unchanged files must not be read again")

    monkeypatch.setattr(Path, "read_bytes", no_read)
    assert first.poll(now=0) == first.snapshot()


def test_web_edit_debounces_until_edits_are_quiet(project):
    root, source = project
    watcher = ProjectWatcher(root, source, debounce_seconds=0.5)
    initial = watcher.snapshot()
    script = source / "web" / "app.js"
    script.write_text("const value = 2;\n")
    assert watcher.poll(now=0)["pending"]
    script.write_text("const value = 3;\n")
    assert watcher.poll(now=0.4)["pending"]
    assert watcher.poll(now=0.8)["web_revision"] == initial["web_revision"]
    final = watcher.poll(now=1)
    assert not final["pending"]
    assert final["web_revision"] != initial["web_revision"]
    assert final["backend_revision"] == initial["backend_revision"]
    assert final["changed_paths"] == ["src/flybrain/web/app.js"]


def test_backend_add_delete_and_atomic_replace(project):
    root, source = project
    watcher = ProjectWatcher(root, source, debounce_seconds=0)
    initial = watcher.snapshot()
    module = source / "new_module.py"
    module.write_text("value = 1\n")
    added = watcher.poll(now=0)
    assert added["backend_revision"] != initial["backend_revision"]
    assert added["web_revision"] == initial["web_revision"]
    module.unlink()
    deleted = watcher.poll(now=1)
    assert deleted["backend_revision"] == initial["backend_revision"]
    original = source / "engine.py"
    before = original.stat()
    temporary = source / ".engine.py.tmp"
    temporary.write_text("value = 2\n")
    os.utime(temporary, ns=(before.st_atime_ns, before.st_mtime_ns))
    temporary.replace(original)
    assert watcher.poll(now=2)["backend_revision"] != initial["backend_revision"]


@pytest.mark.parametrize("relative", [
    "data/input.py", "build/result.py", "runs/result.py", ".venv/module.py",
    "src/flybrain/__pycache__/cached.py", "src/flybrain/.hidden/module.py",
    "src/flybrain/web/.app.js", "src/flybrain/web/app.js.tmp",
    "config/draft.yaml~", "config/build/generated.yaml",
])
def test_ignores_outputs_and_editor_temporary_files(project, relative):
    root, source = project
    watcher = ProjectWatcher(root, source, debounce_seconds=0)
    initial = watcher.snapshot()
    ignored = root / relative
    ignored.parent.mkdir(parents=True, exist_ok=True)
    ignored.write_text("invalid syntax here !!!")
    assert watcher.poll(now=1) == initial


def test_invalid_python_preserves_revisions_and_recovers(project):
    root, source = project
    watcher = ProjectWatcher(root, source, debounce_seconds=0)
    initial = watcher.snapshot()
    module = source / "engine.py"
    module.write_text("def broken(:\n")
    (source / "web" / "app.js").write_text("const value = 2;\n")
    invalid = watcher.poll(now=0)
    assert not invalid["pending"]
    assert "src/flybrain/engine.py" in invalid["error"]
    assert invalid["web_revision"] == initial["web_revision"]
    assert invalid["backend_revision"] == initial["backend_revision"]
    assert watcher.poll(now=1) == invalid
    module.write_text("value = 2\n")
    final = watcher.poll(now=2)
    assert final["error"] is None
    assert final["backend_revision"] != initial["backend_revision"]
    assert final["web_revision"] != initial["web_revision"]
    assert not (source / "__pycache__").exists()


def test_initially_invalid_backend_is_reported_and_recovers(project):
    root, source = project
    module = source / "engine.py"
    module.write_text("def broken(:\n")
    watcher = ProjectWatcher(root, source, debounce_seconds=0)
    assert "src/flybrain/engine.py" in watcher.snapshot()["error"]
    assert "src/flybrain/engine.py" in watcher.poll(now=0)["error"]
    module.write_text("value = 1\n")
    assert watcher.poll(now=1)["error"] is None
    fresh = ProjectWatcher(root, source)
    assert watcher.snapshot()["backend_revision"] == fresh.snapshot()["backend_revision"]


@pytest.mark.parametrize("relative,invalid,valid", [
    ("config/settings.yaml", "value: [", "value: [1, 2]\n"),
    ("protocols/test.json", '{"value":', '{"value": 2}'),
    ("pyproject.toml", "[project", '[project]\nname = "changed"\n'),
])
def test_rejects_malformed_configuration_and_recovers(project, relative, invalid, valid):
    root, source = project
    watcher = ProjectWatcher(root, source, debounce_seconds=0)
    initial = watcher.snapshot()
    path = root / relative
    path.write_text(invalid)
    failed = watcher.poll(now=0)
    assert relative in failed["error"]
    assert failed["backend_revision"] == initial["backend_revision"]
    path.write_text(valid)
    recovered = watcher.poll(now=1)
    assert recovered["error"] is None
    assert recovered["backend_revision"] != initial["backend_revision"]


def test_large_web_asset_is_only_statted_and_symlinks_are_ignored(project, monkeypatch):
    root, source = project
    asset = source / "web" / "mesh.glb"
    asset.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    external = root / "data"
    external.mkdir()
    (external / "bad.py").write_text("broken !")
    (source / "linked").symlink_to(external, target_is_directory=True)
    (source / "linked.py").symlink_to(external / "bad.py")
    original_read = Path.read_bytes

    def guarded_read(path):
        assert path != asset
        assert not path.is_relative_to(external)
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    watcher = ProjectWatcher(root, source, debounce_seconds=0)
    initial = watcher.snapshot()
    with asset.open("ab") as stream:
        stream.write(b"y")
    updated = watcher.poll(now=0)
    assert updated["web_revision"] != initial["web_revision"]
    assert updated["backend_revision"] == initial["backend_revision"]


def test_same_content_write_does_not_create_revision_and_revert_cancels_pending(project):
    root, source = project
    watcher = ProjectWatcher(root, source)
    initial = watcher.snapshot()
    module = source / "engine.py"
    module.write_text("value = 1\n")
    assert watcher.poll(now=0) == initial
    module.write_text("value = 2\n")
    assert watcher.poll(now=1)["pending"]
    module.write_text("value = 1\n")
    restored = watcher.poll(now=1.1)
    assert not restored["pending"]
    assert restored["backend_revision"] == initial["backend_revision"]
    assert restored["error"] is None
