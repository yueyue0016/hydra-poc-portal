"""Hydra PoC Portal — sales-facing AI PoC automation on ACA dynamic sessions.

Flow: sales submit -> admin approval -> agent pipeline (skills: research/poc/
azureops) -> portal hosts the document pack & demo site -> a clean XFCE desktop
sandbox (plain hydra-desktop image) is allocated from the session pool -> sales
page shows the AE endpoint + password; AE gets doc viewer, demo site & desktop.
"""
import asyncio
import os
import secrets
import time
from urllib.parse import urlencode

import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import (HTMLResponse, PlainTextResponse,
                               RedirectResponse, Response)

from core import (ADMIN_TOKEN, APIV, POOL, db_all, db_save, get_poc, kb_all,
                  poc_dir, pool_token, set_status)
from skills import (azureops, knowledge, media as mediaskill,
                    mediaproc, poc as pocskill, research)

app = FastAPI()

DOCS = ["01-customer-research.md", "02-industry-research.md",
        "03-solution-proposal.md", "04-poc-plan.md"]
DEMO = "05-demo-site.html"


# ---------- orchestrator ----------
def write_doc(pid: str, name: str, content: str):
    with open(os.path.join(poc_dir(pid), name), "w", encoding="utf-8") as f:
        f.write(content)


def read_doc(pid: str, name: str) -> str:
    with open(os.path.join(poc_dir(pid), name), encoding="utf-8") as f:
        return f.read()


def readme_md(pid: str, rec: dict) -> str:
    return f"""# PoC Package — {rec['customer']}

- PoC ID: `{pid}`
- Industry: {rec['industry']}
- Generated: {time.strftime('%Y-%m-%d %H:%M')}
- Sandbox: Azure Container Apps **dynamic sessions** (Hyper-V isolated XFCE
  desktop, allocated in seconds, auto-destroyed when idle)

## Contents
1. `01-customer-research.md` — Customer Research Report
2. `02-industry-research.md` — Industry Research Report
3. `03-solution-proposal.md` — Solution Proposal
4. `04-poc-plan.md` — PoC Implementation Plan
5. `05-demo-site.html` — interactive PoC demo site

## How to use (AE)
- View documents and the demo site directly in this portal.
- "Open desktop" attaches to the customer-dedicated sandbox: an XFCE desktop
  with Chrome / FileZilla / CLI tools for running and showing the PoC.
- The sandbox is destroyed automatically after idling; reopening this page
  allocates a fresh one in seconds. Documents stay hosted by the portal.
- Steps in the PoC plan that provision extra Azure services are tagged
  [REQUIRES USER AUTHORIZATION] — obtain approval before running them.

> AI-generated content — verify facts and figures before customer use.
> For internal pre-sales use only.
"""


