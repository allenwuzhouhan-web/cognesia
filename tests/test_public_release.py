"""Public-export boundaries and generated public URL checks."""
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_export_rejects_sensitive_paths_even_if_tracked(tmp_path):
    audit = module('prepare_public_release').audit_file
    path = tmp_path / 'file'
    path.write_text('ordinary content')
    assert audit(Path('sessions/private.json'), path)
    assert audit(Path('.env.production'), path)
    assert audit(Path('credentials.json'), path)
    assert not audit(Path('src/example.py'), path)


def test_export_rejects_credentials_without_echoing_value(tmp_path):
    audit = module('prepare_public_release').audit_file
    path = tmp_path / 'file'
    token = 'ghp_' + 'A' * 36
    path.write_text(token)
    issues = audit(Path('config.txt'), path)
    assert issues and token not in str(issues)


def test_export_rejects_symlinks(tmp_path):
    source = tmp_path / 'source'
    source.write_text('private')
    link = tmp_path / 'link'
    link.symlink_to(source)
    assert 'symlink requires explicit review' in module('prepare_public_release').audit_file(Path('link'), link)


def test_page_uses_real_project_subpath_and_version(tmp_path):
    module('build_public_site').build('example/Cognesia', 'https://example.github.io/Cognesia', output=tmp_path)
    page = (tmp_path / 'index.html').read_text()
    assert '@@' not in page
    assert '<link rel="canonical" href="https://example.github.io/Cognesia/">' in page
    metadata = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page).group(1))
    assert metadata['codeRepository'] == 'https://github.com/example/Cognesia'
    assert metadata['name'] == 'Cognesia'
    assert '<loc>https://example.github.io/Cognesia/</loc>' in (tmp_path / 'sitemap.xml').read_text()
    assert (tmp_path / 'style.css').is_file()
    assert (tmp_path / 'icon.svg').is_file()
