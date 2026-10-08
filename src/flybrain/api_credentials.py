"""Offline-managed customer keys and immutable private-workspace bindings.

Keys contain 256 CSPRNG bits. Only SHA-256 verifiers enter the registry; plaintext
is written once to an explicitly chosen mode-0600 output. Revoked bindings are
retained so a later customer cannot inherit another customer's worker or history.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit
import time

from .api_tools import validate_backend_url

IDENTITY=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
KEY_PATTERN=re.compile(r"^cgnk_([a-f0-9]{32})\.([A-Za-z0-9_-]{43})$")
MUTABLE_DIRECTORIES=("runs","sessions","checkpoints","boundaries","build")
READ_TOOLS=frozenset({
    "cognesia_bootstrap","cognesia_models","cognesia_model","cognesia_messengers","cognesia_resources",
    "cognesia_neuron","cognesia_region","cognesia_peripheral","cognesia_eyes","cognesia_connectivity",
    "cognesia_preview","cognesia_plan_replicates","cognesia_import_protocol","cognesia_sessions",
    "cognesia_session","cognesia_frame","cognesia_checkpoints","cognesia_branch","cognesia_runs",
    "cognesia_run_summary","cognesia_report_data","cognesia_capture_figure","cognesia_analyze_interval",
    "cognesia_morphology_status","cognesia_morphology_neuron","cognesia_morphology_overview",
    "cognesia_model_job","cognesia_read_asset",
})
RUN_TOOLS=frozenset({"cognesia_start","cognesia_command","cognesia_cancel","cognesia_stop_all","cognesia_save_workspace"})


class CredentialError(Exception):
    def __init__(self,message,status=400,code="credential_error"):
        super().__init__(message)
        self.status,self.code=status,code


def workspace_fingerprint(root):
    """Opaque binding used by a loopback worker's health endpoint; no path returned."""
    return hashlib.sha256(("cognesia-workspace-v1\0"+str(Path(root).resolve())).encode()).hexdigest()


def scope_for_tool(name):
    return "read" if name in READ_TOOLS else "run" if name in RUN_TOOLS else None


def _scopes(value):
    scopes=tuple(sorted(set(value)))
    if "read" not in scopes or set(scopes)-{"read","run"}:
        raise CredentialError("Scopes must include read and may additionally include run")
    return scopes


def _utc(timestamp):
    return datetime.fromtimestamp(timestamp,timezone.utc).isoformat().replace("+00:00","Z")


def _identity(value,label):
    if not isinstance(value,str) or not IDENTITY.fullmatch(value):raise CredentialError(f"Invalid {label}; use 1–80 letters, digits, underscores or hyphens")
    return value


@dataclass(frozen=True)
class Principal:
    customer_id: str
    customer_name: str
    workspace_id: str
    backend_url: str
    workspace_fingerprint: str
    scopes: tuple[str,...]
    key_id: str
    expires_at: float

    @property
    def namespace(self):
        return "customer_"+hashlib.sha256((self.customer_id+"\0"+self.workspace_id).encode()).hexdigest()

    def public_access(self):
        return {"authenticated":True,"authentication":"customer_key","billing":False,
                "customer":{"id":self.customer_id,"name":self.customer_name},
                "workspace":{"id":self.workspace_id},"scopes":list(self.scopes),"expires_at":_utc(self.expires_at)}


