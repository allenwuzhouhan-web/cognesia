"""Integration validators write evidence in disposable copies, never the live build."""
import shutil
from pathlib import Path
import pytest


@pytest.fixture
def isolated_validation_root(tmp_path):
    def clone(source):
        source=Path(source)
        root=tmp_path/'validation-workspace'
        root.mkdir()
        for name in ('src','data','runs'):
            if (source/name).exists(): (root/name).symlink_to(source/name,target_is_directory=True)
        shutil.copytree(source/'config',root/'config')
        for path in source.glob('*.md'): shutil.copy2(path,root/path.name)
        (root/'build').mkdir()
        for path in (source/'build').iterdir():
            if path.is_file() and path.suffix!='.zip':
                shutil.copy2(path,root/'build'/path.name)
            elif path.is_dir():
                (root/'build'/path.name).symlink_to(path,target_is_directory=True)
        return root
    return clone
