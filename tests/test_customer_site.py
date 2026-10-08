"""Exercise public asset and credential forwarding boundaries over real HTTP."""
import asyncio
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from flybrain.customer_site import create_app


def website(tmp_path):
    (tmp_path / 'index.html').write_text('<!doctype html><title>Cognesia</title><script type="application/ld+json">{"name":"Cognesia"}</script>')
    (tmp_path / 'app.js').write_text('"use strict";')
    (tmp_path / 'style.css').write_text('body { color: white; }')
    return tmp_path


def test_preview_allowlists_assets_and_rejects_rebinding_and_cross_origin(tmp_path):
    directory = website(tmp_path)
    (directory / 'security-headers.conf').write_text('not a public asset')
    (directory / 'private.json').write_text('private value')
    (directory / 'icon.svg').symlink_to(directory / 'private.json')

    async def run():
        async with TestClient(TestServer(create_app(directory))) as client:
            response = await client.get('/')
            assert response.status == 200 and '<title>Cognesia</title>' in await response.text()
            assert "'sha256-" in response.headers['Content-Security-Policy']
            assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
            assert response.headers['Cache-Control'] == 'no-store'
            assert response.headers['Referrer-Policy'] == 'no-referrer'
            for path in ('/private.json', '/security-headers.conf', '/api/bootstrap', '/ws/', '/icon.svg', '/build/private/api-password.json'):
                response = await client.get(path)
                assert response.status == 404
                assert 'private value' not in await response.text()
            assert (await client.get('/', headers={'Host': 'attacker.example'})).status == 403
            assert (await client.get('/v1/access', headers={'Origin': 'https://attacker.example'})).status == 403
            assert (await client.get('/v1/access?key=wrong')).status == 400
            assert (await client.options('/v1/tools/call')).status == 405
    asyncio.run(run())


def test_preview_proxies_only_explicit_headers_json_routes_and_never_follows_redirects(tmp_path):
    directory = website(tmp_path)
    seen = []
    async def gateway(request):
        seen.append((request.path, dict(request.headers), await request.read()))
        if request.path == '/health':
            raise web.HTTPFound('/steal-key')
        return web.json_response({'authenticated': True})

    async def run():
        upstream = web.Application()
        upstream.router.add_route('*', '/{tail:.*}', gateway)
        async with TestServer(upstream) as server:
            async with TestClient(TestServer(create_app(directory, str(server.make_url('/')).rstrip('/')))) as client:
                response = await client.get('/v1/access', headers={
                    'Authorization': 'Bearer test-only-value', 'Cookie': 'must-not-forward=yes',
                    'X-Forwarded-For': 'must-not-trust',
                })
                assert response.status == 200
                assert seen[-1][1]['Authorization'] == 'Bearer test-only-value'
                assert 'Cookie' not in seen[-1][1] and 'X-Forwarded-For' not in seen[-1][1]
                response = await client.post('/v1/tools/call', json={'name': 'cognesia_models', 'arguments': {}},
                                             headers={'Idempotency-Key': 'distinct-call-example'})
                assert response.status == 200
                assert seen[-1][1]['Idempotency-Key'] == 'distinct-call-example'
                assert (await client.post('/v1/tools/call', data='not JSON')).status == 415
                assert (await client.get('/health')).status == 502
                assert '/steal-key' not in [item[0] for item in seen]
                assert (await client.post('/v1/tools/call', data=b'x' * (1024 * 1024 + 1),
                                           headers={'Content-Type': 'application/json'})).status == 413
    asyncio.run(run())


def test_preview_rejects_remote_gateway_and_unbuilt_template(tmp_path):
    directory = website(tmp_path)
    with pytest.raises(ValueError):
        create_app(directory, 'https://attacker.example')
    (directory / 'index.html').write_text('@@SITE_URL@@')
    with pytest.raises(ValueError, match='Build the site'):
        create_app(directory)
