"""Standard-library check of publication bindings and byte-identical core."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / "metadata/source-manifest.json").read_text())
    for name, entry in manifest["files"].items():
        path = ROOT / name
        assert path.is_file(), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], name
        assert path.stat().st_size == entry["bytes"], name
    candidate = json.loads((ROOT / "src/paralimbo1/model-manifest.json").read_text())
    payload = {key: value for key, value in candidate.items() if key != "model_hash"}
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    release = json.loads((ROOT / "src/paralimbo1/release.json").read_text())
    assert identity == candidate["model_hash"] == release["model_hash"]
    assert candidate["id"] == release["canonical_model_id"] == "paralimbo-visual-graded-v1"
    assert release["public_name"] == "ParaLimbo 1"
    assert release["study_neural_baseline_sha256"] == manifest["files"]["src/flybrain/neural_baseline.py"]["sha256"]
    assert release["archived_model_compiler_sha256"] == candidate["implementation_hash"]
    assert candidate["runtime_profile"]["graded_input_cap"] == 0.8
    # Confirm no extracted scientific module references an omitted local module.
    for path in (ROOT / "src/flybrain").rglob("*.py"):
        module = list(path.relative_to(ROOT / "src").with_suffix("").parts)
        package = module[:-1]
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                base = package[:len(package) - node.level + 1]
                name = base + ((node.module or "").split(".") if node.module else [])
                target = ROOT / "src" / Path(*name)
                assert target.with_suffix(".py").exists() or (target / "__init__.py").exists(), (path, name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("flybrain."):
                        target = ROOT / "src" / Path(*alias.name.split("."))
                        assert target.with_suffix(".py").exists() or (target / "__init__.py").exists()
    print(json.dumps({"status": "PASS", "byte_identical_files": len(manifest["files"]),
                      "model_hash": identity, "local_import_closure": "PASS"}, indent=2))


if __name__ == "__main__":
    main()
