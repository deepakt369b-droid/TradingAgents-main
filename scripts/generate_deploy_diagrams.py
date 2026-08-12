"""Generate architecture & flow diagrams for the Coolify deployment guide.

Produces PNG images used by the PDF guide:
  - docs/diagrams/architecture.png
  - docs/diagrams/deploy_flow.png
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------- Paths ----------
PROJECT_DIR = Path(__file__).resolve().parent.parent
DIAGRAM_DIR = PROJECT_DIR / "docs" / "diagrams"
DIAGRAM_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Fonts ----------
def _load_font(size: int, bold: bool = False):
    """Load a TTF font, falling back to a default bitmap font."""
    candidates = []
    if os.name == "nt":  # Windows
        candidates = [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
        ]
    else:  # Linux / macOS
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ---------- Colors ----------
BG = (18, 18, 30)          # dark background
CARD = (30, 30, 50)        # card background
BORDER = (99, 102, 241)    # indigo border
ACCENT = (139, 92, 246)    # purple
GREEN = (52, 211, 153)     # green
RED = (248, 113, 113)      # red
TEXT = (226, 232, 240)     # light text
MUTED = (148, 163, 184)    # muted text
WHITE = (255, 255, 255)


def _rounded_box(draw: ImageDraw.ImageDraw, xy, radius: int, fill, outline=None, width=2):
    """Draw a rounded rectangle."""
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _center_text(draw: ImageDraw.ImageDraw, box, text, font, fill=TEXT):
    """Draw text centered within a box."""
    x0, y0, x1, y1 = box
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = x0 + (x1 - x0 - tw) / 2
    y = y0 + (y1 - y0 - th) / 2
    draw.text((x, y), text, font=font, fill=fill)


def _arrow(draw: ImageDraw.ImageDraw, x1, y1, x2, y2, color=ACCENT, width=3):
    """Draw an arrow from (x1,y1) to (x2,y2)."""
    draw.line([(x1, y1), (x2, y2)], fill=color, width=width)
    # Arrowhead
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 12
    ax = x2 - size * math.cos(angle - 0.4)
    ay = y2 - size * math.sin(angle - 0.4)
    bx = x2 - size * math.cos(angle + 0.4)
    by = y2 - size * math.sin(angle + 0.4)
    draw.polygon([(x2, y2), (ax, ay), (bx, by)], fill=color)


# =====================================================================
# 1. Architecture Diagram
# =====================================================================
def build_architecture() -> Image.Image:
    W, H = 1200, 700
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    title_font = _load_font(30, bold=True)
    sub_font = _load_font(18)
    card_font = _load_font(16, bold=True)
    small_font = _load_font(13)
    tiny_font = _load_font(11)

    # Title
    draw.text((40, 30), "TradingAgents on Self-Hosted Coolify", font=title_font, fill=WHITE)
    draw.text((40, 70), "LAN Deployment Architecture  |  Coolify at 192.168.0.161:8000", font=sub_font, fill=MUTED)

    # ---- Browser (left) ----
    browser_box = (40, 180, 260, 300)
    _rounded_box(draw, browser_box, 16, CARD, BORDER)
    _center_text(draw, (browser_box[0], browser_box[1] + 20, browser_box[2], browser_box[1] + 60), "🌐 Browser", card_font, WHITE)
    _center_text(draw, (browser_box[0], browser_box[1] + 65, browser_box[2], browser_box[1] + 95), "http://192.168.0.161:8001", small_font, GREEN)
    _center_text(draw, (browser_box[0], browser_box[1] + 100, browser_box[2], browser_box[1] + 120), "User on LAN", tiny_font, MUTED)

    # ---- Coolify Proxy (middle) ----
    proxy_box = (420, 150, 780, 330)
    _rounded_box(draw, proxy_box, 16, CARD, BORDER)
    _center_text(draw, (proxy_box[0], proxy_box[1] + 20, proxy_box[2], proxy_box[1] + 60), "🖥️ Coolify (Ubuntu VM)", card_font, WHITE)
    _center_text(draw, (proxy_box[0], proxy_box[1] + 65, proxy_box[2], proxy_box[1] + 95), "Dashboard: 192.168.0.161:8000", small_font, ACCENT)
    _center_text(draw, (proxy_box[0], proxy_box[1] + 100, proxy_box[2], proxy_box[1] + 130), "Docker Engine + Reverse Proxy", small_font, TEXT)
    _center_text(draw, (proxy_box[0], proxy_box[1] + 135, proxy_box[2], proxy_box[1] + 160), "Routes :8001 → container :8000", tiny_font, MUTED)

    # ---- App Container (right) ----
    app_box = (920, 150, 1160, 330)
    _rounded_box(draw, app_box, 16, CARD, GREEN)
    _center_text(draw, (app_box[0], app_box[1] + 20, app_box[2], app_box[1] + 60), "📦 TradingAgents", card_font, WHITE)
    _center_text(draw, (app_box[0], app_box[1] + 65, app_box[2], app_box[1] + 95), "Container", small_font, TEXT)
    _center_text(draw, (app_box[0], app_box[1] + 100, app_box[2], app_box[1] + 130), "uvicorn :8000", small_font, GREEN)
    _center_text(draw, (app_box[0], app_box[1] + 135, app_box[2], app_box[1] + 160), "FastAPI + Web UI", tiny_font, MUTED)

    # Arrows: browser -> proxy -> app
    _arrow(draw, 260, 240, 420, 240)
    _arrow(draw, 780, 240, 920, 240)

    # ---- Volumes (bottom) ----
    vol1 = (420, 480, 700, 600)
    _rounded_box(draw, vol1, 16, CARD, ACCENT)
    _center_text(draw, (vol1[0], vol1[1] + 20, vol1[2], vol1[1] + 60), "💾 tradingagents_config", card_font, WHITE)
    _center_text(draw, (vol1[0], vol1[1] + 65, vol1[2], vol1[1] + 95), "config/credentials.json", small_font, TEXT)
    _center_text(draw, (vol1[0], vol1[1] + 100, vol1[2], vol1[1] + 120), "API keys persist", tiny_font, MUTED)

    vol2 = (760, 480, 1040, 600)
    _rounded_box(draw, vol2, 16, CARD, ACCENT)
    _center_text(draw, (vol2[0], vol2[1] + 20, vol2[2], vol2[1] + 60), "💾 tradingagents_data", card_font, WHITE)
    _center_text(draw, (vol2[0], vol2[1] + 65, vol2[2], vol2[1] + 95), "~/.tradingagents", small_font, TEXT)
    _center_text(draw, (vol2[0], vol2[1] + 100, vol2[2], vol2[1] + 120), "logs & cache", tiny_font, MUTED)

    # Arrows from app to volumes
    _arrow(draw, 1000, 330, 560, 480)
    _arrow(draw, 1000, 330, 900, 480)

    # Legend
    draw.text((40, 640), "Legend:", font=small_font, fill=MUTED)
    _rounded_box(draw, (120, 630, 150, 660), 6, CARD, BORDER)
    draw.text((160, 640), "Coolify / Proxy", font=tiny_font, fill=TEXT)
    _rounded_box(draw, (300, 630, 330, 660), 6, CARD, GREEN)
    draw.text((340, 640), "App Container", font=tiny_font, fill=TEXT)
    _rounded_box(draw, (480, 630, 510, 660), 6, CARD, ACCENT)
    draw.text((520, 640), "Persistent Volume", font=tiny_font, fill=TEXT)

    return img


# =====================================================================
# 2. Deployment Flow Diagram
# =====================================================================
def build_deploy_flow() -> Image.Image:
    W, H = 1000, 1100
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    title_font = _load_font(28, bold=True)
    step_font = _load_font(15, bold=True)
    desc_font = _load_font(12)
    num_font = _load_font(18, bold=True)

    draw.text((40, 30), "Deployment Flow — Step by Step", font=title_font, fill=WHITE)

    steps = [
        ("1", "Push code to Git repo", "GitHub / GitLab / Gitea — include Dockerfile & docker-compose.coolify.yml"),
        ("2", "Add repo in Coolify", "Projects → New Project → New Resource → Public/Private Repository"),
        ("3", "Select Dockerfile build", "Build Pack = Dockerfile, Base Directory = / (repo root)"),
        ("4", "Set environment variables", "TRADINGAGENTS_LLM_PROVIDER, optional API keys, PORT=8000"),
        ("5", "Configure port mapping", "Host port 8001 → Container port 8000 (8000 is used by Coolify)"),
        ("6", "Deploy", "Click Deploy; watch build & container logs"),
        ("7", "Verify healthcheck", "GET /api/config returns 200 — container is healthy"),
        ("8", "Open the app", "http://192.168.0.161:8001 — configure API keys in the browser"),
    ]

    y = 100
    for num, title, desc in steps:
        # Number circle
        draw.ellipse([60, y, 110, y + 50], fill=ACCENT)
        _center_text(draw, (60, y, 110, y + 50), num, num_font, WHITE)

        # Step card
        card = (130, y, 940, y + 90)
        _rounded_box(draw, card, 12, CARD, BORDER)
        draw.text((150, y + 12), title, font=step_font, fill=WHITE)
        draw.text((150, y + 45), desc, font=desc_font, fill=MUTED)

        # Arrow between steps
        if num != "8":
            _arrow(draw, 85, y + 50, 85, y + 110, color=MUTED, width=2)

        y += 120

    return img


# =====================================================================
# Main
# =====================================================================
def main():
    arch = build_architecture()
    arch_path = DIAGRAM_DIR / "architecture.png"
    arch.save(arch_path)
    print(f"Saved {arch_path}")

    flow = build_deploy_flow()
    flow_path = DIAGRAM_DIR / "deploy_flow.png"
    flow.save(flow_path)
    print(f"Saved {flow_path}")


if __name__ == "__main__":
    main()