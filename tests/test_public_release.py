"""Public-export boundaries and generated public URL checks."""
import importlib.util
import json
from pathlib import Path
import re
import pytest

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


def test_export_rejects_cognesia_credentials_without_echoing(tmp_path):
    audit = module('prepare_public_release').audit_file
    path = tmp_path / 'file'
    for prefix in ('cgk_', 'cgc_'):
        token = prefix + 'A' * 43
        path.write_text(token)
        issues = audit(Path('notes.txt'), path)
        assert issues and token not in str(issues)


def test_export_rejects_customer_api_keys_without_echoing(tmp_path):
    path = tmp_path / 'file'
    token = 'cgnk_' + 'a' * 32 + '.' + 'B' * 43
    path.write_text(token)
    issues = module('prepare_public_release').audit_file(Path('notes.txt'), path)
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
    assert (tmp_path / 'app.js').is_file()
    assert "frame-ancestors 'none'" in (tmp_path / 'security-headers.conf').read_text()


def test_static_page_has_no_credentials_or_gateway_assets(tmp_path):
    builder = module('build_public_site')
    # Reusing a local preview directory must not publish stale account forms.
    builder.build('example/Cognesia', 'https://example.github.io/Cognesia', output=tmp_path)
    for name in ('account.html', 'account.js', 'account.css'):
        (tmp_path / name).write_text('stale account asset')
    builder.build('example/Cognesia', 'https://example.github.io/Cognesia', output=tmp_path, mode='static')
    page = (tmp_path / 'index.html').read_text()
    assert '@@' not in page
    assert '<form' not in page
    assert 'Get API access' not in page
    assert 'Public account signup and hosted simulations are not available' in page
    assert 'https://github.com/example/Cognesia/releases/tag/v' in page
    assert 'Content-Security-Policy' in page
    assert 'connect-src &#x27;none&#x27;' in page
    assert 'form-action &#x27;none&#x27;' in page
    assert {p.name for p in tmp_path.iterdir()} == {
        'index.html', 'app.js', 'style.css', 'icon.svg', 'sitemap.xml', '.nojekyll',
    }


def test_static_accounts_entry_requires_explicit_https_portal(tmp_path):
    builder = module('build_public_site')
    for origin in ['http://accounts.example', 'https://user:password@accounts.example',
                   'https://accounts.example/?key=secret', 'https://accounts.example/other', 'https://localhost']:
        with pytest.raises(ValueError):
            builder.build('example/Cognesia', 'https://example.github.io/Cognesia', output=tmp_path,
                          mode='static', accounts_url=origin)
    builder.build('example/Cognesia', 'https://example.github.io/Cognesia', output=tmp_path,
                  mode='static', accounts_url='https://accounts.example')
    page = (tmp_path / 'index.html').read_text()
    assert 'href="https://accounts.example/"' in page
    assert 'Sign up or sign in' in page
    assert 'Public account signup and hosted simulations are not available' not in page
    assert '<form' not in page and '@@' not in page
