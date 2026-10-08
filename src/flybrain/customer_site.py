"""Loopback-only preview of the Cognesia customer site and same-origin API.

Use nginx and TLS for public hosting. This development server exposes only an
explicit set of built website assets and four gateway routes, never the viewer.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
from pathlib import Path
import re
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web

from .api_tools import validate_backend_url

ASSETS = {
    '/': ('index.html', 'text/html'),
    '/index.html': ('index.html', 'text/html'),
    '/style.css': ('style.css', 'text/css'),
    '/app.js': ('app.js', 'text/javascript'),
    '/icon.svg': ('icon.svg', 'image/svg+xml'),
    '/sitemap.xml': ('sitemap.xml', 'application/xml'),
}
API_ROUTES = {'/health': 'GET', '/v1/access': 'GET', '/v1/tools': 'GET', '/v1/tools/call': 'POST'}
MAX_RESPONSE = 8 * 1024 * 1024
CLIENT = web.AppKey('gateway_client', aiohttp.ClientSession)


def site_policy(page):
    hashes = ["'sha256-" + base64.b64encode(hashlib.sha256(value.encode()).digest()).decode() + "'"
              for value in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)]
    return ("default-src 'none'; script-src 'self' " + ' '.join(hashes) +
            "; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'")


def create_app(site_dir, gateway_url='http://127.0.0.1:8798'):
    directory = Path(site_dir).resolve(strict=True)
    gateway = validate_backend_url(gateway_url)
    page = (directory / 'index.html').read_text()
    if '@@' in page:
        raise ValueError('Build the site before previewing it')
    policy = site_policy(page)

    @web.middleware
    async def boundary(request, handler):
        try:
            address = request.transport.get_extra_info('sockname') if request.transport else None
            port = address[1] if address else None
            hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
            if request.host not in hosts:
                raise web.HTTPForbidden(reason='Unexpected preview host')
            origin = request.headers.get('Origin')
            if origin and origin != 'http://' + request.host:
                raise web.HTTPForbidden(reason='Cross-origin access is forbidden')
            if request.query_string:
                raise web.HTTPBadRequest(reason='Query parameters are not accepted')
            response = await handler(request)
        except web.HTTPException as error:
            response = web.json_response({'error': {'code': 'http_error', 'message': error.reason}}, status=error.status)
        response.headers.update({
            'Content-Security-Policy': policy,
            'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY', 'Cache-Control': 'no-store',
            'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
        })
        return response

    app = web.Application(client_max_size=1024 * 1024, middlewares=[boundary])

    async def startup(app):
        app[CLIENT] = aiohttp.ClientSession(trust_env=False, cookie_jar=aiohttp.DummyCookieJar(),
                                         timeout=aiohttp.ClientTimeout(total=65))

    async def cleanup(app):
        await app[CLIENT].close()

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)

    async def static(request):
        filename, mime = ASSETS[request.path]
        path = directory / filename
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory):
            raise web.HTTPNotFound()
        return web.Response(body=path.read_bytes(), content_type=mime)

    async def proxy(request):
        if request.method != API_ROUTES[request.path]:
            raise web.HTTPMethodNotAllowed(request.method, [API_ROUTES[request.path]])
        if request.method == 'POST' and request.content_type != 'application/json':
            raise web.HTTPUnsupportedMediaType(reason='Content-Type must be application/json')
        headers = {name: request.headers[name] for name in
                   ('Authorization', 'Content-Type', 'Idempotency-Key', 'Origin') if name in request.headers}
        # Host must be the gateway's numeric loopback address, never client-controlled.
        headers['Host'] = urlsplit(gateway).netloc
        try:
            async with app[CLIENT].request(request.method, gateway + request.path,
                                           headers=headers, data=await request.read(), allow_redirects=False) as upstream:
                if 300 <= upstream.status < 400 or upstream.content_type != 'application/json':
                    raise web.HTTPBadGateway(reason='Unexpected API response')
                result = bytearray()
                async for chunk in upstream.content.iter_chunked(65536):
                    result.extend(chunk)
                    if len(result) > MAX_RESPONSE:
                        raise web.HTTPBadGateway(reason='API response exceeds the preview limit')
                response = web.Response(body=bytes(result), status=upstream.status, content_type='application/json')
                if upstream.status == 401:
                    response.headers['WWW-Authenticate'] = 'Bearer'
                retry = upstream.headers.get('Retry-After', '')
                if retry.isdigit():
                    response.headers['Retry-After'] = retry
                return response
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise web.HTTPBadGateway(reason='API is unavailable; start the customer gateway') from None

    for route in ASSETS:
        app.router.add_get(route, static)
    for route, method in API_ROUTES.items():
        app.router.add_route(method, route, proxy)
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-dir', type=Path, default=Path('_site'))
    parser.add_argument('--gateway', default='http://127.0.0.1:8798')
    parser.add_argument('--port', type=int, default=8800)
    args = parser.parse_args(argv)
    web.run_app(create_app(args.site_dir, args.gateway), host='127.0.0.1', port=args.port, access_log=None)


if __name__ == '__main__':
    main()
