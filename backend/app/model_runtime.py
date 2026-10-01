"""User-scoped model configuration and bounded Ollama model downloads."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import urljoin, urlsplit
import socket
import ipaddress
from uuid import uuid4

import httpx

from .config import get_settings


OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_INSTALL_URL = "https://ollama.com/download/windows"
SOURCES = (
    {"id": "ollama", "label": "Ollama 官方模型库", "host": "registry.ollama.ai"},
    {"id": "huggingface", "label": "Hugging Face", "host": "huggingface.co"},
    {"id": "hf-mirror", "label": "HF Mirror", "host": "hf-mirror.com"},
)
CATALOG = (
    {"id": "qwen3:0.6b", "label": "Qwen3 0.6B", "size_bytes": 396705472,
     "repo": "unsloth/Qwen3-0.6B-GGUF", "revision": "50968a4468ef4233ed78cd7c3de230dd1d61a56b",
     "file": "Qwen3-0.6B-Q4_K_M.gguf", "sha256": "ac2d97712095a558e31573f62f466a3f9d93990898b0ec79d7c974c1780d524a"},
    {"id": "qwen3:1.7b", "label": "Qwen3 1.7B", "size_bytes": 1107409472,
     "repo": "unsloth/Qwen3-1.7B-GGUF", "revision": "d7f544eead698dbd1f15126ef60b45a1e1933222",
     "file": "Qwen3-1.7B-Q4_K_M.gguf", "sha256": "b139949c5bd74937ad8ed8c8cf3d9ffb1e99c866c823204dc42c0d91fa181897"},
    {"id": "deepseek-r1:1.5b", "label": "DeepSeek R1 1.5B", "size_bytes": 1117321312,
     "repo": "unsloth/DeepSeek-R1-Distill-Qwen-1.5B-GGUF", "revision": "3cb4d15544a2a5e07439592b9a0965b6445fbd34",
     "file": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf", "sha256": "f3bdf9cf31dee4b57ae4e455a1cb0d01b5c2c1b50d72d3112141c195506c2840"},
)
_catalog = {row["id"]: row for row in CATALOG}
_lock = threading.RLock()
_jobs: dict[str, DownloadJob] = {}


class LocalModelError(RuntimeError):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


if os.name == "nt":
    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        return data
    source_buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    destination = _Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    func = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    func.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    func.restype = wintypes.BOOL
    if not func(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination)):
        raise OSError(ctypes.get_last_error(), "Windows credential protection failed")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(destination.pbData)


def _encrypt(value: str) -> str:
    prefix = "dpapi:" if os.name == "nt" else "plain:"
    return prefix + base64.b64encode(_dpapi(value.encode("utf-8"), True)).decode("ascii")


def _decrypt(value: str) -> str:
    prefix = "dpapi:" if os.name == "nt" else "plain:"
    if not value.startswith(prefix):
        raise ValueError("Saved model credential cannot be read on this computer")
    return _dpapi(base64.b64decode(value[len(prefix):], validate=True), False).decode("utf-8")


def _config_path() -> Path:
    settings = get_settings()
    # Keep the lightweight agent test doubles compatible with the runtime module.
    data_dir = getattr(settings, "data_dir", None)
    if data_dir is None:
        data_dir = Path(__file__).resolve().parents[1] / "data"
    return Path(data_dir) / "model-providers.json"


def _load() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid model configuration")
    return data


def _save(data: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".model-providers-", suffix=".tmp", delete=False) as stream:
            name = stream.name
            os.chmod(name, 0o600)
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _default(provider: str) -> dict:
    settings = get_settings()
    if provider == "qwen":
        return {"api_key": settings.qwen_api_key, "base_url": settings.qwen_base_url, "model": settings.qwen_model}
    if provider == "deepseek":
        return {"api_key": settings.deepseek_api_key, "base_url": settings.deepseek_base_url, "model": settings.deepseek_model}
    if provider == "ollama":
        return {"api_key": "", "base_url": OLLAMA_URL + "/v1", "model": "qwen3:0.6b"}
    raise ValueError("Unknown model provider")


def provider_settings(provider: str) -> dict:
    with _lock:
        stored = _load().get(provider, {})
    result = _default(provider)
    for field_name in ("base_url", "model"):
        if field_name in stored:
            result[field_name] = stored[field_name]
    if "api_key" in stored:
        result["api_key"] = _decrypt(stored["api_key"]) if stored["api_key"] else ""
    return result


def configuration() -> dict:
    providers = {}
    for provider in ("qwen", "deepseek"):
        current = provider_settings(provider)
        providers[provider] = {"configured": bool(current["api_key"]), "base_url": current["base_url"], "model": current["model"]}
    return {"providers": providers, "ollama": {"base_url": OLLAMA_URL, "model": provider_settings("ollama")["model"]}}


def _valid_base_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError("Invalid API address")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid API address") from exc
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None or port == 0
            or "\\" in value or parsed.query or parsed.fragment
            or parsed.path not in ("", "/", "/v1", "/compatible-mode/v1")):
        raise ValueError("API address must be an HTTPS provider root or /v1 endpoint")
    return value.rstrip("/")


def update_provider(provider: str, changes: dict) -> dict:
    if provider not in ("qwen", "deepseek", "ollama"):
        raise ValueError("Unknown model provider")
    with _lock:
        data = _load()
        current = dict(data.get(provider, {}))
        if provider == "ollama":
            if set(changes) - {"model"}:
                raise ValueError("Only the local model can be selected")
            model = changes.get("model")
            if not isinstance(model, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}", model):
                raise ValueError("Invalid local model name")
            current["model"] = model
        else:
            if changes.get("clear_api_key") and "api_key" in changes:
                raise ValueError("Cannot set and clear an API key together")
            if changes.get("clear_api_key"):
                current["api_key"] = ""
            if "api_key" in changes:
                key = changes["api_key"]
                if not isinstance(key, str) or not 1 <= len(key) <= 4096 or any(c in key for c in "\r\n\0"):
                    raise ValueError("Invalid API key")
                current["api_key"] = _encrypt(key)
            if "base_url" in changes:
                target_url = _valid_base_url(changes["base_url"])
                defaults = _default(provider)
                previous = urlsplit(_valid_base_url(current.get("base_url", defaults["base_url"])))
                target = urlsplit(target_url)
                authority_changed = (previous.hostname.lower(), previous.port or 443) != (target.hostname.lower(), target.port or 443)
                previous_key = data.get(provider, {}).get("api_key", defaults["api_key"])
                if authority_changed and previous_key and "api_key" not in changes and not changes.get("clear_api_key"):
                    raise ValueError("Changing the API host or port requires a new API key or clearing the saved key")
                current["base_url"] = target_url
            if "model" in changes:
                model = changes["model"]
                if not isinstance(model, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}", model):
                    raise ValueError("Invalid model name")
                current["model"] = model
        data[provider] = current
        _save(data)
    return configuration()


def test_provider(provider: str) -> dict:
    if provider == "ollama":
        current = provider_settings("ollama")
        try:
            response = httpx.post(OLLAMA_URL + "/api/show", json={"model": current["model"]}, timeout=10, trust_env=False)
            if response.status_code == 404:
                return {"ok": False, "error": "所选模型尚未下载"}
            response.raise_for_status()
            return {"ok": True}
        except httpx.HTTPError:
            return {"ok": False, "error": "无法连接本机 Ollama，请安装并启动 Ollama"}
    current = provider_settings(provider)
    if not current["api_key"]:
        return {"ok": False, "error": "请先填写 API Key"}
    try:
        response = httpx.post(current["base_url"].rstrip("/") + "/chat/completions",
                              headers={"Authorization": "Bearer " + current["api_key"]},
                              json={"model": current["model"], "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                              timeout=20, trust_env=False)
        if response.status_code in (401, 403):
            return {"ok": False, "error": "API Key 未通过服务商验证"}
        if response.status_code >= 400:
            return {"ok": False, "error": f"服务商返回 HTTP {response.status_code}；请检查模型名称和额度"}
        return {"ok": True}
    except httpx.HTTPError:
        return {"ok": False, "error": "无法连接模型服务商，请检查网络或 API 地址"}


def local_models() -> dict:
    installed = []
    running = False
    try:
        response = httpx.get(OLLAMA_URL + "/api/tags", timeout=2, trust_env=False)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise ValueError("Invalid Ollama model list")
        for row in payload["models"]:
            if (not isinstance(row, dict) or not isinstance(row.get("name"), str)
                    or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}", row["name"])):
                continue
            size = row.get("size", 0)
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                size = 0
            installed.append({"name": row["name"], "size_bytes": size})
        running = True
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        pass
    names = {row["name"] for row in installed}
    return {"running": running, "install_url": OLLAMA_INSTALL_URL, "selected_model": provider_settings("ollama")["model"],
            "installed": installed,
            "catalog": [{"id": row["id"], "label": row["label"], "size_bytes": row["size_bytes"],
                         "installed": row["id"] in names} for row in CATALOG], "sources": SOURCES}


def resolve_local_model(name: str | None = None) -> str:
    selected = name if name is not None else provider_settings("ollama")["model"]
    if not isinstance(selected, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}", selected):
        raise LocalModelError("本地模型名称无效，请重新选择模型", 422)
    available = local_models()
    if not available["running"]:
        raise LocalModelError("无法连接本机 Ollama，请安装并启动 Ollama 后重试")
    names = {row["name"] for row in available["installed"]}
    if selected in names:
        return selected
    if ":" not in selected.rsplit("/", 1)[-1] and selected + ":latest" in names:
        return selected + ":latest"
    raise LocalModelError("所选本地模型尚未安装或已被删除，请下载模型或在聊天窗口选择已安装模型", 409)


@dataclass
class DownloadJob:
    id: str
    model: str
    source: str
    status: str = "queued"
    progress: float = 0.0
    detail: str = "等待下载"
    error: str = ""
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self) -> dict:
        return {"id": self.id, "model": self.model, "source": self.source, "status": self.status,
                "progress": round(self.progress, 4), "detail": self.detail, "error": self.error}


def start_download(model: str, source: str) -> dict:
    if model not in _catalog or source not in {row["id"] for row in SOURCES}:
        raise ValueError("Unknown model or download source")
    with _lock:
        for job in _jobs.values():
            if job.model == model and job.status in {"queued", "downloading", "importing"}:
                return job.public()
        job = DownloadJob(str(uuid4()), model, source)
        _jobs[job.id] = job
    threading.Thread(target=_run_download, args=(job,), daemon=True, name="ollama-model-download").start()
    return job.public()


def get_download(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return job.public() if job else None


def cancel_download(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.cancel.set()
        return job.public() if job else None


def _run_download(job: DownloadJob) -> None:
    try:
        if job.cancel.is_set():
            job.status, job.detail = "cancelled", "下载已取消"
            return
        job.status = "downloading"
        if job.source == "ollama":
            _ollama_pull(job)
        else:
            _gguf_pull(job)
        if job.cancel.is_set():
            job.status, job.detail = "cancelled", "下载已取消"
        else:
            job.progress, job.status, job.detail = 1.0, "completed", "模型已安装"
    except Exception:
        if job.cancel.is_set():
            job.status, job.detail, job.error = "cancelled", "下载已取消", ""
        else:
            job.status, job.detail, job.error = "failed", "下载失败", "下载或导入失败，请检查网络、磁盘空间和 Ollama 状态"


def _ollama_events(response: httpx.Response, job: DownloadJob) -> None:
    """A closed or truncated stream is not proof that Ollama installed a model."""
    response.raise_for_status()
    succeeded = False
    for line in response.iter_lines():
        if job.cancel.is_set():
            return
        if not line:
            continue
        event = json.loads(line)
        if not isinstance(event, dict) or event.get("error"):
            raise ValueError("Ollama operation failed")
        total, completed = event.get("total", 0), event.get("completed", 0)
        if isinstance(total, (int, float)) and isinstance(completed, (int, float)) and total > 0:
            job.progress = max(0.0, min(0.99, completed / total))
        status = event.get("status")
        if isinstance(status, str):
            job.detail = status[:120]
            succeeded = status == "success"
    if not succeeded and not job.cancel.is_set():
        raise ValueError("Ollama ended without confirming installation")


def _ollama_pull(job: DownloadJob) -> None:
    with httpx.Client(timeout=httpx.Timeout(30, read=120), trust_env=False) as client:
        with client.stream("POST", OLLAMA_URL + "/api/pull", json={"model": job.model, "stream": True}) as response:
            _ollama_events(response, job)


def _download_target(url: str) -> tuple[str, str]:
    """Validate one redirect and pin its TLS connection to a checked public IP."""
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise ValueError("Invalid model download URL")
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid model download URL") from exc
    if (parsed.scheme != "https" or port not in (None, 443)
            or parsed.username is not None or parsed.password is not None or parsed.fragment
            or not re.fullmatch(r"[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)*", host)
            or not (host in {"huggingface.co", "hf-mirror.com"} or host.endswith(".hf.co"))):
        raise ValueError("Model download must use a trusted HTTPS host")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any("%" in row[4][0] or not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError("Model download resolved to a non-public address")
    except socket.gaierror as exc:
        raise ValueError("Model download host could not be resolved") from exc
    address = addresses[0][4][0]
    authority = f"[{address}]" if ":" in address else address
    return parsed._replace(netloc=authority).geturl(), host


def _gguf_pull(job: DownloadJob) -> None:
    spec = _catalog[job.model]
    host = "huggingface.co" if job.source == "huggingface" else "hf-mirror.com"
    url = f"https://{host}/{spec['repo']}/resolve/{spec['revision']}/{spec['file']}?download=true"
    directory = get_settings().data_dir / "model-downloads"
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / (job.id + ".gguf.part")
    digest = hashlib.sha256()
    received = 0
    try:
        with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(30, read=120), trust_env=False) as client:
            current_url = url
            for _ in range(5):
                if job.cancel.is_set():
                    return
                pinned_url, host = _download_target(current_url)
                # Host/SNI preserve TLS verification for the original host, while
                # a numeric connection URL prevents a second DNS resolution.
                with client.stream("GET", pinned_url, headers={"Host": host, "Accept-Encoding": "identity"},
                                   extensions={"sni_hostname": host}) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Model download redirect is missing location")
                        if any(ord(c) <= 32 or ord(c) == 127 for c in location):
                            raise ValueError("Invalid model download redirect")
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise ValueError("Model download did not return a complete file")
                    with tmp.open("xb") as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            if job.cancel.is_set():
                                return
                            received += len(chunk)
                            if received > spec["size_bytes"]:
                                raise ValueError("Model download exceeds pinned size")
                            digest.update(chunk)
                            output.write(chunk)
                            job.progress = min(0.8, received / spec["size_bytes"] * 0.8)
                            job.detail = f"正在下载 {received // 1048576} / {spec['size_bytes'] // 1048576} MB"
                    break
            else:
                raise ValueError("Too many model download redirects")
        if received != spec["size_bytes"] or digest.hexdigest() != spec["sha256"]:
            raise ValueError("Model checksum mismatch")
        if job.cancel.is_set():
            return
        job.status, job.detail = "importing", "正在导入 Ollama"
        blob = "sha256:" + spec["sha256"]
        def upload_chunks():
            with tmp.open("rb") as input_file:
                while chunk := input_file.read(1024 * 1024):
                    if job.cancel.is_set():
                        raise ValueError("Model import cancelled")
                    yield chunk

        with httpx.Client(timeout=httpx.Timeout(30, write=120, read=120), trust_env=False) as client:
            response = client.post(OLLAMA_URL + "/api/blobs/" + blob, content=upload_chunks(),
                                   headers={"Content-Type": "application/octet-stream", "Content-Length": str(received)})
            response.raise_for_status()
            if job.cancel.is_set():
                return
            with client.stream("POST", OLLAMA_URL + "/api/create", json={"model": job.model,
                               "files": {spec["file"]: blob}, "stream": True}) as response:
                _ollama_events(response, job)
    finally:
        tmp.unlink(missing_ok=True)
