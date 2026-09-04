"""Core: config, Entra credentials, AOAI client, JSON store."""
import json
import os
import threading
import time

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

POOL = os.environ["POOL_ENDPOINT"].rstrip("/")
APIV = os.environ.get("POOL_API_VERSION", "2025-10-02-preview")
AOAI_EP = os.environ["AOAI_ENDPOINT"]
AOAI_DEP = os.environ.get("AOAI_DEPLOYMENT", "gpt-4o")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "changeme")
EXEC_TOKEN = os.environ.get("EXEC_TOKEN", "")
DATA = os.environ.get("DATA_DIR", "/app/data")
os.makedirs(DATA, exist_ok=True)

cred = DefaultAzureCredential()
_ptok = {"v": None, "exp": 0}
_lock = threading.Lock()

aoai = AzureOpenAI(
    azure_endpoint=AOAI_EP,
    azure_ad_token_provider=get_bearer_token_provider(
        cred, "https://cognitiveservices.azure.com/.default"),
    api_version="2024-06-01",
)


def pool_token() -> str:
    """Entra token for dynamic sessions data plane (portal managed identity)."""
    with _lock:
        if time.time() > _ptok["exp"] - 300:
            t = cred.get_token("https://dynamicsessions.io/.default")
            _ptok.update(v=t.token, exp=t.expires_on)
        return _ptok["v"]


def llm(system: str, user: str, max_tokens: int = 2600, temp: float = 0.4) -> str:
    r = aoai.chat.completions.create(
        model=AOAI_DEP,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=temp, max_tokens=max_tokens)
    return r.choices[0].message.content or ""


# ---------- tiny JSON store ----------
def _dbp():
    return os.path.join(DATA, "pocs.json")


def db_all() -> dict:
    with _lock:
        if not os.path.exists(_dbp()):
            return {}
        with open(_dbp(), encoding="utf-8") as f:
            return json.load(f)


def db_save(pid: str, rec: dict):
    with _lock:
        d = {}
        if os.path.exists(_dbp()):
            with open(_dbp(), encoding="utf-8") as f:
                d = json.load(f)
        d[pid] = rec
        with open(_dbp(), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)


def get_poc(pid: str) -> dict | None:
    return db_all().get(pid)


def set_status(pid: str, status: str, step: str):
    rec = get_poc(pid)
    if rec:
        rec["status"] = status
        rec["step"] = step
        rec["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        db_save(pid, rec)


def poc_dir(pid: str) -> str:
    p = os.path.join(DATA, pid)
    os.makedirs(p, exist_ok=True)
    return p


# ---------- knowledge base store ----------
def _kbp():
    return os.path.join(DATA, "knowledge.json")


def kb_all() -> dict:
    with _lock:
        if not os.path.exists(_kbp()):
            return {"entries": {}}
        with open(_kbp(), encoding="utf-8") as f:
            return json.load(f)


def kb_merge(pid: str, items: list):
    """Merge harvested skill/tool entries; dedupe by name, accumulate PoC ids."""
    with _lock:
        d = {"entries": {}}
        if os.path.exists(_kbp()):
            with open(_kbp(), encoding="utf-8") as f:
                d = json.load(f)
        ent = d.setdefault("entries", {})
        for it in items:
            key = it["name"].strip().lower()
            e = ent.get(key)
            if e:
                if pid not in e["pocs"]:
                    e["pocs"].append(pid)
            else:
                ent[key] = {"name": it["name"], "category": it["category"],
                            "scenario": it["scenario"], "pocs": [pid]}
        d["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_kbp(), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
