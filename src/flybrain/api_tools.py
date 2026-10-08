"""Bounded, explicitly routed tool calls shared by local agents and the public API.

The viewer remains the authority for experiment option validation and scientific
provenance. There is deliberately no arbitrary URL, filesystem, or shell tool.
"""
from __future__ import annotations

import base64
import copy
import ipaddress
import json
import math
import re
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import aiohttp

IDENTIFIER = {"type": "string", "pattern": r"^[A-Za-z0-9_-]{1,160}$"}
OBJECT = {"type": "object", "description": "Cognesia native JSON options; inspect bootstrap and preview before running."}
EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_CHUNK_BYTES = 256 * 1024


class ToolError(Exception):
    def __init__(self, message, status=400, code="invalid_tool_request"):
        super().__init__(message)
        self.status, self.code = status, code


def schema(**properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


@dataclass(frozen=True)
class Tool:
    description: str
    path: str
    method: str = "GET"
    parameters: dict | None = None
    body: str | None = None
    query: tuple[str, ...] = ()
    operator_only: bool = False


def _tool(description, path, **kwargs):
    return Tool(description, path, **kwargs)


TOOLS = {
    "cognesia_bootstrap": _tool("Read model, allowed lab options, simulation limits, saved runs and validation failures. Recorded model output is not validated fly behaviour.", "/api/bootstrap"),
    "cognesia_models": _tool("List available model versions and their provenance.", "/api/models"),
    "cognesia_model": _tool("Read a model manifest and evidence.", "/api/models/{model_id}", parameters=schema(model_id=IDENTIFIER)),
    "cognesia_messengers": _tool("Read the evidence-tagged chemical messenger catalog; candidates are not automatically simulated.", "/api/messengers"),
    "cognesia_resources": _tool("Read the worker's resource limits and current activity.", "/api/resources"),
    "cognesia_neuron": _tool("Inspect one model neuron. Optional run_id resolves the recorded neuron ordering.", "/api/neuron/{index}", parameters={**schema(index={"type":"integer","minimum":0}, model_id=IDENTIFIER, run_id=IDENTIFIER), "required":["index", "model_id"]}, query=("model_id", "run_id")),
    "cognesia_region": _tool("List the neurons assigned to a named anatomical region.", "/api/regions/{region}", parameters=schema(region=IDENTIFIER)),
    "cognesia_peripheral": _tool("Read peripheral modules and their scientific assumptions.", "/api/peripheral", parameters=schema(model_id=IDENTIFIER), query=("model_id",)),
    "cognesia_eyes": _tool("Read a model's eye mapping and optical configuration.", "/api/model-eyes", parameters=schema(model_id=IDENTIFIER), query=("model_id",)),
    "cognesia_connectivity": _tool("Inspect native connectivity for a selection without advancing simulation time.", "/api/connectivity", method="POST", parameters=schema(options=OBJECT), body="options"),
    "cognesia_preview": _tool("Validate an experiment selection and estimate its work before starting it. Pass native Cognesia options.", "/api/selection/preview", method="POST", parameters=schema(options=OBJECT), body="options"),
    "cognesia_plan_replicates": _tool("Draft 1–50 deterministic replicate options from a master seed. Never starts experiments. Seed changes optical ray sampling, not individual flies; this does not create independent biological replication.", "/api/replicates/plan", method="POST", parameters=schema(plan={"type":"object","properties":{"master_seed":{"type":"integer","minimum":0,"maximum":4294967295},"replicates":{"type":"integer","minimum":1,"maximum":50},"options":OBJECT},"required":["master_seed","replicates","options"],"additionalProperties":False}), body="plan"),
    "cognesia_import_protocol": _tool("Parse an in-memory protocol document into native options. Does not execute it or read arbitrary files.", "/api/protocols/import", method="POST", parameters=schema(options=OBJECT), body="options"),
    "cognesia_start": _tool("Start one experiment with stimulus, neural/visual overrides, chemistry, timeline, interventions, selection, recording and seed options. Returns immediately with an experiment id; poll cognesia_session. Existing scientific gates still apply.", "/api/sessions", method="POST", parameters=schema(options=OBJECT), body="options"),
    "cognesia_sessions": _tool("List experiments belonging to this dedicated workspace.", "/api/sessions"),
    "cognesia_session": _tool("Read experiment progress, status and resulting run id.", "/api/sessions/{experiment_id}", parameters=schema(experiment_id=IDENTIFIER)),
    "cognesia_frame": _tool("Read the latest recorded experiment frame; does not advance time.", "/api/sessions/{experiment_id}/frame", parameters=schema(experiment_id=IDENTIFIER)),
    "cognesia_command": _tool("Pause, resume, advance a step, save a checkpoint, or gracefully stop an experiment. Stop saves recoverable state.", "/api/sessions/{experiment_id}/commands", method="POST", parameters=schema(experiment_id=IDENTIFIER, command={"type":"object","properties":{"action":{"type":"string","enum":["pause","resume","step","checkpoint","stop"]},"duration_ms":{"type":"number","minimum":0.025,"maximum":100},"label":{"type":"string","maxLength":160}},"required":["action"],"additionalProperties":False}), body="command"),
    "cognesia_cancel": _tool("Force-cancel a job. Prefer a graceful stop when recoverable state matters.", "/api/jobs/{experiment_id}/cancel", method="POST", parameters=schema(experiment_id=IDENTIFIER)),
    "cognesia_checkpoints": _tool("List the saved checkpoints in this workspace.", "/api/checkpoints"),
    "cognesia_branch": _tool("Prepare a reproducible branch from a checkpoint. Returns draft options; call cognesia_start explicitly to run the branch.", "/api/checkpoints/{checkpoint_id}/branches", method="POST", parameters=schema(checkpoint_id=IDENTIFIER, options=OBJECT), body="options"),
    "cognesia_runs": _tool("List completed recordings in this workspace, including warnings and evidence.", "/api/runs"),
    "cognesia_run_summary": _tool("Read recorded run dimensions, options, warnings, provenance and summary statistics.", "/api/runs/{run_id}/summary.json", parameters=schema(run_id=IDENTIFIER)),
    "cognesia_report_data": _tool("Read compact recorded evidence, sample counts, seed, warnings and available trace names for a report. Prefer this to the large full summary. Does not run an experiment.", "/api/runs/{run_id}/report-data", parameters=schema(run_id=IDENTIFIER)),
    "cognesia_capture_figure": _tool("Capture a chart snapshot from a saved numeric trace, with computed statistics and a PNG for the report. First inspect cognesia_report_data for exact trace names. This is numerical analysis of the plotted source data, not pixel vision. Population neurons and time samples are not biological replicates.", "/api/runs/{run_id}/report-figure", parameters=schema(run_id=IDENTIFIER, group={"type":"string","enum":["type","region","class"]}, trace={"type":"string","maxLength":160}, series={"type":"string","enum":["raw","baseline","delta"]}), query=("group","trace","series")),
    "cognesia_analyze_interval": _tool("Analyze original uniformly sampled data; Fourier fits summarize recordings, not biological governing laws.", "/api/analysis/interval", method="POST", parameters=schema(options=OBJECT), body="options"),
    "cognesia_save_workspace": _tool("Save native workspace notes, configuration and recordings into a portable archive. No external paths are accepted.", "/api/workspace-sessions", method="POST", parameters=schema(options=OBJECT), body="options"),
    "cognesia_morphology_status": _tool("Read morphology preparation status.", "/api/morphology/status"),
    "cognesia_morphology_neuron": _tool("Read an individual neuron's available morphology.", "/api/morphology/{index}", parameters=schema(index={"type":"integer","minimum":0})),
    "cognesia_morphology_overview": _tool("Read an overview at an advertised segment budget.", "/api/morphology/overview", parameters=schema(budget={"type":"integer","enum":[100000,500000,1000000,2000000,5000000]}), query=("budget",)),
    "cognesia_prepare_morphology": _tool("Prepare morphology assets for this workspace; operator must enable preparation.", "/api/morphology/prepare", method="POST", operator_only=True),
    "cognesia_prepare_model": _tool("Acquire BANC or compile the fused model. Operator must enable preparation and provision source credentials.", "/api/models/{operation}", method="POST", parameters=schema(operation={"type":"string","enum":["acquire-banc","compile-fused"]}), operator_only=True),
    "cognesia_model_job": _tool("Read a model preparation job.", "/api/models/jobs/{job_id}", parameters=schema(job_id=IDENTIFIER)),
    "cognesia_stop_all": _tool("Stop this workspace's running experiments and preparatory jobs.", "/api/stop-all", method="POST"),
    "cognesia_clear_cache": _tool("Clear rebuildable visualization caches in this dedicated workspace. Operator must enable maintenance.", "/api/cache/clear", method="POST", operator_only=True),
}

RUN_ASSETS = ("delta.bin", "raw.bin", "baseline.bin", "stimulus.bin", "eye_luminance.bin",
    "chemistry.bin", "chemistry_baseline.bin", "chemistry_state.bin", "chemistry_hormones.bin",
    "chemistry_baseline_state.bin", "chemistry_baseline_hormones.bin", "chemistry_plasticity.bin", "chemistry_baseline_plasticity.bin",
    "enzyme_pools.bin", "enzyme_baseline_pools.bin", "enzyme_flux.bin", "enzyme_baseline_flux.bin",
    "chemistry_membership_indptr.bin", "chemistry_membership_indices.bin", "chemistry_membership_weights.bin")
MORPHOLOGY_ASSETS = ("metadata.json", "vertices.bin", "edges.bin", "radius.bin", "positions.bin", "owners.bin")
ANATOMY_ASSETS = ("metadata.json", "positions.bin", "groups.bin", "visible_indices.bin", "identities.json", "regions.json")
TOOLS["cognesia_read_asset"] = _tool("Read a bounded base64 chunk of a recording, model anatomy or saved workspace archive. Use offsets until eof; shape and numeric types come from the run summary/anatomy metadata. No filesystem paths or external URLs.", "", parameters={**schema(kind={"type":"string","enum":["run","model_anatomy","run_anatomy","workspace","morphology_neuron","morphology_overview"]}, id=IDENTIFIER, asset={"type":"string","enum":list(dict.fromkeys((*RUN_ASSETS,*ANATOMY_ASSETS,*MORPHOLOGY_ASSETS,"archive")))}, partial={"type":"boolean","description":"Only for a morphology overview built from partially cached skeletons."}, offset={"type":"integer","minimum":0,"maximum":16*1024**3}, length={"type":"integer","minimum":1,"maximum":MAX_CHUNK_BYTES}),"required":["kind","id","asset"]})


def tool_schemas(*, allow_operator=True):
    return [{"type":"function", "function":{"name":name,"description":item.description,"parameters":copy.deepcopy(item.parameters or EMPTY)}}
            for name,item in TOOLS.items() if allow_operator or not item.operator_only]


def _validate(value, spec, path="arguments", depth=0):
    if depth > 32:
        raise ToolError("JSON nesting exceeds 32 levels")
    kind=spec.get("type")
    matches={"object":isinstance(value,dict), "array":isinstance(value,list), "string":isinstance(value,str),
             "integer":isinstance(value,int) and not isinstance(value,bool),
             "number":isinstance(value,(int,float)) and not isinstance(value,bool), "boolean":isinstance(value,bool)}
    if kind and not matches.get(kind,False):
        raise ToolError(f"{path} must be {kind}")
    if "enum" in spec and value not in spec["enum"]:
        raise ToolError(f"{path} must be one of {spec['enum']}")
    if isinstance(value,dict):
        props=spec.get("properties",{})
        if set(spec.get("required",()))-value.keys():
            raise ToolError(f"{path} missing required fields: {sorted(set(spec['required'])-value.keys())}")
        if spec.get("additionalProperties") is False and value.keys()-props.keys():
            raise ToolError(f"{path} contains unknown fields")
        for key, child in value.items():
            if not isinstance(key,str) or len(key)>256:
                raise ToolError("Invalid JSON object key")
            _validate(child,props.get(key,{}),path+"."+key,depth+1)
    elif isinstance(value,list):
        if len(value)>1000000:
            raise ToolError("Array exceeds one million items")
        for child in value:
            _validate(child,spec.get("items",{}),path+"[]",depth+1)
    elif isinstance(value,str):
        if len(value)>spec.get("maxLength",1024*1024):
            raise ToolError(f"{path} is too long")
        if spec.get("pattern") and not re.fullmatch(spec["pattern"],value):
            raise ToolError(f"{path} is not a valid identifier")
    elif isinstance(value,(int,float)) and not isinstance(value,bool):
        try: finite=math.isfinite(value)
        except OverflowError: finite=False
        if not finite or value<spec.get("minimum",-math.inf) or value>spec.get("maximum",math.inf):
            raise ToolError(f"{path} is outside allowed numeric bounds")
    elif value is not None and not isinstance(value,bool):
        raise ToolError(f"{path} must contain JSON values")


def validate_tool(name, arguments, *, allow_operator=True):
    if not isinstance(name,str) or name not in TOOLS:
        raise ToolError("Unknown Cognesia tool",404,"unknown_tool")
    item=TOOLS[name]
    if item.operator_only and not allow_operator:
        raise ToolError("This tool requires operator-enabled model preparation or maintenance",403,"operator_only")
    _validate(arguments,item.parameters or EMPTY)
    if name=="cognesia_read_asset":
        allowed={"run":RUN_ASSETS,"model_anatomy":ANATOMY_ASSETS,"run_anatomy":ANATOMY_ASSETS,"workspace":("archive",),"morphology_neuron":("metadata.json","vertices.bin","edges.bin","radius.bin"),"morphology_overview":("metadata.json","positions.bin","owners.bin")}
        if arguments["asset"] not in allowed[arguments["kind"]]:
            raise ToolError("Asset does not belong to the requested kind")
        if arguments["kind"]=="morphology_neuron" and not re.fullmatch(r"[0-9]{1,7}",arguments["id"]):
            raise ToolError("Morphology neuron id must be a model index")
        if arguments["kind"]=="morphology_overview" and arguments["id"] not in ("100000","500000","1000000","2000000","5000000"):
            raise ToolError("Morphology overview id must be an advertised segment budget")
        if arguments.get("partial") and arguments["kind"]!="morphology_overview":
            raise ToolError("partial only applies to morphology overviews")
    return item


def validate_backend_url(url):
    parsed=urlsplit(url)
    try: loopback=ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError: loopback=False
    if parsed.scheme!="http" or not loopback or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Backends must be numeric loopback HTTP origins without credentials, paths or queries")
    if parsed.port is None:
        raise ValueError("Backend must specify its dedicated port")
    return url.rstrip("/")


def build_tool_request(name, arguments):
    item=validate_tool(name,arguments)
    if name=="cognesia_read_asset":
        kind,identifier,asset=arguments["kind"],arguments["id"],arguments["asset"]
        path={"run":f"/api/runs/{identifier}/{asset}","model_anatomy":f"/api/model-anatomy/{identifier}/{asset}",
              "run_anatomy":f"/api/runs/{identifier}/anatomy/{asset}","workspace":f"/api/workspace-sessions/{identifier}/download",
              "morphology_neuron":f"/api/morphology/assets/neurons/{identifier}/{asset}",
              "morphology_overview":f"/api/morphology/assets/overview/{identifier}/"+("partial/" if arguments.get("partial") else "")+asset}[kind]
    else:
        path=item.path.format(**arguments)
    params={key:arguments[key] for key in item.query if key in arguments}
    if params:path+="?"+urlencode(params)
    return item.method,path,arguments[item.body] if item.body else ({} if item.method=="POST" else None)


async def execute_tool(name, arguments, base_url, session=None, *, allow_operator=True, timeout=45, worker_headers=None):
    """Execute an allowlisted tool against a trusted loopback viewer.

    A provided aiohttp session is reused without ambient cookies, proxies or
    redirects. Only explicit allowlisted worker_headers carry the private local
    capability or the research agent's authenticated viewer session; tool
    arguments cannot choose credentials or arbitrary URLs.
    """
    validate_tool(name,arguments,allow_operator=allow_operator)
    base_url=validate_backend_url(base_url)
    method,path,body=build_tool_request(name,arguments)
    own=session is None
    if own:session=aiohttp.ClientSession(trust_env=False, cookie_jar=aiohttp.DummyCookieJar())
    headers=dict(worker_headers or {})
    if set(headers) - {"Cookie", "Origin", "X-Cognesia-CSRF", "X-Cognesia-Internal", "X-Cognesia-Customer", "X-Cognesia-Workspace", "X-Cognesia-Scopes"}:
        raise ToolError("Invalid internal worker credentials")
    offset=arguments.get("offset",0);length=arguments.get("length",MAX_CHUNK_BYTES)
    binary=name=="cognesia_read_asset"
    if binary:headers["Range"]=f"bytes={offset}-{offset+length-1}"
    try:
        async with session.request(method,base_url+path,json=body,headers=headers,allow_redirects=False,timeout=aiohttp.ClientTimeout(total=timeout)) as response:
            maximum=length if binary and response.status<300 else MAX_JSON_BYTES
            if 300<=response.status<400:
                raise ToolError("Worker redirects are not allowed",502,"backend_redirect")
            if binary and response.status==200 and offset:
                raise ToolError("Worker does not support ranged asset reads",502,"range_unsupported")
            if response.content_length is not None and response.content_length>maximum:
                raise ToolError("Worker response exceeds the bounded tool output; use a smaller selection or asset chunks",502,"response_too_large")
            chunks=[];size=0
            async for chunk in response.content.iter_chunked(min(maximum+1,65536)):
                size+=len(chunk)
                if size>maximum:raise ToolError("Worker response exceeds the bounded tool output",502,"response_too_large")
                chunks.append(chunk)
            data=b"".join(chunks)
            if response.status>=400:
                try: message=json.loads(data).get("error","Worker rejected the request")
                except (ValueError,AttributeError):message="Worker rejected the request"
                raise ToolError(str(message),response.status,"backend_error")
            if binary:
                content_range=response.headers.get("Content-Range","")
                match=re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",content_range)
                if response.status==206 and (not match or int(match[1])!=offset or int(match[2])-int(match[1])+1!=len(data)):
                    raise ToolError("Worker returned an invalid asset range",502,"invalid_range")
                total=int(match[3]) if match else len(data)
                return {"encoding":"base64","data":base64.b64encode(data).decode("ascii"),"offset":offset,"length":len(data),"total_bytes":total,"next_offset":offset+len(data),"eof":offset+len(data)>=total}
            try: return json.loads(data)
            except ValueError:raise ToolError("Worker did not return JSON",502,"backend_format") from None
    except (aiohttp.ClientError,TimeoutError):
        raise ToolError("Worker request failed or timed out; inspect experiment state before issuing a new mutation",504,"backend_unavailable") from None
    finally:
        if own:await session.close()
