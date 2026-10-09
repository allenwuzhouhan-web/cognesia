"""A release may ship a verified HTTPS service without overriding owner setup."""
import json
import pytest
from flybrain import app_access


@pytest.fixture
def default_config(tmp_path, monkeypatch):
    path = tmp_path / 'public_access.json'
    monkeypatch.setattr(app_access, 'PUBLIC_ACCESS_CONFIG', path)
    monkeypatch.delenv('COGNESIA_ACCESS_URL', raising=False)
    monkeypatch.delenv('COGNESIA_ACCESS_ALLOW_LOOPBACK_HTTP', raising=False)
    return path


def test_bundled_origin_is_optional_and_never_allows_plaintext(default_config, tmp_path):
    assert app_access.AppAccess(tmp_path / 'workspace').endpoint is None
    default_config.write_text(json.dumps({'access_url': 'http://127.0.0.1/v1/access'}))
    with pytest.raises(ValueError): app_access.AppAccess(tmp_path / 'other')


def test_release_default_does_not_override_an_explicit_endpoint(default_config, tmp_path, monkeypatch):
    default_config.write_text(json.dumps({'access_url': 'https://accounts.example/v1/access'}))
    assert app_access.AppAccess(tmp_path / 'new').endpoint == 'https://accounts.example/v1/access'
    monkeypatch.setenv('COGNESIA_ACCESS_URL', 'https://owner.example/v1/access')
    assert app_access.AppAccess(tmp_path / 'owner').endpoint == 'https://owner.example/v1/access'
    monkeypatch.setenv('COGNESIA_ACCESS_URL', '')
    assert app_access.AppAccess(tmp_path / 'disabled').endpoint is None


def test_existing_private_configuration_and_explicit_disable_win(default_config, tmp_path):
    default_config.write_text(json.dumps({'access_url': 'https://accounts.example/v1/access'}))
    root = tmp_path / 'workspace'
    private = root / 'build/private/app-access'
    private.mkdir(parents=True)
    config = private / 'config.json'
    config.write_text(json.dumps({'access_url': 'https://owner.example/v1/access'}))
    config.chmod(0o600)
    assert app_access.AppAccess(root).endpoint == 'https://owner.example/v1/access'
    assert app_access.AppAccess(root, endpoint='').endpoint is None
