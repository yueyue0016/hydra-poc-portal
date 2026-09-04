"""Azure ops skill: allocate a dynamic-sessions desktop sandbox and proxy to it.

All calls authenticate with the portal's managed identity (RBAC: 'Azure
ContainerApps Session Executor' on the session pool). The sandbox is the plain
hydra-desktop:v1 webtop image — no custom agents inside; documents are hosted
by the portal itself. Provisioning of ADDITIONAL Azure services is intentionally
manual: generated PoC plans tag such steps [REQUIRES USER AUTHORIZATION].
"""
import asyncio
from urllib.parse import urlencode

import httpx

from core import APIV, EXEC_TOKEN, POOL, pool_token

client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=30))


def pool_url(path: str, pid: str, extra: dict | None = None) -> str:
    q = {"api-version": APIV, "identifier": pid}
    if extra:
        q.update(extra)
    return f"{POOL}/{path}?{urlencode(q)}"


async def wait_desktop(pid: str, tries: int = 40) -> None:
    """Allocate (or reattach) the desktop session; wait until webtop serves HTTP 200."""
    last = ""
    for _ in range(tries):
        try:
            r = await client.get(pool_url("", pid),
                                 headers={"Authorization": f"Bearer {pool_token()}"},
                                 timeout=30)
            if r.status_code == 200:
                return
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = str(e)[:120]
        await asyncio.sleep(8)
    raise RuntimeError(f"sandbox startup timed out: {last}")


# ---------- in-sandbox tooling agent (exec / upload / install) ----------
def _agent_headers(extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {pool_token()}", "X-Exec-Token": EXEC_TOKEN}
    if extra:
        h.update(extra)
    return h


async def agent_health(pid: str) -> dict:
    r = await client.get(pool_url("agent/health", pid),
                         headers=_agent_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


async def exec_cmd(pid: str, cmd: str, timeout: int = 180,
                   workdir: str | None = None) -> dict:
    """Run a shell command inside the PoC sandbox (as root)."""
    r = await client.post(
        pool_url("agent/exec", pid), headers=_agent_headers(),
        json={"cmd": cmd, "timeout": timeout, "workdir": workdir},
        timeout=timeout + 40)
    r.raise_for_status()
    return r.json()


async def upload_bytes(pid: str, filename: str, data: bytes,
                       subdir: str | None = None) -> dict:
    """Drop a file onto the sandbox Desktop (optionally under a subdir)."""
    r = await client.post(
        pool_url("agent/upload", pid),
        headers=_agent_headers({"X-Filename": filename, "X-Subdir": subdir or ""}),
        content=data, timeout=300)
    r.raise_for_status()
    return r.json()


async def pkg_install(pid: str, packages: str, timeout: int = 300) -> dict:
    """Install additional apt packages inside the sandbox on demand."""
    cmd = ("export DEBIAN_FRONTEND=noninteractive && apt-get update && "
           f"apt-get install -y --no-install-recommends {packages}")
    return await exec_cmd(pid, cmd, timeout=timeout)
