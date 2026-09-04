"""Media/tooling skill: run ffmpeg / ImageMagick inside the PoC sandbox and
place the produced assets on the requester's XFCE Desktop."""
from skills import azureops

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
OUT = "/config/Desktop/PoC-Outputs"


def _san(s: str) -> str:
    return "".join(c for c in (s or "") if c.isalnum() or c in " &-_.,").strip()[:60]


async def produce_desktop_assets(pid: str, customer: str, industry: str) -> list:
    """Generate a branded title card (ImageMagick) + short intro clip (ffmpeg)
    into ~/Desktop/PoC-Outputs. Returns [(artifact, exit_code), ...]."""
    steps = []
    cust, ind = _san(customer), _san(industry)
    caption = f"{cust}  |  Azure PoC" + (f"\\n{ind}" if ind else "")

    await azureops.exec_cmd(pid, f"mkdir -p {OUT}", timeout=30)

    title = (f"convert -background '#0b3d91' -fill white -gravity center "
             f"-font {FONT} -size 1200x628 caption:'{caption}' "
             f"{OUT}/title.png")
    r1 = await azureops.exec_cmd(pid, title, timeout=90)
    steps.append(("title.png", r1.get("code", -1)))

    intro = (f"ffmpeg -y -loop 1 -i {OUT}/title.png -t 6 "
             f"-vf 'scale=1200:628,format=yuv420p' -r 25 {OUT}/intro.mp4")
    r2 = await azureops.exec_cmd(pid, intro, timeout=180)
    steps.append(("intro.mp4", r2.get("code", -1)))

    return steps
