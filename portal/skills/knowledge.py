"""Knowledge skill: harvest reusable skills/tools from successful PoCs."""
import json
import re

from core import kb_merge, llm

CATS = ["Agent Skills", "AI & Models", "Azure Services", "Data & Analytics",
        "Security & Compliance", "Dev & Ops Tools", "Sandbox Tools"]

BUILTIN = [
    {"name": "research skill", "category": "Agent Skills",
     "scenario": "Generates customer & industry research reports from the "
                 "request form; runs first in every PoC engagement."},
    {"name": "poc skill", "category": "Agent Skills",
     "scenario": "Drafts the solution proposal, PoC implementation plan and "
                 "the interactive demo site from research output."},
    {"name": "azureops skill", "category": "Agent Skills",
     "scenario": "Allocates an isolated desktop sandbox from the ACA "
                 "dynamic-sessions pool and waits until it is ready."},
    {"name": "Azure OpenAI (gpt-4o)", "category": "AI & Models",
     "scenario": "LLM behind all document and demo generation, called with "
                 "keyless Entra ID auth."},
    {"name": "ACA dynamic sessions", "category": "Azure Services",
     "scenario": "Per-PoC Hyper-V isolated sandbox replacing VMs: allocated "
                 "in seconds, auto-recycled when idle."},
    {"name": "Webtop XFCE desktop (Chrome/FileZilla/CLI)",
     "category": "Sandbox Tools",
     "scenario": "Browser-accessible GUI desktop where AEs run and present "
                 "the PoC remotely."},
    {"name": "FFmpeg (sandbox media)", "category": "Sandbox Tools",
     "scenario": "Pre-baked in the sandbox; the agent transcodes/clips/renders "
                 "audio-video and drops results on the requester's Desktop."},
    {"name": "ImageMagick (sandbox media)", "category": "Sandbox Tools",
     "scenario": "Pre-baked; the agent generates or edits images (title cards, "
                 "thumbnails) straight onto the Desktop."},
    {"name": "Sandbox exec / install endpoint", "category": "Dev & Ops Tools",
     "scenario": "Token-gated in-sandbox command runner; lets the agent "
                 "apt-get install and invoke arbitrary CLI tools per PoC."},
    {"name": "Uploaded-file processing (agent)", "category": "Sandbox Tools",
     "scenario": "Requester-uploaded images/video/audio are pushed to the "
                 "sandbox; the agent installs tools and processes them, writing "
                 "results to the Desktop Processed/ folder."},
]

SYS = ("You curate a reusable knowledge base for an Azure pre-sales team. "
       "Reply with a pure JSON array only — no markdown, no commentary.")

PROMPT = ("From the solution proposal and PoC plan below, extract up to 8 "
          "Azure services, AI models or notable third-party tools this PoC "
          "uses or recommends. For each output an object: "
          '{{"name": "<canonical name>", "category": "<one of: AI & Models | '
          "Azure Services | Data & Analytics | Security & Compliance | "
          'Dev & Ops Tools>", "scenario": "<one sentence, max 25 words, '
          'describing when a seller should reach for it>"}}. '
          "JSON array only.\n\n--- SOLUTION PROPOSAL ---\n{prop}\n\n"
          "--- POC PLAN ---\n{plan}")


def _extract(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for it in arr[:8]:
        if not (isinstance(it, dict) and it.get("name") and it.get("scenario")):
            continue
        cat = it.get("category", "")
        if cat not in CATS:
            cat = "Azure Services"
        out.append({"name": str(it["name"])[:80], "category": cat,
                    "scenario": str(it["scenario"])[:220]})
    return out


def harvest(pid: str, proposal: str, plan: str):
    """Merge built-in skills + LLM-extracted tools into the knowledge base."""
    items = list(BUILTIN)
    try:
        items += _extract(llm(SYS, PROMPT.format(prop=proposal[:6000],
                                                 plan=plan[:6000]),
                              max_tokens=1100, temp=0.1))
    except Exception:  # noqa: BLE001 — built-ins still get merged
        pass
    kb_merge(pid, items)
