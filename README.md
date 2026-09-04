# Hydra PoC Portal

Sales-facing **AI PoC automation** on Azure Container Apps **dynamic sessions**.

Flow: sales submit (form + optional file uploads) → admin approval → an in-portal
agent pipeline researches the customer/industry, drafts the solution proposal, PoC
plan and an interactive demo site → a Hyper-V isolated **XFCE desktop sandbox** is
allocated from a dynamic-sessions pool → agent runs tools (ffmpeg/ImageMagick, or
anything it `apt-get install`s) inside the sandbox and places outputs on the
Desktop → the AE gets an access link + password.

## Repo layout

| Path | What |
|---|---|
| `portal/` | FastAPI portal + agent (Container App). Submission form, approval console, status pages, doc hosting, HTTP+WS reverse proxy to the sandbox, knowledge base. |
| `portal/skills/` | Agent skills: `research`, `poc`, `azureops` (sandbox allocation + exec/upload client), `media` (desktop assets), `mediaproc` (LLM-written bash to process uploaded files), `knowledge` (harvests reusable skills/tools from successful PoCs). |
| `sandbox-image/` | `hydra-desktop:v4` — sandbox image for the session pool: webtop XFCE base + ffmpeg/ImageMagick/sox + token-gated in-sandbox exec/upload agent (`exec-agent.py`, s6 service) + nginx self-heal script. |
| `desktop-base/` | `hydra-desktop:v1` — the base desktop image (webtop XFCE + Chrome + FileZilla + CLI tools). |
| `docs/design-zh.md` | Full design doc (Chinese): architecture, approval gates, pitfalls, demo script. |

## Deployed topology (East Asia)

- **Portal**: Container App `hydra-poc-portal` (managed identity; RBAC:
  *Session Executor* on the pool, *Cognitive Services OpenAI User* on AOAI).
- **Sandboxes**: dynamic-sessions pool `hydra-poc-pool`, custom container
  `hydra-desktop:v4`, one session per PoC (`identifier = poc-id`).
- **Model**: Azure OpenAI `gpt-4o` via Entra ID (keyless).

## Configuration (env vars, no secrets in code)

| Var | Where | Purpose |
|---|---|---|
| `POOL_ENDPOINT` | portal | dynamic-sessions pool data-plane endpoint |
| `AOAI_ENDPOINT` / `AOAI_DEPLOYMENT` | portal | Azure OpenAI endpoint / deployment |
| `ADMIN_TOKEN` | portal | approval console token |
| `EXEC_TOKEN` | portal **and** pool | shared secret for the in-sandbox exec/upload agent |
| `DATA_DIR` | portal | record/doc store (ephemeral unless mounted) |
| `CUSTOM_PORT=3000`, `TITLE` | pool | webtop listen port / title |

## Build & deploy (ACR cloud build)

```bash
az acr build -r <acr> -t hydra-desktop:v1 desktop-base/
az acr build -r <acr> -t hydra-desktop:v4 sandbox-image/
az acr build -r <acr> -t hydra-poc-portal:v7 portal/

az containerapp sessionpool update -n hydra-poc-pool -g <rg> \
  --image <acr>.azurecr.io/hydra-desktop:v4 \
  --env-vars CUSTOM_PORT=3000 TITLE="Hydra PoC Sandbox" EXEC_TOKEN=<secret> \
  --registry-server <acr>.azurecr.io --registry-username <acr> --registry-password <pw>

az containerapp update -n hydra-poc-portal -g <rg> \
  --image <acr>.azurecr.io/hydra-poc-portal:v7 --set-env-vars EXEC_TOKEN=<secret>
```

## Endpoints (portal)

- Sales: `GET /ui` · `POST /portal-api/submit` (multipart w/ files) ·
  `GET /ui/status/{id}` · `GET /portal-api/status/{id}`
- Admin (`?token=ADMIN_TOKEN`): `GET /admin` · `POST /admin/action`
  (approve/reject) · `POST /admin/exec` (run command in a PoC sandbox)
- AE (password cookie): `GET|POST /poc/{id}` · `/view` · `/demosite` ·
  `/docs/list` · `/docs/get` · `/` (desktop HTTP+WS proxy)

## Known limitations

- Portal `DATA_DIR` is an ephemeral container disk — records/docs reset on
  redeploy (mount Azure Files for production).
- Sandboxes auto-recycle after cooldown; desktop files are per-session.
- See `docs/design-zh.md` §9 for the webtop/dynamic-sessions pitfalls
  (nginx config paths, CUSTOM_PORT residue, websockets pinning).

> Internal pre-sales tooling. AI-generated PoC content must be verified before
> customer use.
