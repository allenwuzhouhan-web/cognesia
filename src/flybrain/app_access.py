"""Fail-closed personal-key access for the local app.

The trusted gateway URL is operator configuration, never a browser parameter.
Keys remain in memory for at most 30 minutes; sessions revalidate every 30 seconds.
A private filesystem capability is exclusively for explicitly provisioned local
worker clients, never a browser login credential or a shipped release secret.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from http.cookies import SimpleCookie
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request

SESSION_SECONDS = 1800
REVALIDATE_SECONDS = 30
MAX_RESPONSE_BYTES = 16384


class AccessError(Exception):
    def __init__(self, message, status=401):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def access_url(value, *, allow_loopback_http=False):
    try:
        p = urlsplit(value)
        if (not p.hostname or p.username or p.password or p.query or p.fragment
                or p.path != '/v1/access' or len(value) > 500):
            raise ValueError
        p.port
        local = p.hostname == 'localhost'
        try:
            addr = ipaddress.ip_address(p.hostname)
        except ValueError:
            addr = None
        if addr is not None:
            local = addr.is_loopback
            if not local and (not addr.is_global or addr.is_multicast):
                raise ValueError
        elif re.fullmatch(r'[A-Za-z0-9.-]+', p.hostname) is None:
            raise ValueError
        if p.scheme != 'https' and not (p.scheme == 'http' and local and allow_loopback_http):
            raise ValueError
        return value
    except (TypeError, ValueError):
        raise ValueError('COGNESIA_ACCESS_URL must be trusted HTTPS /v1/access; loopback HTTP needs COGNESIA_ACCESS_ALLOW_LOOPBACK_HTTP=1') from None


def verify_personal_key(url, key):
    if not isinstance(key, str) or not 16 <= len(key) <= 256 or not re.fullmatch(r'[A-Za-z0-9_.-]+', key):
        raise AccessError('A valid personal access key is required')
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=5) as response:
            if response.status != 200:
                raise AccessError('Access service did not authorize this key')
            deadline = time.monotonic() + 5
            chunks = []; size = 0
            while True:
                if time.monotonic() > deadline:
                    raise AccessError('Access service timed out', 503)
                block = response.read1(min(4096, MAX_RESPONSE_BYTES + 1 - size))
                if not block: break
                chunks.append(block); size += len(block)
                if size > MAX_RESPONSE_BYTES: break
            raw = b''.join(chunks)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise AccessError('Access service response was too large', 503)
            value = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise AccessError('Personal key is invalid, expired or revoked' if exc.code in (401, 403) else 'Access service unavailable', 401 if exc.code in (401, 403) else 503) from None
    except (OSError, ValueError, UnicodeDecodeError):
        raise AccessError('Access service unavailable', 503) from None
    return normalize_access(value)


def normalize_access(value):
    try:
        if value.get('authenticated') is not True or value.get('authentication') != 'customer_key':
            raise ValueError
        customer = value['customer']['id']; workspace = value['workspace']['id']
        if any(not isinstance(s, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', s) for s in (customer, workspace)):
            raise ValueError
        scopes = value['scopes']
        if not isinstance(scopes, list) or 'read' not in scopes or set(scopes) - {'read', 'run'}:
            raise ValueError
        expiry = datetime.fromisoformat(value['expires_at'].replace('Z', '+00:00'))
        if expiry.tzinfo is None or expiry.timestamp() <= time.time():
            raise ValueError
        return {'customer_id': customer, 'workspace_id': workspace, 'scopes': sorted(set(scopes)),
                'key_expires_at': expiry.timestamp()}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AccessError('Access service returned invalid personal-key authorization', 503) from None


def _private_read(path):
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError('Access state requires private permissions and current-user ownership')
        value = stream.read(8193)
        if len(value) > 8192:
            raise ValueError('Invalid access state')
        return value


def _private_write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(value)


def internal_capability(root, *, create=False):
    directory = Path(root).resolve() / 'build/private/app-access'
    if create:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.is_symlink() or not directory.resolve().is_relative_to(Path(root).resolve()):
            raise ValueError('Access state must remain inside the workspace')
        directory.chmod(0o700)
    path = directory / 'internal-capability'
    if create:
        try:
            _private_write(path, secrets.token_urlsafe(48))
        except FileExistsError:
            pass
    result = _private_read(path).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{64}', result):
        raise ValueError('Invalid internal capability')
    return result


class AppAccess:
    def __init__(self, root, *, endpoint=None, verifier=verify_personal_key):
        self.root = Path(root).resolve()
        self.capability = internal_capability(self.root, create=True)
        config = {}
        if endpoint is None and not os.environ.get('COGNESIA_ACCESS_URL'):
            try:
                config = json.loads(_private_read(self.root / 'build/private/app-access/config.json'))
            except FileNotFoundError:
                pass
            if (not isinstance(config, dict) or set(config) - {'access_url', 'allow_loopback_http'}
                    or not isinstance(config.get('allow_loopback_http', False), bool)):
                raise ValueError('Invalid private app access configuration')
        configured = os.environ.get('COGNESIA_ACCESS_URL', config.get('access_url', '')) if endpoint is None else endpoint
        allow_http = os.environ.get('COGNESIA_ACCESS_ALLOW_LOOPBACK_HTTP') == '1' or config.get('allow_loopback_http') is True
        self.endpoint = access_url(configured, allow_loopback_http=allow_http) if configured else None
        self.verifier = verifier
        self.cookie_name = 'cognesia_' + hashlib.sha256(str(self.root).encode()).hexdigest()[:16]
        self.binding_path = self.root / 'build/private/app-access/principal.json'
        self.sessions = {}
        self._stop_required = False
        self.attempts = deque()
        self.lock = threading.RLock()

    def bind(self, principal):
        """An existing local workspace is permanently bound; logout cannot leak its history."""
        identity = {k: principal[k] for k in ('customer_id', 'workspace_id')}
        with self.lock:
            try:
                saved = json.loads(_private_read(self.binding_path))
            except FileNotFoundError:
                try:
                    _private_write(self.binding_path, json.dumps(identity))
                except FileExistsError:
                    saved = json.loads(_private_read(self.binding_path))
                else:
                    saved = identity
            if saved != identity:
                raise AccessError('This local workspace belongs to a different account. Use a separate workspace directory.', 403)

    def login(self, key):
        with self.lock:
            now = time.time()
            while self.attempts and self.attempts[0] < now - 60:
                self.attempts.popleft()
            if len(self.attempts) >= 6:
                raise AccessError('Too many sign-in attempts; wait one minute', 429)
            self.attempts.append(now)
            if not self.endpoint:
                raise AccessError('Access service is not configured. Set COGNESIA_ACCESS_URL before signing in.', 503)
            if not isinstance(key, str) or not 16 <= len(key) <= 256 or not re.fullmatch(r'[A-Za-z0-9_.-]+', key):
                raise AccessError('A valid personal access key is required')
            principal = self.verifier(self.endpoint, key)
            self.bind(principal)
            self.sessions = {token: s for token, s in self.sessions.items() if s['expires_at'] > now}
            if len(self.sessions) >= 8:
                raise AccessError('Session limit reached; sign out an existing session', 429)
            token = secrets.token_urlsafe(32)
            self.sessions[token] = {'key': key, 'principal': principal, 'checked_at': now,
                'expires_at': min(now + SESSION_SECONDS, principal['key_expires_at']), 'csrf': secrets.token_urlsafe(32)}
            return token, self.public_session(self.sessions[token])

    def token(self, headers):
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get('Cookie', ''))
            return cookies[self.cookie_name].value if self.cookie_name in cookies else ''
        except Exception:
            return ''

    def cookie(self, token, *, clear=False):
        # Secure is intentionally absent only because this listener is literal loopback HTTP.
        return f'{self.cookie_name}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if clear else SESSION_SECONDS}'

    def public_session(self, session):
        p = session['principal']
        return {'authenticated': True, 'customer': {'id': p['customer_id']}, 'workspace': {'id': p['workspace_id']},
                'scopes': p['scopes'], 'csrf': session['csrf'], 'expires_at': session['expires_at'],
                'revalidate_seconds': REVALIDATE_SECONDS}

    def session(self, token):
        with self.lock:
            s = self.sessions.get(token)
            if not s or s['expires_at'] <= time.time():
                if s and 'run' in s['principal']['scopes']: self._stop_required = True
                self.sessions.pop(token, None)
                raise AccessError('Sign in with your personal access key')
            if time.time() - s['checked_at'] >= REVALIDATE_SECONDS:
                try:
                    current = self.verifier(self.endpoint, s['key'])
                    self.bind(current)
                    if any(current[k] != s['principal'][k] for k in ('customer_id', 'workspace_id')):
                        raise AccessError('Personal key identity changed')
                    if current['scopes'] != s['principal']['scopes']:
                        raise AccessError('Access permissions changed; sign in again')
                    s['principal'] = current
                    s['expires_at'] = min(s['expires_at'], current['key_expires_at'])
                    s['checked_at'] = time.time()
                except AccessError:
                    if 'run' in s['principal']['scopes']: self._stop_required = True
                    self.sessions.pop(token, None)
                    raise
                except (OSError, ValueError):
                    if 'run' in s['principal']['scopes']: self._stop_required = True
                    self.sessions.pop(token, None)
                    raise AccessError('Access could not be verified; sign in again', 503) from None
            return s

    def authorize(self, headers, *, scope='read', mutation=False):
        capability = headers.get('X-Cognesia-Internal', '')
        if capability:
            if headers.get('Origin') or not secrets.compare_digest(capability, self.capability):
                raise AccessError('Invalid internal workspace capability', 403)
            customer, workspace = headers.get('X-Cognesia-Customer'), headers.get('X-Cognesia-Workspace')
            if customer or workspace:
                if not customer or not workspace:
                    raise AccessError('Incomplete internal workspace identity', 403)
                self.bind({'customer_id': customer, 'workspace_id': workspace})
            if scope not in headers.get('X-Cognesia-Scopes', 'read run').split():
                raise AccessError('Access key does not permit this operation', 403)
            return {'internal': True, 'scopes': ['read', 'run']}
        s = self.session(self.token(headers))
        if scope not in s['principal']['scopes']:
            raise AccessError('Access key does not permit this operation', 403)
        if mutation and not secrets.compare_digest(headers.get('X-Cognesia-CSRF', ''), s['csrf']):
            raise AccessError('Refresh the app before sending this request', 403)
        return self.public_session(s)

    def logout(self, headers):
        with self.lock:
            self.sessions.pop(self.token(headers), None)

    def revalidate_all(self):
        """Consume run-access loss, including failures discovered by request threads."""
        with self.lock:
            tokens = list(self.sessions)
        for token in tokens:
            try:
                self.session(token)
            except AccessError:
                pass
        with self.lock:
            lost = self._stop_required
            self._stop_required = False
        return lost


READ_POSTS = frozenset(('/api/connectivity', '/api/selection/preview', '/api/replicates/plan',
    '/api/protocols/import', '/api/analysis/interval'))


def scope_for_request(method, path):
    return 'read' if path == '/auth/logout' or method in ('GET', 'HEAD') or path in READ_POSTS or (path.startswith('/api/checkpoints/') and path.endswith('/branches')) else 'run'


LOGIN_HTML = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cognesia · Sign in</title><style>body{font:17px system-ui;background:#101817;color:#e3eee7;max-width:440px;margin:12vh auto;padding:30px}h1{font-size:38px}input,button{box-sizing:border-box;width:100%;padding:14px;border-radius:10px;margin:8px 0;font:inherit}input{background:#23302c;color:white;border:1px solid #607469}button{background:#b4d7bc;border:0}p{line-height:1.6}#status{color:#edc39b}</style></head><body><h1>Cognesia</h1><p>Enter your personal access key to open this workspace.</p><form id="login"><input id="key" aria-label="Personal access key" type="password" autocomplete="off" required maxlength="256"><button>Open workspace</button></form><p id="status" role="status"></p><p>Your key stays in server memory for this session. An access service must be configured by the operator.</p><script src="/auth/login.js"></script></body></html>'''
LOGIN_JS = '''document.querySelector('#login').addEventListener('submit',async e=>{e.preventDefault();const field=document.querySelector('#key'),key=field.value;field.value='';try{const r=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json','X-Cognesia-Login':'1'},body:JSON.stringify({key})});const v=await r.json();if(!r.ok)throw Error(v.error||'Sign in failed');location.replace('/')}catch(e){document.querySelector('#status').textContent=e.message}});'''
CLIENT_JS = '''(()=>{const original=window.fetch.bind(window);let session;const load=()=>session||(session=original('/auth/session').then(async r=>{if(!r.ok){location.replace('/auth/login');throw Error('Sign in required')}return r.json()}));window.fetch=async(input,init={})=>{const url=new URL(typeof input==='string'?input:input.url,location.href);const method=(init.method||(input instanceof Request?input.method:'GET')).toUpperCase();if(url.origin===location.origin&&!url.pathname.startsWith('/auth/')&&!['GET','HEAD','OPTIONS'].includes(method)){const s=await load();const headers=new Headers(init.headers||(input instanceof Request?input.headers:undefined));headers.set('X-Cognesia-CSRF',s.csrf);init={...init,headers}}const response=await original(input,init);if(response.status===401&&url.origin===location.origin)location.replace('/auth/login');return response};document.addEventListener('DOMContentLoaded',()=>{const host=document.querySelector('.top-right');if(!host)return;const button=document.createElement('button');button.textContent='Sign out';button.addEventListener('click',async()=>{button.disabled=true;try{const s=await load();const r=await original('/auth/logout',{method:'POST',headers:{'Content-Type':'application/json','X-Cognesia-CSRF':s.csrf},body:'{}'});if(!r.ok)throw Error('Sign out failed');location.replace('/auth/login')}catch(e){button.disabled=false;button.textContent=e.message}});host.append(button)});load().catch(()=>{});})();'''
