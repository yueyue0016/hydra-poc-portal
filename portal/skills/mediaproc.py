"""Upload-processing skill: the agent installs tools in the sandbox and
processes the requester's uploaded files (images / video / audio) per the
scenario. LLM writes a bash script; it runs (as root) inside the sandbox."""
import asyncio
import re

from core import llm
from skills import azureops

SYS = ("You are a media-processing engineer operating a root bash shell inside "
       "an Ubuntu sandbox. Reply with ONLY a bash script — no markdown fences, "
       "no prose.")

PROMPT = """Uploaded files are in /config/Desktop/Uploads/ :
{files}

Scenario / intent:
{scenario}

Write ONE bash script that:
- Installs any needed tools non-interactively: `export DEBIAN_FRONTEND=noninteractive; apt-get update -qq; apt-get install -y <pkgs>`. NOTE: ffmpeg, imagemagick and sox are ALREADY installed.
- Processes the uploaded image/video/audio files per the scenario (e.g. transcode, clip, resize, thumbnail, poster frame, extract audio, waveform, watermark, montage). If intent is unclear, do sensible demos: thumbnails for images, a 480p mp4 + poster frame for videos, a waveform png for audio.
- Writes ALL outputs into /config/Desktop/Processed/ (mkdir -p first).
- Prints a concise summary of what it produced.
Only use the listed files; do NOT download external assets. Keep runtime under ~3 minutes.
Output ONLY the bash script."""


def _clean(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\n", "", t)
    t = re.sub(r"\n```$", "", t)
    return t.strip()


async def process(pid: str, scenario: str, filenames: list) -> dict:
    files = "\n".join(f"- {f}" for f in filenames) or "- (none)"
    script = _clean(await asyncio.to_thread(
        llm, SYS, PROMPT.format(files=files, scenario=scenario),
        max_tokens=1300, temp=0.2))
    await azureops.exec_cmd(pid, "mkdir -p /config/Desktop/Processed", timeout=30)
    res = await azureops.exec_cmd(pid, script, timeout=300)
    ls = await azureops.exec_cmd(
        pid, "find /config/Desktop/Processed -type f -printf '%s\\t%p\\n' | head -60",
        timeout=30)
    return {"script": script, "code": res.get("code"),
            "stdout": res.get("stdout", ""), "stderr": res.get("stderr", ""),
            "outputs": ls.get("stdout", "")}