class CredentialRegistry:
    def __init__(self,path,*,create=False):
        self.path=Path(path)
        if create:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd=os.open(self.path,os.O_CREAT|os.O_RDWR,0o600);os.close(fd)
        if not self.path.is_file():raise ValueError("Customer credential registry does not exist; issue keys offline first")
        if self.path.stat().st_mode&0o077:raise ValueError("Customer registry must have private permissions (chmod 600)")
        if create:
            with self.connect(write=True) as db:
                existing={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if existing-{"customer_workspaces","customer_keys"}:raise ValueError("Credential registry contains an unrelated schema")
                db.execute("CREATE TABLE IF NOT EXISTS customer_workspaces(customer_id TEXT PRIMARY KEY,customer_name TEXT NOT NULL,workspace_id TEXT UNIQUE NOT NULL,backend_url TEXT UNIQUE NOT NULL,backend_port INTEGER UNIQUE NOT NULL,workspace_root TEXT UNIQUE NOT NULL,workspace_fingerprint TEXT NOT NULL,created REAL NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS customer_keys(id TEXT PRIMARY KEY,verifier TEXT UNIQUE NOT NULL,customer_id TEXT NOT NULL REFERENCES customer_workspaces(customer_id),scopes TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,revoked REAL)")
                db.execute("CREATE INDEX IF NOT EXISTS customer_keys_customer ON customer_keys(customer_id)")
        with self.connect() as db:
            if {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}!={"customer_workspaces","customer_keys"}:
                raise ValueError("Customer registry schema is incomplete")

    @contextmanager
    def connect(self,write=False):
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None)
        db.row_factory=sqlite3.Row;db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:db.execute("BEGIN IMMEDIATE")
            yield db
            if write:db.commit()
        except BaseException:
            if write:db.rollback()
            raise
        finally:db.close()

    @staticmethod
    def _binding(db,customer_id,name,workspace_id,backend_url,workspace_root):
        _identity(customer_id,"customer identity");_identity(workspace_id,"workspace identity")
        if not isinstance(name,str) or not 1<=len(name)<=120 or any(ord(c)<32 or ord(c)==127 for c in name):raise CredentialError("Customer name must be 1–120 printable characters")
        backend_url=validate_backend_url(backend_url);port=urlsplit(backend_url).port
        root=Path(workspace_root).resolve()
        if not root.is_dir():raise CredentialError("Workspace root must be an existing dedicated directory")
        for directory in MUTABLE_DIRECTORIES:
            resolved=(root/directory).resolve()
            if not resolved.is_relative_to(root):raise CredentialError("Mutable workspace directories must not point outside the dedicated root")
        previous=db.execute("SELECT * FROM customer_workspaces WHERE customer_id=?",(customer_id,)).fetchone()
        if previous:
            if (previous["workspace_id"],previous["backend_url"],previous["workspace_root"],previous["customer_name"])!=(workspace_id,backend_url,str(root),name):
                raise CredentialError("Existing customer workspace binding is immutable; use its original identity and dedicated backend")
            return
        if db.execute("SELECT COUNT(*) FROM customer_workspaces").fetchone()[0]>=10000:raise CredentialError("Registry customer capacity reached",503,"registry_capacity")
        for other in db.execute("SELECT * FROM customer_workspaces"):
            other_root=Path(other["workspace_root"])
            if other["workspace_id"]==workspace_id or other["backend_port"]==port or root.is_relative_to(other_root) or other_root.is_relative_to(root):
                raise CredentialError("A customer cannot share another customer's workspace identity, worker port or overlapping root",409,"workspace_conflict")
        db.execute("INSERT INTO customer_workspaces VALUES(?,?,?,?,?,?,?,?)",(customer_id,name,workspace_id,backend_url,port,str(root),workspace_fingerprint(root),time.time()))

    @staticmethod
    def _write_key(db,customer_id,scopes,expires_days,output_file,rotate_id=None):
        scopes=_scopes(scopes)
        if type(expires_days) is not int or not 1<=expires_days<=3650:raise CredentialError("Expiry must be 1–3650 days")
        if db.execute("SELECT COUNT(*) FROM customer_keys").fetchone()[0]>=100000:raise CredentialError("Registry key capacity reached",503,"registry_capacity")
        key_id=secrets.token_hex(16);token="cgnk_"+key_id+"."+secrets.token_urlsafe(32)
        now=time.time();expires=now+expires_days*86400
        db.execute("INSERT INTO customer_keys VALUES(?,?,?,?,?,?,NULL)",(key_id,hashlib.sha256(token.encode()).hexdigest(),customer_id,json.dumps(scopes),now,expires))
        if rotate_id:db.execute("UPDATE customer_keys SET revoked=? WHERE id=?",(now,rotate_id))
        workspace=db.execute("SELECT workspace_id FROM customer_workspaces WHERE customer_id=?",(customer_id,)).fetchone()[0]
        output={"api_key":token,"key_id":key_id,"customer_id":customer_id,"workspace_id":workspace,"scopes":list(scopes),"expires_at":_utc(expires)}
        path=Path(output_file);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,"w") as stream:
                json.dump(output,stream,indent=2);stream.write("\n");stream.flush();os.fsync(stream.fileno())
        except BaseException:
            path.unlink(missing_ok=True);raise
        return {key:value for key,value in output.items() if key!="api_key"}

    def issue(self,*,customer_id,name,workspace_id,backend_url,workspace_root,output_file,scopes=("read",),expires_days=90):
        output=Path(output_file)
        if output.resolve()==self.path.resolve():raise CredentialError("Key output must be separate from its verifier registry")
        written=False
        try:
            with self.connect(write=True) as db:
                self._binding(db,customer_id,name,workspace_id,backend_url,workspace_root)
                result=self._write_key(db,customer_id,scopes,expires_days,output)
                written=True
            return result
        except BaseException:
            if written:output.unlink(missing_ok=True)
            raise

    def rotate(self,key_id,*,output_file,expires_days=90):
        if not isinstance(key_id,str) or not re.fullmatch(r"[a-f0-9]{32}",key_id):raise CredentialError("Invalid key identity")
        output=Path(output_file)
        if output.resolve()==self.path.resolve():raise CredentialError("Key output must be separate from its verifier registry")
        written=False
        try:
            with self.connect(write=True) as db:
                old=db.execute("SELECT * FROM customer_keys WHERE id=?",(key_id,)).fetchone()
                if old is None or old["revoked"] is not None:raise CredentialError("Key is unavailable or already revoked",404,"key_unavailable")
                result=self._write_key(db,old["customer_id"],json.loads(old["scopes"]),expires_days,output,rotate_id=key_id)
                written=True
            return result
        except BaseException:
            if written:output.unlink(missing_ok=True)
            raise

    def revoke(self,key_id):
        if not isinstance(key_id,str) or not re.fullmatch(r"[a-f0-9]{32}",key_id):raise CredentialError("Invalid key identity")
        with self.connect(write=True) as db:
            if db.execute("UPDATE customer_keys SET revoked=COALESCE(revoked,?) WHERE id=?",(time.time(),key_id)).rowcount!=1:
                raise CredentialError("Unknown key",404,"key_unavailable")

    def list_keys(self,customer_id=None):
        if customer_id is not None:_identity(customer_id,"customer identity")
        with self.connect() as db:
            rows=db.execute("SELECT k.id,k.customer_id,k.scopes,k.created,k.expires,k.revoked,w.customer_name,w.workspace_id FROM customer_keys k JOIN customer_workspaces w ON w.customer_id=k.customer_id"+(" WHERE k.customer_id=?" if customer_id else "")+" ORDER BY k.created",(customer_id,) if customer_id else ()).fetchall()
        now=time.time()
        return [{"key_id":row["id"],"customer":{"id":row["customer_id"],"name":row["customer_name"]},"workspace":{"id":row["workspace_id"]},"scopes":json.loads(row["scopes"]),"created_at":_utc(row["created"]),"expires_at":_utc(row["expires"]),"status":"revoked" if row["revoked"] is not None else "expired" if row["expires"]<=now else "active"} for row in rows]

    def authenticate(self,token):
        matched=KEY_PATTERN.fullmatch(token) if isinstance(token,str) and len(token)<=128 else None
        if not matched:raise CredentialError("A valid customer API key is required",401,"unauthorized")
        digest=hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row=db.execute("SELECT k.*,w.customer_name,w.workspace_id,w.backend_url,w.workspace_fingerprint FROM customer_keys k JOIN customer_workspaces w ON w.customer_id=k.customer_id WHERE k.id=?",(matched[1],)).fetchone()
        valid=hmac.compare_digest(digest,row["verifier"] if row else "0"*64)
        if not valid or row is None or row["revoked"] is not None or row["expires"]<=time.time():
            raise CredentialError("A valid customer API key is required",401,"unauthorized")
        return Principal(row["customer_id"],row["customer_name"],row["workspace_id"],row["backend_url"],row["workspace_fingerprint"],tuple(json.loads(row["scopes"])),row["id"],row["expires"])
