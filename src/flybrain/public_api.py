"""Cognesia tools with local owner-password or isolated customer-key authentication.

The GUI stays on its loopback viewer. This optional gateway uses the same bounded
scientific tools and never exposes arbitrary shell commands, paths, or URLs.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web

from .api_tools import ToolError, execute_tool, tool_schemas, validate_backend_url, validate_tool
from .api_credentials import CredentialError, CredentialRegistry, Principal, scope_for_tool

MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_CACHE_BYTES = 64 * 1024 * 1024
GLOBAL_CACHE_BYTES = 512 * 1024 * 1024
RESULT_RETENTION_SECONDS = 86400
MAX_IDEMPOTENCY_RECORDS = 100_000
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,160}$")
SCRYPT_N, SCRYPT_R, SCRYPT_P = 32768, 8, 1


class APIError(Exception):
    def __init__(self, message, status=400, code="invalid_request"):
        super().__init__(message)
        self.status, self.code = status, code


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                          p=SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)


@dataclass(frozen=True)
class PasswordVerifier:
    salt: bytes
    digest: bytes

    @classmethod
    def load(cls, path):
        path=Path(path)
        if path.stat().st_mode & 0o077:
            raise ValueError("Password verifier must have private permissions (chmod 600)")
        value=json.loads(path.read_text())
        if (not isinstance(value,dict) or value.get("version")!=1 or value.get("algorithm")!="scrypt"
            or (value.get("n"),value.get("r"),value.get("p"))!=(SCRYPT_N,SCRYPT_R,SCRYPT_P)):
            raise ValueError("Unsupported password verifier; use init-password")
        try:
            salt=base64.b64decode(value["salt"],validate=True)
            digest=base64.b64decode(value["digest"],validate=True)
        except (KeyError,ValueError,TypeError):raise ValueError("Invalid password verifier") from None
        if len(salt)!=16 or len(digest)!=32:raise ValueError("Invalid password verifier")
        return cls(salt,digest)

    def verify(self, password):
        if not isinstance(password,str) or not 1<=len(password)<=256:
            return False
        return hmac.compare_digest(_password_hash(password,self.salt),self.digest)


def initialize_password(verifier_file, output_file):
    """Create a strong password and salted verifier, never overwriting either file."""
    verifier_file,output_file=Path(verifier_file),Path(output_file)
    if verifier_file.resolve()==output_file.resolve():raise ValueError("Password output and verifier must be separate files")
    password=secrets.token_urlsafe(32);salt=secrets.token_bytes(16)
    record={"version":1,"algorithm":"scrypt","n":SCRYPT_N,"r":SCRYPT_R,"p":SCRYPT_P,
            "salt":base64.b64encode(salt).decode(),"digest":base64.b64encode(_password_hash(password,salt)).decode()}
    created=[]
    try:
        for path,value in ((output_file,{"password":password,"verifier_file":str(verifier_file.resolve())}), (verifier_file,record)):
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            created.append(path)
            with os.fdopen(fd,"w") as stream:
                stream.write(_json(value)+"\n");stream.flush();os.fsync(stream.fileno())
    except BaseException:
        for path in created:path.unlink(missing_ok=True)
        raise


class Ledger:
    """Durable, tenant-bound at-most-once dispatch, cached results and stop leases."""
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR,0o600);os.close(fd)
        self.path.chmod(0o600)
        with self.connect(write=True) as db:
            existing={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if existing-{"gateway_calls","gateway_state","gateway_namespaces"}:
                raise ValueError("State file contains a different ledger; choose a fresh tool-gateway.sqlite3")
            db.execute("CREATE TABLE IF NOT EXISTS gateway_calls(key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,state TEXT NOT NULL,status INTEGER,response TEXT,created REAL NOT NULL,cache_bytes INTEGER NOT NULL DEFAULT 0,namespace TEXT NOT NULL DEFAULT 'owner')")
            if "namespace" not in {row[1] for row in db.execute("PRAGMA table_info(gateway_calls)")}:
                db.execute("ALTER TABLE gateway_calls ADD COLUMN namespace TEXT NOT NULL DEFAULT 'owner'")
            db.execute("CREATE INDEX IF NOT EXISTS gateway_expiry ON gateway_calls(state,created)")
            db.execute("CREATE INDEX IF NOT EXISTS gateway_namespace ON gateway_calls(namespace)")
            db.execute("CREATE TABLE IF NOT EXISTS gateway_state(id INTEGER PRIMARY KEY CHECK(id=1),cache_bytes INTEGER NOT NULL DEFAULT 0 CHECK(cache_bytes>=0),job_deadline REAL)")
            db.execute("INSERT OR IGNORE INTO gateway_state(id) VALUES(1)")
            db.execute("CREATE TABLE IF NOT EXISTS gateway_namespaces(namespace TEXT PRIMARY KEY,backend_url TEXT,workspace_fingerprint TEXT,cache_bytes INTEGER NOT NULL DEFAULT 0 CHECK(cache_bytes>=0),job_deadline REAL)")
            # Keep old owner keys and stop leases intact when migrating the local API.
            db.execute("INSERT OR IGNORE INTO gateway_namespaces(namespace,cache_bytes,job_deadline) SELECT 'owner',COALESCE((SELECT SUM(cache_bytes) FROM gateway_calls WHERE namespace='owner'),0),job_deadline FROM gateway_state WHERE id=1")
            db.execute("UPDATE gateway_state SET job_deadline=NULL WHERE id=1")
        with self.connect() as db:db.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def connect(self,write=False):
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None)
        db.row_factory=sqlite3.Row
        try:
            if write:db.execute("BEGIN IMMEDIATE")
            yield db
            if write:db.commit()
        except BaseException:
            if write:db.rollback()
            raise
        finally:db.close()

    @staticmethod
    def _storage_key(key,namespace):
        return key if namespace=="owner" else namespace+":"+key

    def bind(self,namespace,backend_url,fingerprint=None):
        with self.connect(write=True) as db:
            row=db.execute("SELECT backend_url,workspace_fingerprint FROM gateway_namespaces WHERE namespace=?",(namespace,)).fetchone()
            if row and row["backend_url"] is not None and (row["backend_url"],row["workspace_fingerprint"])!=(backend_url,fingerprint):
                raise APIError("Saved workspace binding does not match this credential; operator review is required",503,"workspace_binding_changed")
            for other in db.execute("SELECT namespace,backend_url,workspace_fingerprint FROM gateway_namespaces WHERE namespace<>? AND backend_url IS NOT NULL",(namespace,)):
                if urlsplit(other["backend_url"]).port==urlsplit(backend_url).port or (fingerprint is not None and other["workspace_fingerprint"]==fingerprint):
                    raise APIError("A different saved customer already owns this worker or workspace; operator review is required",503,"workspace_binding_changed")
            if not row:
                if db.execute("SELECT COUNT(*) FROM gateway_namespaces").fetchone()[0]>=10001:raise APIError("Workspace capacity reached",503,"ledger_capacity")
                db.execute("INSERT INTO gateway_namespaces(namespace,backend_url,workspace_fingerprint) VALUES(?,?,?)",(namespace,backend_url,fingerprint))
            elif row["backend_url"] is None:
                db.execute("UPDATE gateway_namespaces SET backend_url=?,workspace_fingerprint=? WHERE namespace=?",(backend_url,fingerprint,namespace))

    def replay(self,key,payload,namespace="owner"):
        stored=self._storage_key(key,namespace)
        with self.connect() as db:
            row=db.execute("SELECT * FROM gateway_calls WHERE key=? AND namespace=?",(stored,namespace)).fetchone()
        if row:
            fingerprint=hashlib.sha256(_json(payload).encode()).hexdigest()
            if not hmac.compare_digest(row["fingerprint"],fingerprint):raise APIError("Idempotency-Key was already used for different arguments",409,"idempotency_conflict")
            if row["state"]!="complete":raise APIError("This call is in progress or its outcome is unknown; inspect the experiment before another mutation",409,"call_in_progress")
            return row["status"],json.loads(row["response"])
        return None

    def reserve(self,key,payload,namespace="owner"):
        stored=self._storage_key(key,namespace)
        fingerprint=hashlib.sha256(_json(payload).encode()).hexdigest()
        with self.connect(write=True) as db:
            previous=db.execute("SELECT * FROM gateway_calls WHERE key=? AND namespace=?",(stored,namespace)).fetchone()
            if previous:
                if not hmac.compare_digest(previous["fingerprint"],fingerprint):
                    raise APIError("Idempotency-Key was already used for different arguments",409,"idempotency_conflict")
                if previous["state"]!="complete":
                    raise APIError("This call is in progress or its outcome is unknown; inspect the experiment before another mutation",409,"call_in_progress")
                return previous["status"],json.loads(previous["response"])
            local=db.execute("SELECT cache_bytes FROM gateway_namespaces WHERE namespace=?",(namespace,)).fetchone()
            if local is None:raise APIError("Workspace is not bound",503,"workspace_unavailable")
            if db.execute("SELECT COUNT(*) FROM gateway_calls WHERE namespace=?",(namespace,)).fetchone()[0]>=MAX_IDEMPOTENCY_RECORDS or db.execute("SELECT COUNT(*) FROM gateway_calls").fetchone()[0]>=1_000_000:
                raise APIError("Idempotency metadata capacity reached; operator maintenance is required",503,"ledger_capacity")
            used=db.execute("SELECT cache_bytes FROM gateway_state WHERE id=1").fetchone()[0]
            if local["cache_bytes"]+MAX_RESULT_BYTES>MAX_CACHE_BYTES or used+MAX_RESULT_BYTES>GLOBAL_CACHE_BYTES:
                raise APIError("Result cache is full. Results expire after 24 hours; this request has not run.",429,"result_capacity")
            db.execute("UPDATE gateway_state SET cache_bytes=cache_bytes+? WHERE id=1",(MAX_RESULT_BYTES,))
            db.execute("UPDATE gateway_namespaces SET cache_bytes=cache_bytes+? WHERE namespace=?",(MAX_RESULT_BYTES,namespace))
            db.execute("INSERT INTO gateway_calls(key,fingerprint,state,created,cache_bytes,namespace) VALUES(?,?,'running',?,?,?)",(stored,fingerprint,time.time(),MAX_RESULT_BYTES,namespace))
        return None

    def finish(self,key,status,result,namespace="owner"):
        stored=self._storage_key(key,namespace)
        response=_json(result);size=len(response.encode())
        if size>MAX_RESULT_BYTES:raise APIError("Tool result exceeds the cache bound",413,"response_too_large")
        with self.connect(write=True) as db:
            row=db.execute("SELECT state,cache_bytes FROM gateway_calls WHERE key=? AND namespace=?",(stored,namespace)).fetchone()
            if row and row["state"]=="running":
                db.execute("UPDATE gateway_calls SET state='complete',status=?,response=?,cache_bytes=? WHERE key=? AND namespace=?",(status,response,size,stored,namespace))
                delta=size-row["cache_bytes"]
                db.execute("UPDATE gateway_state SET cache_bytes=cache_bytes+? WHERE id=1",(delta,))
                db.execute("UPDATE gateway_namespaces SET cache_bytes=cache_bytes+? WHERE namespace=?",(delta,namespace))

    def expire_results(self):
        response=_json({"error":{"code":"result_expired","message":"Cached result expired after 24 hours. This call will not run again; inspect the saved experiment or recording with a new read call."}})
        with self.connect(write=True) as db:
            rows=list(db.execute("SELECT key,namespace,cache_bytes FROM gateway_calls WHERE state='complete' AND cache_bytes>0 AND created<? LIMIT 1000",(time.time()-RESULT_RETENTION_SECONDS,)))
            for row in rows:
                db.execute("UPDATE gateway_state SET cache_bytes=cache_bytes-? WHERE id=1",(row["cache_bytes"],))
                db.execute("UPDATE gateway_namespaces SET cache_bytes=cache_bytes-? WHERE namespace=?",(row["cache_bytes"],row["namespace"]))
                db.execute("UPDATE gateway_calls SET status=410,response=?,cache_bytes=0 WHERE key=?",(response,row["key"]))

    def recover_interrupted(self):
        """Call only after acquiring the exclusive gateway process lock."""
        with self.connect() as db:rows=list(db.execute("SELECT key,namespace FROM gateway_calls WHERE state='running'"))
        for row in rows:
            key=row["key"] if row["namespace"]=="owner" else row["key"].removeprefix(row["namespace"]+":")
            self.finish(key,409,{"error":{"code":"execution_unknown","message":"Gateway restarted during execution. This call is never dispatched again; inspect the worker state."}},row["namespace"])
        self.expire_results()

    def lease_job(self,deadline,*,replace=False,namespace="owner"):
        with self.connect(write=True) as db:
            expression="?" if replace else "COALESCE(job_deadline,?)"
            db.execute("UPDATE gateway_namespaces SET job_deadline="+expression+" WHERE namespace=?",(deadline,namespace))

    def job_deadline(self,namespace="owner"):
        with self.connect() as db:
            row=db.execute("SELECT job_deadline FROM gateway_namespaces WHERE namespace=?",(namespace,)).fetchone()
            return row[0] if row else None

    def expired_jobs(self):
        with self.connect() as db:return [dict(row) for row in db.execute("SELECT namespace,backend_url,workspace_fingerprint,job_deadline FROM gateway_namespaces WHERE backend_url IS NOT NULL AND job_deadline<=?",(time.time(),))]

    def clear_lease(self,deadline=None,namespace="owner"):
        with self.connect(write=True) as db:
            if deadline is None:db.execute("UPDATE gateway_namespaces SET job_deadline=NULL WHERE namespace=?",(namespace,))
            else:db.execute("UPDATE gateway_namespaces SET job_deadline=NULL WHERE namespace=? AND job_deadline=?",(namespace,deadline))

@dataclass(frozen=True)
class Config:
    database: Path
    password_file: Path | None = None
    backend_url: str = "http://127.0.0.1:8794"
    auth_mode: str = "owner"
    credential_registry: Path | None = None
    public_origin: str | None = None
    production: bool = False
    allow_operator_tools: bool = False
    request_timeout: int = 45
    max_duration_ms: int = 10000
    max_job_wall_seconds: int = 900
    workspace_root: Path | None = None

    def validate(self):
        validate_backend_url(self.backend_url)
        if self.public_origin:
            origin=urlsplit(self.public_origin)
            if origin.username or origin.password or origin.path not in ("","/") or origin.query or origin.fragment or not origin.hostname or origin.scheme not in ("http","https"):
                raise ValueError("Public origin must be an HTTP(S) origin without credentials, path or query")
            if self.production and origin.scheme!="https":raise ValueError("Production requires an HTTPS public origin")
        elif self.production:raise ValueError("Production requires an HTTPS public origin")
        if not 1<=self.request_timeout<=120:raise ValueError("Tool timeout must be between 1 and 120 seconds")
        if not 1<=self.max_duration_ms<=10000 or not 30<=self.max_job_wall_seconds<=86400:
            raise ValueError("Experiments need bounded simulated and wall-clock duration")
        if self.auth_mode not in ("owner","customer"):raise ValueError("Choose owner or customer authentication")
        if self.production and self.auth_mode!="customer":raise ValueError("Production requires customer keys and a customer registry; shared owner passwords are local-only")
        if self.auth_mode=="customer":
            if self.credential_registry is None:raise ValueError("Customer mode requires a credential registry")
            CredentialRegistry(self.credential_registry)
            if self.allow_operator_tools:raise ValueError("Customer credentials can never enable operator maintenance tools")
        else:
            if self.password_file is None:raise ValueError("Owner mode requires a password verifier")
            PasswordVerifier.load(self.password_file)


LEDGER_KEY=web.AppKey("ledger",Ledger)
HTTP_KEY=web.AppKey("http",aiohttp.ClientSession)
WATCHDOG_KEY=web.AppKey("watchdog",asyncio.Task)


def _idempotency_key(request):
    key=request.headers.get("Idempotency-Key","")
    if not IDEMPOTENCY_PATTERN.fullmatch(key):raise APIError("Provide a 16–160 character Idempotency-Key using letters, digits, hyphens or underscores")
    return key


async def _body(request):
    if request.content_type!="application/json":raise APIError("Content-Type must be application/json",415,"content_type")
    try:value=json.loads(await request.read(),parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    except (ValueError,UnicodeDecodeError,RecursionError):raise APIError("Expected a finite JSON object") from None
    if not isinstance(value,dict) or set(value)!={"name","arguments"}:raise APIError("Request must contain exactly name and arguments")
    return value


async def verify_workspace_backend(session,backend_url,expected_fingerprint):
    """Require the actual worker root to match its offline customer binding."""
    try:
        async with session.get(validate_backend_url(backend_url)+"/api/health",allow_redirects=False,timeout=aiohttp.ClientTimeout(total=5)) as response:
            data=await response.content.read(65537)
            if response.status!=200 or len(data)>65536:raise ValueError("Invalid worker health")
            value=json.loads(data)
        actual=value.get("workspace_fingerprint") if isinstance(value,dict) else None
        if not isinstance(actual,str) or not hmac.compare_digest(actual,expected_fingerprint):raise ValueError("Workspace mismatch")
    except (aiohttp.ClientError,TimeoutError,ValueError,TypeError):
        raise APIError("The dedicated workspace is unavailable or its identity does not match; contact the operator",503,"workspace_unavailable") from None


PRINCIPAL_KEY=getattr(web,"RequestKey",web.AppKey)("principal",Principal)


def create_app(config: Config, *, executor=execute_tool, workspace_checker=verify_workspace_backend):
    config.validate()
    registry=CredentialRegistry(config.credential_registry) if config.auth_mode=="customer" else None
    verifier=PasswordVerifier.load(config.password_file) if registry is None else None
    ledger=Ledger(config.database)
    if registry is None:ledger.bind("owner",config.backend_url)
    async def worker_execute(name, arguments, backend_url, **kwargs):
        if executor is not execute_tool:
            return await executor(name, arguments, backend_url, **kwargs)
        from .app_access import internal_capability
        try:
            if registry:
                with registry.connect() as db:
                    binding = db.execute("SELECT * FROM customer_workspaces WHERE backend_url=?", (backend_url,)).fetchone()
                if binding is None:
                    raise ValueError('Missing workspace binding')
                root = Path(binding['workspace_root'])
                headers = {'X-Cognesia-Customer': binding['customer_id'], 'X-Cognesia-Workspace': binding['workspace_id']}
            else:
                if config.workspace_root is None:
                    raise ValueError('Configure the owner workspace root')
                root = config.workspace_root
                headers = {}
            headers['X-Cognesia-Internal'] = internal_capability(root)
        except (OSError, ValueError):
            raise ToolError('Private worker capability unavailable; provision the dedicated workspace before executing tools', 503, 'worker_credentials_unavailable') from None
        return await executor(name, arguments, backend_url, worker_headers=headers, **kwargs)

    limits={};active_calls=0;active_namespaces={};workspace_locks={}
    def workspace_lock(namespace):
        return workspace_locks.setdefault(namespace,asyncio.Lock())
    auth_slots=asyncio.Semaphore(2)

    def limit(bucket,maximum):
        window=int(time.time()//60)
        if bucket not in limits and len(limits)>=40000:
            for old in list(limits):
                if limits[old][0]!=window:limits.pop(old,None)
            if len(limits)>=40000:raise APIError("Client capacity reached",429,"rate_limit")
        previous,count=limits.get(bucket,(window,0))
        count=count+1 if previous==window else 1;limits[bucket]=(window,count)
        if count>maximum:raise APIError("Request rate exceeded; retry after one minute",429,"rate_limit")

    @web.middleware
    async def boundary(request,handler):
        try:
            sock=request.transport.get_extra_info("sockname") if request.transport else None
            port=sock[1] if sock else None
            hosts={f"127.0.0.1:{port}",f"localhost:{port}"}
            if config.public_origin:hosts.add(urlsplit(config.public_origin).netloc)
            if request.headers.get("Host","") not in hosts:raise APIError("Unexpected gateway host",403,"host_forbidden")
            origin=request.headers.get("Origin")
            origins={config.public_origin.rstrip("/")} if config.public_origin else set()
            if not config.production:origins.update("http://"+host for host in hosts)
            if origin and origin not in origins:raise APIError("Cross-origin browser requests are not allowed",403,"origin_forbidden")
            peer=request.remote or "unknown"
            if request.path=="/health":limit("health:"+peer,120)
            elif registry is not None:
                auth=request.headers.get("Authorization","")
                try:
                    principal=registry.authenticate(auth[7:] if auth.startswith("Bearer ") else "")
                except CredentialError:
                    limit("failed:"+peer,30);limit("failed-global",600)
                    raise
                # Key validity is checked fresh on every protected request, before replay.
                limit("customer:"+principal.namespace,120);limit("authenticated-global",2400)
                ledger.bind(principal.namespace,principal.backend_url,principal.workspace_fingerprint)
                request[PRINCIPAL_KEY]=principal
            else:
                limit("owner:"+peer,120)
                auth=request.headers.get("Authorization","")
                if not auth.startswith("Bearer "):raise APIError("The workspace password is required",401,"unauthorized")
                if auth_slots.locked():raise APIError("Authentication capacity reached; retry shortly",429,"authentication_capacity")
                async with auth_slots:valid=await asyncio.to_thread(verifier.verify,auth[7:])
                if not valid:raise APIError("The workspace password is incorrect",401,"unauthorized")
            response=await handler(request)
        except (APIError,ToolError,CredentialError) as error:
            response=web.json_response({"error":{"code":error.code,"message":str(error)}},status=error.status)
            if error.status==429:response.headers["Retry-After"]="60"
            if error.status==401:response.headers["WWW-Authenticate"]="Bearer"
        except web.HTTPException as error:
            response=web.json_response({"error":{"code":"http_error","message":error.reason}},status=error.status)
        except Exception:
            response=web.json_response({"error":{"code":"internal_error","message":"The gateway could not complete this request"}},status=500)
        response.headers.update({"Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer","Content-Security-Policy":"default-src 'none'; frame-ancestors 'none'"})
        if config.production:response.headers["Strict-Transport-Security"]="max-age=31536000"
        return response

    app=web.Application(client_max_size=1024*1024,middlewares=[boundary])
    app[LEDGER_KEY]=ledger

    async def watchdog():
        while True:
            ledger.expire_results()
            for job in ledger.expired_jobs():
                try:
                    async with workspace_lock(job["namespace"]):
                        # Another call may have replaced this snapshot's lease while
                        # waiting for the lock. Never stop a newer experiment.
                        if ledger.job_deadline(job["namespace"])!=job["job_deadline"]:continue
                        if job["workspace_fingerprint"]:
                            await workspace_checker(app[HTTP_KEY],job["backend_url"],job["workspace_fingerprint"])
                        await worker_execute("cognesia_stop_all",{},job["backend_url"],session=app[HTTP_KEY],allow_operator=False,timeout=config.request_timeout)
                        ledger.clear_lease(job["job_deadline"],job["namespace"])
                except (APIError,ToolError,TimeoutError):pass
            await asyncio.sleep(10)
    async def startup(app):
        app[HTTP_KEY]=aiohttp.ClientSession(trust_env=False,cookie_jar=aiohttp.DummyCookieJar())
        app[WATCHDOG_KEY]=asyncio.create_task(watchdog())
    async def cleanup(app):
        app[WATCHDOG_KEY].cancel()
        try:await app[WATCHDOG_KEY]
        except asyncio.CancelledError:pass
        await app[HTTP_KEY].close()
    app.on_startup.append(startup);app.on_cleanup.append(cleanup)

    async def health(request):return web.json_response({"service":"cognesia-tool-api","api_version":1,"authentication":"customer_key" if registry else "password","billing":False})
    async def access(request):
        principal=request.get(PRINCIPAL_KEY)
        return web.json_response(principal.public_access() if principal else {"authenticated":True,"workspace":"shared_private","billing":False})
    async def tools_handler(request):
        principal=request.get(PRINCIPAL_KEY)
        schemas=tool_schemas(allow_operator=config.allow_operator_tools if principal is None else False)
        if principal:
            schemas=[tool for tool in schemas if scope_for_tool(tool["function"]["name"]) in principal.scopes]
            return web.json_response({"tools":schemas,"tool_scopes":{tool["function"]["name"]:scope_for_tool(tool["function"]["name"]) for tool in schemas}})
        return web.json_response({"tools":schemas})
    async def call(request):
        nonlocal active_calls
        principal=request.get(PRINCIPAL_KEY)
        namespace=principal.namespace if principal else "owner"
        backend=principal.backend_url if principal else config.backend_url
        operator=config.allow_operator_tools if principal is None else False
        payload=await _body(request)
        validate_tool(payload["name"],payload["arguments"],allow_operator=operator)
        if principal and scope_for_tool(payload["name"]) not in principal.scopes:
            raise APIError("This customer key does not permit the requested tool",403,"insufficient_scope")
        if payload["name"]=="cognesia_start":
            options=payload["arguments"]["options"];duration=options.get("duration_ms")
            if "legacy_protocol" in options or isinstance(duration,bool) or not isinstance(duration,(int,float)) or not 0<duration<=config.max_duration_ms:
                raise APIError(f"API experiments require explicit duration_ms up to {config.max_duration_ms}; unbounded legacy protocols use the local workbench",400,"workload_limit")
        key=_idempotency_key(request)
        previous=ledger.replay(key,payload,namespace)
        if previous:return web.json_response(previous[1],status=previous[0])
        if active_calls>=4 or (principal and active_namespaces.get(namespace,0)>=1):
            raise APIError("Gateway execution slots are full; retry with the same key",429,"gateway_capacity")
        active_calls+=1;active_namespaces[namespace]=active_namespaces.get(namespace,0)+1
        try:
            async with workspace_lock(namespace):
                if principal:await workspace_checker(app[HTTP_KEY],backend,principal.workspace_fingerprint)
                previous=ledger.reserve(key,payload,namespace)
                if previous:return web.json_response(previous[1],status=previous[0])
                if payload["name"]=="cognesia_start":ledger.lease_job(time.time()+config.max_job_wall_seconds,namespace=namespace)
                status=200
                try:
                    result=await worker_execute(payload["name"],payload["arguments"],backend,session=app[HTTP_KEY],allow_operator=operator,timeout=config.request_timeout)
                    if payload["name"]=="cognesia_start" and isinstance(result,dict) and result.get("id"):
                        ledger.lease_job(time.time()+config.max_job_wall_seconds,replace=True,namespace=namespace)
                    if payload["name"]=="cognesia_sessions" and isinstance(result,dict):
                        active={"queued","running","preparing","paused","pause_requested","checkpointing","finalizing"}
                        jobs=result.get("sessions")
                        if isinstance(jobs,list) and not any(job.get("status") in active for job in jobs):ledger.clear_lease(namespace=namespace)
                    result={"result":result}
                    if len(_json(result).encode())>MAX_RESULT_BYTES:raise ToolError("Serialized result exceeds 8 MiB; use smaller selections or asset chunks",413,"response_too_large")
                except ToolError as error:
                    status=error.status;result={"error":{"code":error.code,"message":str(error)}}
                except asyncio.CancelledError:raise
                except Exception:
                    status=500;result={"error":{"code":"execution_unknown","message":"Execution outcome is uncertain; inspect the experiment before another mutation."}}
                ledger.finish(key,status,result,namespace)
                return web.json_response(result,status=status)
        finally:
            active_calls-=1
            active_namespaces[namespace]-=1
            if not active_namespaces[namespace]:active_namespaces.pop(namespace,None)

    app.router.add_get("/health",health)
    app.router.add_get("/v1/access",access)
    app.router.add_get("/v1/tools",tools_handler)
    app.router.add_post("/v1/tools/call",call)
    return app

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file",default="build/private/tool-gateway.sqlite3",help="Dedicated tool idempotency/cache state")
    parser.add_argument("--password-file",default="build/private/api-password-hash.json",help="Salted scrypt password verifier")
    parser.add_argument("--registry",default="build/private/customer-keys.sqlite3",help="Private customer key verifier registry")
    commands=parser.add_subparsers(dest="command",required=True)
    init=commands.add_parser("init-password",help="Generate a strong password and separate salted verifier, in private files")
    init.add_argument("--output",required=True,help="One-time password output file (keep private)")
    serve=commands.add_parser("serve",help="Serve authenticated tools on loopback, optionally behind HTTPS")
    serve.add_argument("--port",type=int,default=8796)
    serve.add_argument("--auth-mode",choices=("owner","customer"),default="owner")
    serve.add_argument("--workspace-root", type=Path, help="Owner mode: dedicated viewer root containing its private internal capability")
    serve.add_argument("--backend",default="http://127.0.0.1:8794",help="Owner mode only: explicit shared private workspace; customer backends come from the registry")
    serve.add_argument("--allow-operator-tools",action="store_true")
    serve.add_argument("--public-origin",default=os.environ.get("COGNESIA_PUBLIC_ORIGIN"))
    serve.add_argument("--production",action="store_true")
    issue=commands.add_parser("key-issue",help="Issue a scoped customer key offline to a private file")
    issue.add_argument("--customer",required=True)
    issue.add_argument("--name",required=True)
    issue.add_argument("--workspace",required=True)
    issue.add_argument("--backend",required=True)
    issue.add_argument("--workspace-root",required=True)
    issue.add_argument("--scopes",default="read",help="read or read,run")
    issue.add_argument("--expires-days",type=int,default=90)
    issue.add_argument("--output",required=True)
    listing=commands.add_parser("key-list",help="List public key identities and status, without verifiers")
    listing.add_argument("--customer")
    revoke=commands.add_parser("key-revoke",help="Revoke a key immediately for new requests")
    revoke.add_argument("key_id")
    rotate=commands.add_parser("key-rotate",help="Atomically replace a key and revoke the old key")
    rotate.add_argument("key_id")
    rotate.add_argument("--expires-days",type=int,default=90)
    rotate.add_argument("--output",required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=="init-password":
            initialize_password(args.password_file,args.output)
            print("Password saved to the requested private output file; a separate salted scrypt verifier was created. Neither value was printed.")
            return
        if args.command.startswith("key-"):
            registry=CredentialRegistry(args.registry,create=args.command=="key-issue")
            if args.command=="key-issue":
                value=registry.issue(customer_id=args.customer,name=args.name,workspace_id=args.workspace,backend_url=args.backend,workspace_root=args.workspace_root,output_file=args.output,scopes=tuple(args.scopes.split(",")),expires_days=args.expires_days)
                print(_json(value))
            elif args.command=="key-list":print(_json({"keys":registry.list_keys(args.customer)}))
            elif args.command=="key-revoke":registry.revoke(args.key_id);print("Customer key revoked; workspace binding retained.")
            elif args.command=="key-rotate":print(_json(registry.rotate(args.key_id,output_file=args.output,expires_days=args.expires_days)))
            return
        import fcntl
        config=Config(database=Path(args.state_file),password_file=Path(args.password_file),backend_url=args.backend,workspace_root=args.workspace_root,
                      auth_mode=args.auth_mode,credential_registry=Path(args.registry) if args.auth_mode=="customer" else None,
                      public_origin=args.public_origin,production=args.production,allow_operator_tools=args.allow_operator_tools)
        config.validate()
        Path(args.state_file).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        lock_fd=os.open(str(args.state_file)+".server.lock",os.O_CREAT|os.O_RDWR,0o600)
        try:
            fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            app=create_app(config)
            app[LEDGER_KEY].recover_interrupted()
            web.run_app(app,host="127.0.0.1",port=args.port,access_log=None,handler_cancellation=False)
        finally:os.close(lock_fd)
    except (APIError,CredentialError,ValueError,OSError) as error:parser.exit(2,str(error)+"\n")


if __name__=="__main__":main()