async def pipeline(pid: str):
    rec = get_poc(pid)
    c, i, s = rec["customer"], rec["industry"], rec["scenario"]

    def missing(name: str) -> bool:
        return not os.path.exists(os.path.join(poc_dir(pid), name))

    try:
        if missing(DOCS[0]):
            set_status(pid, "running", "1/6 [research skill] customer research")
            write_doc(pid, DOCS[0],
                      await asyncio.to_thread(research.customer_research, c, i, s))
        cust = read_doc(pid, DOCS[0])

        if missing(DOCS[1]):
            set_status(pid, "running", "2/6 [research skill] industry research")
            write_doc(pid, DOCS[1],
                      await asyncio.to_thread(research.industry_research, c, i))

        if missing(DOCS[2]):
            set_status(pid, "running", "3/6 [poc skill] drafting solution proposal")
            write_doc(pid, DOCS[2],
                      await asyncio.to_thread(pocskill.solution_proposal, c, i, s, cust))
        prop = read_doc(pid, DOCS[2])

        if missing(DOCS[3]):
            set_status(pid, "running", "4/6 [poc skill] drafting PoC implementation plan")
            write_doc(pid, DOCS[3],
                      await asyncio.to_thread(pocskill.poc_plan, c, s, prop))

        if missing(DEMO):
            set_status(pid, "running", "5/6 [poc skill] generating demo site")
            write_doc(pid, DEMO,
                      await asyncio.to_thread(pocskill.demo_site, c, i, s, prop))

        write_doc(pid, "00-README.md", readme_md(pid, rec))

        set_status(pid, "running",
                   "6/7 [azureops skill] allocating dynamic-sessions desktop sandbox")
        await azureops.wait_desktop(pid)

        set_status(pid, "running",
                   "7/7 [media skill] running sandbox tools, placing outputs on the desktop")
        tools_md = await run_tooling(pid, get_poc(pid))
        write_doc(pid, "06-sandbox-tools.md", tools_md)

        files = ["00-README.md"] + DOCS + [DEMO, "06-sandbox-tools.md"]

        rec = get_poc(pid)
        if rec.get("uploads"):
            set_status(pid, "running",
                       "8/8 [media skill] processing uploaded files in the sandbox")
            proc_md = await process_uploads_step(pid, rec)
            write_doc(pid, "07-uploads-processing.md", proc_md)
            files.append("07-uploads-processing.md")

        rec = get_poc(pid)
        rec["files"] = files
        rec["status"], rec["step"] = "ready", "completed"
        rec["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        db_save(pid, rec)

        # knowledge harvest (best-effort; never affects the ready status)
        try:
            await asyncio.to_thread(knowledge.harvest, pid, prop,
                                    read_doc(pid, DOCS[3]))
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        set_status(pid, "failed", f"failed: {str(e)[:400]}")


async def run_tooling(pid: str, rec: dict) -> str:
    """Step 7: exercise the sandbox toolchain and drop artifacts on the Desktop.
    Best-effort — returns a Markdown report; never raises."""
    lines = ["# Sandbox Tools & Desktop Outputs", "",
             "The agent ran real tools **inside this PoC's dynamic-sessions "
             "sandbox** and placed the results on the remote Desktop, so the "
             "requester can open them directly.", ""]
    try:
        health = await azureops.agent_health(pid)
        lines.append("## Toolchain detected in the sandbox")
        for t, ok in health.get("tools", {}).items():
            lines.append(f"- {'✅' if ok else '❌'} `{t}`")
        lines.append("")
    except Exception as e:  # noqa: BLE001
        return ("# Sandbox Tools\n\nThe in-sandbox tooling agent was not "
                f"reachable: `{e}`.\n\nThe desktop itself is still available.\n")

    try:
        steps = await mediaskill.produce_desktop_assets(
            pid, rec["customer"], rec["industry"])
        lines.append("## Media generated on the Desktop → `PoC-Outputs/`")
        lines.append("Produced with ffmpeg + ImageMagick, driven by the agent:")
        for name, code in steps:
            lines.append(f"- {'✅' if code == 0 else '⚠️'} `{name}` (exit {code})")
        lines.append("")
    except Exception as e:  # noqa: BLE001
        lines.append(f"## Media generation\n\n- ⚠️ {e}\n")

    try:
        n = 0
        for name in ["00-README.md"] + DOCS + [DEMO]:
            p = os.path.join(poc_dir(pid), name)
            if os.path.exists(p):
                with open(p, "rb") as f:
                    await azureops.upload_bytes(pid, name, f.read(),
                                                subdir="PoC-Package")
                n += 1
        lines.append(f"## Document pack copied to the Desktop → `PoC-Package/` "
                     f"({n} files)")
        lines.append("")
    except Exception as e:  # noqa: BLE001
        lines.append(f"## Document copy\n\n- ⚠️ {e}\n")

    lines.append("> Open **🖥️ Remote desktop**: the folders **PoC-Outputs/** "
                 "(agent-produced media) and **PoC-Package/** (the document "
                 "pack) are on the desktop. The agent can also install and run "
                 "additional CLI tools on demand (e.g. `apt-get install …`).")
    return "\n".join(lines)


async def process_uploads_step(pid: str, rec: dict) -> str:
    """Push the requester's uploaded files into the sandbox and let the agent
    install tools + process them per the scenario. Returns a Markdown report."""
    updir = os.path.join(poc_dir(pid), "uploads")
    names = rec.get("uploads", [])
    lines = ["# Uploaded Files — Sandbox Processing", "",
             "The requester's uploaded files were pushed into the sandbox "
             "(`Desktop/Uploads/`), then the agent installed any needed tools "
             "and processed them per the scenario.", "", f"## Uploaded ({len(names)})"]
    pushed = []
    for n in names:
        p = os.path.join(updir, n)
        if not os.path.exists(p):
            continue
        try:
            with open(p, "rb") as f:
                await azureops.upload_bytes(pid, n, f.read(), subdir="Uploads")
            pushed.append(n)
            lines.append(f"- `{n}`")
        except Exception as e:  # noqa: BLE001
            lines.append(f"- ⚠️ `{n}` upload failed: {e}")
    lines.append("")
    if not pushed:
        lines.append("_No files were pushed._")
        return "\n".join(lines)
    try:
        res = await mediaproc.process(pid, rec["scenario"], pushed)
        lines.append("## Agent-generated processing script")
        lines.append("```bash\n" + res["script"][:2500] + "\n```")
        lines.append(f"\n## Result (exit {res['code']})")
        if res.get("outputs"):
            lines.append("Outputs on the Desktop → `Processed/`:")
            lines.append("```\n" + res["outputs"][:1800] + "\n```")
        if res.get("stdout"):
            lines.append("Run log (tail):")
            lines.append("```\n" + res["stdout"][-1500:] + "\n```")
        if res.get("code") not in (0, None) and res.get("stderr"):
            lines.append("Stderr (tail):")
            lines.append("```\n" + res["stderr"][-1000:] + "\n```")
    except Exception as e:  # noqa: BLE001
        lines.append(f"## Processing\n- ⚠️ {e}")
    lines.append("\n> Open **🖥️ Remote desktop** → `Uploads/` (originals) and "
                 "`Processed/` (agent output).")
    return "\n".join(lines)


# ---------- auth helpers ----------
def check_cookie(request) -> str | None:
    pid = request.cookies.get("poc_id")
    key = request.cookies.get("poc_key")
    if pid:
        rec = get_poc(pid)
        if rec and secrets.compare_digest(key or "", rec["password"]):
            return pid
    return None


def is_admin(request: Request) -> bool:
    t = request.query_params.get("token") or request.cookies.get("admin_token") or ""
    return secrets.compare_digest(t, ADMIN_TOKEN)


# ---------- HTML ----------
CSS = """<style>
:root{--b:#0078d4;--bg:#f5f7fa;--tx:#1a1a2e}
*{box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--tx);margin:0}
.wrap{max-width:860px;margin:40px auto;padding:0 20px}
.card{background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);padding:32px;margin-bottom:20px}
h1{font-size:24px;margin:0 0 6px}h2{font-size:17px}.sub{color:#667;margin:0 0 24px;font-size:14px}
label{display:block;font-weight:600;margin:16px 0 6px;font-size:14px}
input,textarea{width:100%;padding:10px 12px;border:1px solid #d0d7de;border-radius:8px;font-size:14px;font-family:inherit}
textarea{min-height:120px;resize:vertical}
button{background:var(--b);color:#fff;border:0;border-radius:8px;padding:12px 28px;font-size:15px;cursor:pointer;margin-top:20px}
button:hover{filter:brightness(1.1)}
.btn2{background:#5c2d91}.btn3{background:#a4262c}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600}
.b-run{background:#fff4ce;color:#835c00}.b-ok{background:#dff6dd;color:#0e700e}.b-err{background:#fde7e9;color:#a4262c}.b-wait{background:#e8e8f5;color:#5c2d91}
.step{padding:10px 14px;border-left:3px solid var(--b);background:#f0f6ff;border-radius:0 8px 8px 0;margin:8px 0;font-size:14px}
code,.mono{font-family:Consolas,monospace;background:#f0f2f5;padding:2px 6px;border-radius:4px;font-size:13px}
.kv{display:grid;grid-template-columns:130px 1fr;gap:8px;font-size:14px;margin:14px 0}
a{color:var(--b)}
.files{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.files a{padding:6px 12px;background:#f0f6ff;border-radius:8px;text-decoration:none;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #e1e4e8;padding:8px;text-align:left;vertical-align:top}
</style>"""

FORM_HTML = f"""<!doctype html><html><head><meta charset=utf-8>
<title>AI PoC Automation Portal</title>{CSS}</head><body><div class=wrap>
<div class=card><h1>🤖 AI PoC Automation Portal</h1>
<p class=sub>Submit customer info → admin approval → AI agent researches, drafts the
solution & PoC, builds a demo site → a dynamic-sessions desktop sandbox is allocated
→ you get an AE access link + password.</p>
<form id=f><label>Customer name</label><input name=customer required placeholder="e.g. Fosun Pharma">
<label>Industry</label><input name=industry required placeholder="e.g. Pharmaceuticals & Healthcare">
<label>Solution scenario</label><textarea name=scenario required
placeholder="Describe the scenario to validate, current pain points, and the expected PoC goals..."></textarea>
<label>Attachments (optional) — images, video, audio, documents</label>
<input type=file name=files multiple>
<p class=sub style="margin:6px 0 0">Uploaded files are pushed into the PoC sandbox; the agent
installs the tools it needs and processes them (e.g. ffmpeg/ImageMagick), with results placed on the desktop.</p>
<button>Submit request (admin approval required)</button></form></div></div>
<script>
document.getElementById('f').onsubmit=async e=>{{e.preventDefault();
const btn=e.target.querySelector('button');btn.disabled=true;btn.textContent='Uploading…';
const r=await fetch('/portal-api/submit',{{method:'POST',body:new FormData(e.target)}});
const j=await r.json();
if(j.id){{location.href='/ui/status/'+j.id;}}
else{{btn.disabled=false;btn.textContent='Submit request (admin approval required)';alert(j.detail||'error');}}}};
</script></body></html>"""


def status_html(pid: str) -> str:
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>PoC status {pid}</title>{CSS}</head><body><div class=wrap>
<div class=card><h1>PoC pipeline <span class=mono>{pid}</span> <span id=badge></span></h1>
<div class=kv id=info></div><div id=steps></div><div id=result></div>
<p style="margin-top:18px"><a href=/ui>← back to submission form</a></p></div></div>
<script>
async function poll(){{
 const r=await fetch('/portal-api/status/{pid}');const j=await r.json();
 document.getElementById('info').innerHTML=
  `<div>Customer</div><div>${{j.customer}}</div><div>Industry</div><div>${{j.industry}}</div>`+
  ((j.uploads&&j.uploads.length)?`<div>Uploads</div><div>${{j.uploads.join(', ')}}</div>`:'')+
  `<div>Updated</div><div>${{j.updated||''}}</div>`;
 const b=document.getElementById('badge');
 const map={{ready:['b-ok','ready'],failed:['b-err','failed'],pending_approval:['b-wait','awaiting approval'],rejected:['b-err','rejected']}};
 const st=map[j.status]||['b-run','running'];b.className='badge '+st[0];b.textContent=st[1];
 document.getElementById('steps').innerHTML=`<div class=step>${{j.step}}</div>`;
 if(j.status=='ready'){{
  document.getElementById('result').innerHTML=
   `<h2>✅ Hand-off to AE / sales</h2><div class=kv>
    <div>Access link</div><div><a href="/poc/{pid}" target=_blank>${{location.origin}}/poc/{pid}</a></div>
    <div>Password</div><div><code>${{j.password}}</code></div>
    <div>Contents</div><div>${{(j.files||[]).join(', ')}}</div></div>
    <p class=sub>The AE opens the link, enters the password, then can read the documents,
    open the demo site, or attach to the remote desktop sandbox.</p>`;
  return;}}
 if(j.status=='failed'||j.status=='rejected')return;
 setTimeout(poll,4000);}}
poll();
</script></body></html>"""


def login_html(pid: str, err: str = "") -> str:
    e = f"<p style='color:#a4262c'>{err}</p>" if err else ""
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>PoC access</title>{CSS}</head><body><div class=wrap>
<div class=card style="max-width:420px;margin:80px auto"><h1>🔐 PoC package access</h1>
<p class=sub>PoC <code>{pid}</code> — enter the password provided by your seller</p>{e}
<form method=post><input type=password name=password placeholder="Access password" required>
<button>Enter</button></form></div></div></body></html>"""


VIEW_HTML = f"""<!doctype html><html><head><meta charset=utf-8>
<title>PoC package</title>{CSS}
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script></head>
<body><div class=wrap style="max-width:1000px">
<div class=card><h1 id=t>PoC package</h1>
<p class=sub><a href="/demosite" target=_blank>🌐 Open demo site</a> ·
<a href="/desktop" target=_blank>🖥️ Open remote desktop (first launch ~30-60s)</a> ·
<a href="/logout">Sign out</a></p>
<div class=files id=list></div></div>
<div class=card><div id=md>Loading…</div></div></div>
<script>
async function load(){{
 const r=await fetch('/docs/list');const j=await r.json();
 const mds=(j.files||[]).filter(f=>f.name.endsWith('.md'));
 document.getElementById('list').innerHTML=mds.map(f=>
  `<a href="#" onclick="show('${{f.name}}');return false">📄 ${{f.name}}</a>`).join('');
 if(mds.length)show(mds[0].name);else document.getElementById('md').textContent='No documents yet';}}
async function show(n){{
 document.getElementById('md').textContent='Loading '+n+' …';
 const r=await fetch('/docs/get?name='+encodeURIComponent(n));
 document.getElementById('md').innerHTML=marked.parse(await r.text());}}
load();
</script></body></html>"""


def kb_html() -> str:
    """Knowledge Base section for the admin console."""
    kb = kb_all()
    entries = list(kb.get("entries", {}).values())
    if not entries:
        return ("<div class=card><h2>📚 Knowledge Base</h2><p class=sub>"
                "Skills & tools from successfully completed PoCs get distilled "
                "here automatically. Nothing harvested yet.</p></div>")
    cats: dict[str, list] = {}
    for e in entries:
        cats.setdefault(e["category"], []).append(e)
    order = ["Agent Skills", "AI & Models", "Azure Services", "Data & Analytics",
             "Security & Compliance", "Dev & Ops Tools", "Sandbox Tools"]
    sections = []
    for cat in order + sorted(set(cats) - set(order)):
        if cat not in cats:
            continue
        rows = []
        for e in sorted(cats[cat], key=lambda x: -len(x["pocs"])):
            links = "".join(
                f"<a href='/ui/status/{p}' target=_blank class=mono "
                f"style='margin-right:6px'>{p}</a>" for p in e["pocs"][:6])
            extra = (f"<small>+{len(e['pocs']) - 6} more</small>"
                     if len(e["pocs"]) > 6 else "")
            rows.append(
                f"<tr><td style='white-space:nowrap'><b>{e['name']}</b></td>"
                f"<td>{e['scenario']}</td>"
                f"<td>{links}{extra}</td></tr>")
        sections.append(
            f"<h2 style='margin:18px 0 8px'>{cat}</h2>"
            f"<table><tr><th style='width:220px'>Skill / Tool</th>"
            f"<th>When to use</th><th style='width:200px'>Used in</th></tr>"
            f"{''.join(rows)}</table>")
    upd = kb.get("updated", "")
    return (f"<div class=card><h2>📚 Knowledge Base "
            f"<small style='font-weight:400;color:#667'>— distilled from "
            f"successful PoCs · updated {upd}</small></h2>{''.join(sections)}</div>")


def admin_html() -> str:
    rows = []
    for pid, r in sorted(db_all().items(), key=lambda x: x[1]["created"], reverse=True):
        act = ""
        if r["status"] == "pending_approval":
            act = (f"<button onclick=\"act('{pid}','approve')\">✅ Approve</button> "
                   f"<button class=btn3 onclick=\"act('{pid}','reject')\">Reject</button>")
        elif r["status"] == "failed":
            act = f"<button onclick=\"act('{pid}','approve')\">🔁 Retry</button>"
        rows.append(
            f"<tr><td class=mono><a href='/ui/status/{pid}' target=_blank>{pid}</a></td>"
            f"<td>{r['customer']}<br><small>{r['industry']}</small></td>"
            f"<td style='max-width:320px'><small>{r['scenario'][:180]}</small></td>"
            f"<td>{r['status']} <a href='/ui/status/{pid}' target=_blank "
            f"title='Open status page (AE link & password)'>↗</a>"
            f"<br><small>{r['step'][:60]}</small></td><td>{act}</td></tr>")
    body = "".join(rows) or "<tr><td colspan=5>No requests yet</td></tr>"
    ready = [pid for pid, r in db_all().items() if r.get("status") == "ready"]
    opts = "".join(f"<option value='{p}'>{p}</option>" for p in sorted(ready))
    console = f"""<div class=card><h2>🔧 Sandbox console
<small style='font-weight:400;color:#667'>— run/install tools inside a ready
PoC's sandbox; output files land on that PoC's Desktop</small></h2>
<p class=sub>Runs as the agent (managed identity) against the dynamic-sessions
sandbox. Examples: <code>ffmpeg -version</code>,
<code>apt-get install -y cowsay &amp;&amp; cowsay hi</code>,
<code>convert -size 400x200 xc:navy /config/Desktop/blue.png</code></p>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
<select id=xpid style="width:auto">{opts or '<option>(no ready PoC)</option>'}</select>
<input id=xcmd placeholder="shell command to run in the sandbox"
 style="flex:1;min-width:280px" value="ffmpeg -version | head -1">
<button onclick="runx()" style="margin-top:0">Run</button></div>
<pre id=xout style="background:#0b1021;color:#c8e1ff;padding:12px;border-radius:8px;
 margin-top:12px;max-height:320px;overflow:auto;display:none;white-space:pre-wrap"></pre></div>"""
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>PoC approval console</title>{CSS}</head><body><div class=wrap style="max-width:1100px">
<div class=card><h1>🛡️ PoC approval console</h1>
<p class=sub>Sales requests wait here for review; the agent only starts working
(consuming AOAI and sandbox resources) after approval.</p>
<table><tr><th>ID</th><th>Customer</th><th>Scenario</th><th>Status</th><th>Action</th></tr>{body}</table>
<p style="margin-top:14px"><a href="javascript:location.reload()">🔄 Refresh</a></p></div>
{console}
{kb_html()}</div>
<script>
async function act(id,a){{
 await fetch('/admin/action',{{method:'POST',headers:{{'Content-Type':'application/json'}},
  body:JSON.stringify({{id:id,action:a}})}});location.reload();}}
async function runx(){{
 const id=document.getElementById('xpid').value, cmd=document.getElementById('xcmd').value;
 const o=document.getElementById('xout'); o.style.display='block'; o.textContent='Running…';
 try{{
  const r=await fetch('/admin/exec',{{method:'POST',headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{id:id,cmd:cmd}})}});
  const j=await r.json();
  o.textContent = j.error ? ('ERROR: '+j.error)
   : ('exit '+j.code+'\\n--- stdout ---\\n'+(j.stdout||'')+'\\n--- stderr ---\\n'+(j.stderr||''));
 }}catch(e){{o.textContent='request failed: '+e;}}
}}
</script></body></html>"""


# ---------- routes: sales ----------
@app.get("/ui", response_class=HTMLResponse)
def ui():
    return FORM_HTML


@app.post("/portal-api/submit")
async def submit(request: Request):
    ct = request.headers.get("content-type", "")
    uploads: list[str] = []
    pid = "poc-" + secrets.token_hex(3)
    if ct.startswith("multipart/form-data"):
        form = await request.form()
        customer = (form.get("customer") or "").strip()
        industry = (form.get("industry") or "").strip()
        scenario = (form.get("scenario") or "").strip()
        updir = os.path.join(poc_dir(pid), "uploads")
        os.makedirs(updir, exist_ok=True)
        total = 0
        for uf in form.getlist("files"):
            fn = os.path.basename(getattr(uf, "filename", "") or "")
            if not fn:
                continue
            fn = "".join(c for c in fn if c.isalnum() or c in "-_.() ")[:100]
            data = await uf.read()
            if not data:
                continue
            total += len(data)
            if total > 200 * 1024 * 1024:
                raise HTTPException(413, "uploads exceed 200 MB total")
            with open(os.path.join(updir, fn), "wb") as f:
                f.write(data)
            uploads.append(fn)
    else:
        d = await request.json()
        customer = (d.get("customer") or "").strip()
        industry = (d.get("industry") or "").strip()
        scenario = (d.get("scenario") or "").strip()
    for k, v in (("customer", customer), ("industry", industry), ("scenario", scenario)):
        if not v:
            raise HTTPException(400, f"missing {k}")
    rec = {"id": pid, "customer": customer, "industry": industry,
           "scenario": scenario, "uploads": uploads,
           "password": secrets.token_urlsafe(8),
           "status": "pending_approval",
           "step": "awaiting admin approval (work starts once approved)",
           "created": time.strftime("%Y-%m-%d %H:%M:%S"), "files": []}
    db_save(pid, rec)
    return {"id": pid}


@app.get("/ui/status/{pid}", response_class=HTMLResponse)
def ui_status(pid: str):
    if not get_poc(pid):
        raise HTTPException(404)
    return status_html(pid)


@app.get("/portal-api/status/{pid}")
def api_status(pid: str):
    rec = get_poc(pid)
    if not rec:
        raise HTTPException(404)
    return rec


# ---------- routes: admin approval ----------
@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    if not is_admin(request):
        return HTMLResponse("<h3>403 — requires ?token=ADMIN_TOKEN</h3>", 403)
    resp = HTMLResponse(admin_html())
    resp.set_cookie("admin_token", ADMIN_TOKEN, httponly=True, samesite="lax")
    return resp


@app.post("/admin/action")
async def admin_action(request: Request):
    if not is_admin(request):
        raise HTTPException(403)
    d = await request.json()
    pid, action = d.get("id"), d.get("action")
    rec = get_poc(pid)
    if not rec:
        raise HTTPException(404)
    if action == "approve" and rec["status"] in ("pending_approval", "failed"):
        set_status(pid, "running", "approved — agent starting…")
        asyncio.create_task(pipeline(pid))
    elif action == "reject":
        set_status(pid, "rejected", "rejected by admin")
    return {"ok": True}


@app.post("/admin/exec")
async def admin_exec(request: Request):
    if not is_admin(request):
        raise HTTPException(403)
    d = await request.json()
    pid, cmd = d.get("id"), (d.get("cmd") or "").strip()
    rec = get_poc(pid)
    if not rec:
        raise HTTPException(404)
    if rec.get("status") != "ready":
        raise HTTPException(400, "sandbox not ready")
    if not cmd:
        raise HTTPException(400, "missing cmd")
    try:
        return await azureops.exec_cmd(pid, cmd, timeout=int(d.get("timeout", 180)))
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:400]}


# ---------- routes: AE access ----------
@app.get("/poc/{pid}", response_class=HTMLResponse)
def poc_login(pid: str):
    if not get_poc(pid):
        raise HTTPException(404)
    return login_html(pid)


@app.post("/poc/{pid}")
async def poc_login_post(pid: str, request: Request):
    rec = get_poc(pid)
    if not rec:
        raise HTTPException(404)
    form = await request.form()
    if not secrets.compare_digest(str(form.get("password", "")), rec["password"]):
        return HTMLResponse(login_html(pid, "Incorrect password"), status_code=401)
    resp = RedirectResponse("/view", status_code=302)
    resp.set_cookie("poc_id", pid, httponly=True, samesite="lax")
    resp.set_cookie("poc_key", rec["password"], httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout():
    r = RedirectResponse("/ui")
    r.delete_cookie("poc_id")
    r.delete_cookie("poc_key")
    return r


@app.get("/view", response_class=HTMLResponse)
def view(request: Request):
    if not check_cookie(request):
        return RedirectResponse("/ui")
    return VIEW_HTML


@app.get("/demosite", response_class=HTMLResponse)
def demosite(request: Request):
    pid = check_cookie(request)
    if not pid:
        return RedirectResponse("/ui")
    p = os.path.join(poc_dir(pid), DEMO)
    if not os.path.exists(p):
        return HTMLResponse("<h3>Demo site not generated yet</h3>", 404)
    with open(p, encoding="utf-8") as f:
        return HTMLResponse(f.read())


# ---------- routes: documents (hosted by the portal) ----------
@app.get("/docs/list")
def docs_list(request: Request):
    pid = check_cookie(request)
    if not pid:
        raise HTTPException(403)
    d = poc_dir(pid)
    out = [{"name": n, "size": os.path.getsize(os.path.join(d, n))}
           for n in sorted(os.listdir(d)) if os.path.isfile(os.path.join(d, n))]
    return {"files": out}


@app.get("/docs/get")
def docs_get(request: Request, name: str):
    pid = check_cookie(request)
    if not pid:
        raise HTTPException(403)
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400)
    p = os.path.join(poc_dir(pid), name)
    if not os.path.isfile(p):
        raise HTTPException(404)
    with open(p, encoding="utf-8", errors="replace") as f:
        return PlainTextResponse(f.read())


@app.get("/desktop")
def desktop(request: Request):
    if not check_cookie(request):
        return RedirectResponse("/ui")
    return RedirectResponse("/")


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


# ---------- desktop proxy (root + catch-all, cookie-gated) ----------
SKIP = ("ui", "portal-api", "admin", "poc", "docs", "view", "desktop",
        "demosite", "logout", "healthz", "agent")


async def proxy(request: Request, path: str):
    pid = check_cookie(request)
    if not pid:
        return RedirectResponse("/ui") if path == "" else PlainTextResponse("not found", 404)
    q = dict(request.query_params)
    q.update({"api-version": APIV, "identifier": pid})
    url = f"{POOL}/{path}?{urlencode(q)}"
    hdr = {k: v for k, v in request.headers.items()
           if k.lower() in ("accept", "content-type", "user-agent", "cache-control", "range")}
    hdr["Authorization"] = f"Bearer {pool_token()}"
    body = await request.body()
    try:
        r = await azureops.client.request(request.method, url, headers=hdr, content=body)
    except Exception as e:  # noqa: BLE001
        return PlainTextResponse(f"sandbox starting… retry shortly ({e})", 502)
    out = {k: v for k, v in r.headers.items()
           if k.lower() in ("content-type", "cache-control", "etag", "last-modified", "accept-ranges")}
    return Response(content=r.content, status_code=r.status_code, headers=out)


@app.get("/")
async def root(request: Request):
    if check_cookie(request):
        return await proxy(request, "")
    return RedirectResponse("/ui")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def any_path(request: Request, path: str):
    if path.split("/")[0] in SKIP:
        raise HTTPException(404)
    return await proxy(request, path)


@app.websocket("/{path:path}")
async def ws_proxy(ws: WebSocket, path: str):
    pid = ws.cookies.get("poc_id")
    key = ws.cookies.get("poc_key")
    rec = get_poc(pid) if pid else None
    if not rec or not secrets.compare_digest(key or "", rec["password"]):
        await ws.close(code=4403)
        return
    q = dict(ws.query_params)
    q.update({"api-version": APIV, "identifier": pid})
    wsurl = POOL.replace("https://", "wss://") + f"/{path}?{urlencode(q)}"
    subs = ws.scope.get("subprotocols") or []
    try:
        upstream = await websockets.connect(
            wsurl, extra_headers={"Authorization": f"Bearer {pool_token()}"},
            subprotocols=subs or None, max_size=None, open_timeout=40)
    except Exception:  # noqa: BLE001
        await ws.close(code=4502)
        return
    await ws.accept(subprotocol=upstream.subprotocol)

    async def down():
        async for m in upstream:
            if isinstance(m, bytes):
                await ws.send_bytes(m)
            else:
                await ws.send_text(m)

    async def up():
        while True:
            m = await ws.receive()
            if m["type"] == "websocket.disconnect":
                break
            if m.get("bytes") is not None:
                await upstream.send(m["bytes"])
            elif m.get("text") is not None:
                await upstream.send(m["text"])

    t1, t2 = asyncio.create_task(down()), asyncio.create_task(up())
    _, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    try:
        await upstream.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        await ws.close()
    except Exception:  # noqa: BLE001
        pass
