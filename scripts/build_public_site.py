#!/usr/bin/env python3
"""Build the static Cognesia page with its actual repository and Pages URLs."""
import argparse
import base64
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import tomllib
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def content_security_policy(page):
    """Permit only the exact generated metadata block, never arbitrary inline JS."""
    scripts = re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    hashes = ["'sha256-" + base64.b64encode(hashlib.sha256(value.encode()).digest()).decode() + "'" for value in scripts]
    return ("default-src 'none'; script-src 'self' " + ' '.join(hashes) +
            "; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'")


def build(repository, site_url, branch='main', output=None, mode='gateway'):
    if mode not in ('gateway', 'static'):
        raise ValueError('Site mode must be gateway or static')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Repository must be OWNER/REPOSITORY')
    parsed = urlsplit(site_url)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('Site URL must be a public HTTPS URL without credentials, query or fragment')
    site_url = site_url.rstrip('/') + '/'
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    repo_url = 'https://github.com/' + repository
    structured = {'@context': 'https://schema.org', '@type': 'SoftwareSourceCode',
                  'name': 'Cognesia', 'version': version, 'url': site_url,
                  'codeRepository': repo_url, 'programmingLanguage': ['Python', 'JavaScript', 'Swift'],
                  'description': 'An experimental Drosophila connectome and neural simulation workbench.'}
    replacements = {'SITE_URL': html.escape(site_url, quote=True),
                    'REPO_URL': repo_url, 'BRANCH': quote(branch, safe=''), 'VERSION': version,
                    'STRUCTURED_DATA': json.dumps(structured).replace('<', '\\u003c')}
    page = (ROOT / 'site/index.html').read_text()
    if mode == 'static':
        # Static hosting has no account service or simulation gateway.
        section = (ROOT / 'site/static-access.html').read_text()
        page, count = re.subn(r'<section id="api"\s.*?</section>', lambda _: section, page, flags=re.S)
        if count != 1:
            raise ValueError('Expected exactly one API section in the site template')
        page = page.replace('Get API access', 'Get Cognesia')
        page = page.replace('illustration and API console', 'illustration')
    for key, value in replacements.items():
        page = page.replace('@@' + key + '@@', value)
    if re.search(r'@@[A-Z_]+@@', page):
        raise ValueError('Unresolved public-site template variable')
    output = Path(output) if output else ROOT / '_site'
    output.mkdir(parents=True, exist_ok=True)
    if mode == 'static':
        policy = content_security_policy(page).replace("; frame-ancestors 'none'", '')
        policy = policy.replace("connect-src 'self'", "connect-src 'none'").replace("form-action 'self'", "form-action 'none'")
        page = page.replace('<head>', '<head>\n  <meta http-equiv="Content-Security-Policy" content="' + html.escape(policy, quote=True) + '">', 1)
    (output / 'index.html').write_text(page)
    for name in ('style.css', 'app.js', 'icon.svg'):
        shutil.copy2(ROOT / 'site' / name, output / name)
    policy = content_security_policy(page)
    (output / 'security-headers.conf').write_text(
        '# Generated with this site build. Include in nginx; never serve as an asset.\n'
        'add_header Content-Security-Policy "' + policy + '" always;\n'
        'add_header X-Content-Type-Options "nosniff" always;\n'
        'add_header Referrer-Policy "no-referrer" always;\n'
        'add_header X-Frame-Options "DENY" always;\n'
        'add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()" always;\n'
        'add_header Strict-Transport-Security "max-age=31536000" always;\n'
        'add_header Cache-Control "no-store" always;\n')
    (output / '.nojekyll').touch()
    if mode == 'static':
        # A reused gateway output must not carry account forms/config into Pages.
        for name in ('account.html', 'account.js', 'account.css', 'security-headers.conf'):
            (output / name).unlink(missing_ok=True)
    (output / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>' + html.escape(site_url) + '</loc></url></urlset>\n')
    # A project Pages subdirectory cannot control the host-level /robots.txt.
    # No robots exclusion is needed; the page explicitly permits indexing.
    print(f'Built Cognesia v{version}: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--site-url', required=True)
    parser.add_argument('--branch', default='main')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--mode', choices=('gateway', 'static'), default='gateway',
                        help='Use static for public pages without a same-origin API')
    args = parser.parse_args()
    build(args.repository, args.site_url, args.branch, args.output, args.mode)
