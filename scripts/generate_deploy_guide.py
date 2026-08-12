"""Generate the Coolify deployment guide PDF for TradingAgents.

Produces docs/Coolify_Deployment_Guide.pdf with embedded diagrams and
step-by-step instructions for deploying on a self-hosted Coolify instance
running on an Ubuntu VM at http://192.168.0.161:8000.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent
DIAGRAM_DIR = PROJECT_DIR / "docs" / "diagrams"
OUTPUT_PDF = PROJECT_DIR / "docs" / "Coolify_Deployment_Guide.pdf"

# ---------- Colors ----------
INDIGO = colors.HexColor("#6366f1")
PURPLE = colors.HexColor("#8b5cf6")
DARK = colors.HexColor("#12121e")
CARD = colors.HexColor("#1e1e2e")
GREEN = colors.HexColor("#34d399")
RED = colors.HexColor("#f87171")
LIGHT = colors.HexColor("#e2e8f0")
MUTED = colors.HexColor("#94a3b8")

# ---------- Styles ----------
styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    "TitleX", parent=styles["Title"], fontSize=26, textColor=INDIGO, spaceAfter=6
)
subtitle_style = ParagraphStyle(
    "SubtitleX", parent=styles["Normal"], fontSize=13, textColor=MUTED, spaceAfter=18
)
h1_style = ParagraphStyle(
    "H1X", parent=styles["Heading1"], fontSize=18, textColor=INDIGO, spaceBefore=14, spaceAfter=8
)
h2_style = ParagraphStyle(
    "H2X", parent=styles["Heading2"], fontSize=14, textColor=PURPLE, spaceBefore=10, spaceAfter=6
)
body_style = ParagraphStyle(
    "BodyX", parent=styles["BodyText"], fontSize=10.5, leading=15, textColor=colors.black
)
code_style = ParagraphStyle(
    "CodeX", parent=styles["Code"], fontSize=9, leading=13, backColor=colors.HexColor("#f1f5f9"),
    borderPadding=6, borderColor=colors.HexColor("#cbd5e1"), borderWidth=0.5,
)
note_style = ParagraphStyle(
    "NoteX", parent=styles["BodyText"], fontSize=10, leading=14,
    backColor=colors.HexColor("#fef3c7"), borderPadding=8,
    borderColor=colors.HexColor("#f59e0b"), borderWidth=1,
)
warn_style = ParagraphStyle(
    "WarnX", parent=styles["BodyText"], fontSize=10, leading=14,
    backColor=colors.HexColor("#fee2e2"), borderPadding=8,
    borderColor=colors.HexColor("#ef4444"), borderWidth=1,
)


def _bullet_list(items: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(i, body_style), leftIndent=18) for i in items],
        bulletType="bullet",
        start="•",
        leftIndent=18,
    )


def _numbered_list(items: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(i, body_style), leftIndent=18) for i in items],
        bulletType="1",
        leftIndent=18,
    )


def _code_block(text: str) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), code_style)


def build_pdf():
    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=A4,
        rightMargin=0.8 * inch,
        leftMargin=0.8 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        title="TradingAgents — Coolify Deployment Guide",
        author="TradingAgents",
    )

    story = []

    # ============ COVER ============
    story.append(Spacer(1, 1.2 * inch))
    story.append(Paragraph("TradingAgents", title_style))
    story.append(Paragraph("Deployment Guide for Self-Hosted Coolify", subtitle_style))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("Version 1.0  |  Ubuntu VM  |  Coolify at <b>http://192.168.0.161:8000</b>", body_style))
    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph(
        "This guide walks you through deploying the TradingAgents multi-agent LLM "
        "financial trading framework on your self-hosted Coolify instance. It covers "
        "code preparation, Coolify configuration, environment variables, port mapping, "
        "and configuring API keys directly in the browser.",
        body_style,
    ))
    story.append(PageBreak())

    # ============ 1. PREREQUISITES ============
    story.append(Paragraph("1. Prerequisites", h1_style))
    story.append(_bullet_list([
        "<b>Ubuntu VM</b> with Docker installed and running.",
        "<b>Coolify</b> installed and accessible at <b>http://192.168.0.161:8000</b>.",
        "<b>Git repository</b> (GitHub, GitLab, or Gitea) containing the TradingAgents project.",
        "<b>LLM API key</b> for at least one provider (OpenAI, Anthropic, Google, etc.).",
        "Network access from your browser to the VM on the LAN.",
    ]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(
        "<b>Note:</b> Coolify itself occupies host port <b>8000</b>. The TradingAgents app "
        "will be exposed on host port <b>8001</b> to avoid a conflict.",
        note_style,
    ))

    # ============ 2. ARCHITECTURE ============
    story.append(Paragraph("2. Architecture Overview", h1_style))
    story.append(Paragraph(
        "The diagram below shows how the browser, Coolify, the app container, and "
        "persistent volumes fit together on your LAN.",
        body_style,
    ))
    story.append(Spacer(1, 0.2 * inch))
    arch_img = DIAGRAM_DIR / "architecture.png"
    if arch_img.exists():
        story.append(Image(str(arch_img), width=6.8 * inch, height=3.9 * inch))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(
        "<b>Key points:</b> The browser reaches the app at <b>http://192.168.0.161:8001</b>. "
        "Coolify's proxy routes that to the container's internal port <b>8000</b>. "
        "API keys saved in the browser persist to the <b>tradingagents_config</b> volume.",
        body_style,
    ))

    # ============ 3. CODE CHANGES ============
    story.append(Paragraph("3. Required Code Changes", h1_style))
    story.append(Paragraph(
        "Two files were updated so the app runs headless in a container and avoids the "
        "port conflict with Coolify.",
        body_style,
    ))

    story.append(Paragraph("3.1 Dockerfile — headless web server", h2_style))
    story.append(Paragraph(
        "The original CMD launched the desktop launcher, which binds to 127.0.0.1 on a "
        "random port and tries to open a native window — this fails in a headless container. "
        "It is replaced with a uvicorn web server bound to 0.0.0.0:8000:",
        body_style,
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(_code_block(
        'CMD ["uvicorn", "app.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]'
    ))

    story.append(Paragraph("3.2 docker-compose.coolify.yml — port mapping", h2_style))
    story.append(Paragraph(
        "Since Coolify uses host port 8000, the app is mapped to host port 8001:",
        body_style,
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(_code_block(
        "ports:\n"
        '  - "8001:8000"   # host 8001 -> container 8000'
    ))

    # ============ 4. DEPLOYMENT FLOW ============
    story.append(Paragraph("4. Step-by-Step Deployment", h1_style))
    flow_img = DIAGRAM_DIR / "deploy_flow.png"
    if flow_img.exists():
        story.append(Image(str(flow_img), width=6.8 * inch, height=7.4 * inch))
    story.append(PageBreak())

    story.append(Paragraph("4.1 Push the code to a Git repository", h2_style))
    story.append(_numbered_list([
        "Create a repository on GitHub, GitLab, or Gitea.",
        "Push the TradingAgents project (including <b>Dockerfile</b> and <b>docker-compose.coolify.yml</b>).",
        "Ensure <b>config/credentials.json</b> is NOT committed (it is in .gitignore).",
    ]))

    story.append(Paragraph("4.2 Add the repository in Coolify", h2_style))
    story.append(_numbered_list([
        "Log in to Coolify at <b>http://192.168.0.161:8000</b>.",
        "Go to <b>Projects</b> → <b>New Project</b> → give it a name (e.g. 'TradingAgents').",
        "Click <b>New Resource</b> → <b>Public Repository</b> (or Private Repository if using a token).",
        "Paste the repository URL and select the branch (e.g. <b>main</b>).",
    ]))

    story.append(Paragraph("4.3 Configure the build", h2_style))
    story.append(_numbered_list([
        "Set <b>Build Pack</b> to <b>Dockerfile</b>.",
        "Set <b>Base Directory</b> to <b>/</b> (repo root).",
        "Coolify will use the <b>Dockerfile</b> at the root.",
    ]))

    story.append(Paragraph("4.4 Set environment variables", h2_style))
    story.append(Paragraph(
        "In the resource's <b>Environment Variables</b> tab, add:",
        body_style,
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(_code_block(
        "PORT=8000\n"
        "TRADINGAGENTS_LLM_PROVIDER=openai\n"
        "# Optional: pre-seed keys (or set them later in the browser)\n"
        "# OPENAI_API_KEY=sk-...\n"
        "# ANTHROPIC_API_KEY=sk-ant-...\n"
        "# GOOGLE_API_KEY=AIza...\n"
        "# CLOUDFLARE_ACCOUNT_ID=...\n"
        "# CLOUDFLARE_GATEWAY_ID=...\n"
        "# CLOUDFLARE_BYOK_ALIAS=default"
    ))

    story.append(Paragraph("4.5 Configure the port", h2_style))
    story.append(Paragraph(
        "In the resource's <b>Ports</b> / <b>Networking</b> settings, map:",
        body_style,
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(_code_block(
        "Host port:  8001\n"
        "Container port:  8000"
    ))
    story.append(Paragraph(
        "This avoids the conflict with Coolify on port 8000. If you prefer, you can "
        "instead use Coolify's built-in reverse proxy with a domain.",
        note_style,
    ))

    story.append(Paragraph("4.6 Deploy", h2_style))
    story.append(_numbered_list([
        "Click <b>Deploy</b>.",
        "Watch the build logs — the Docker image will be built and the container started.",
        "Wait for the status to show <b>Running</b> and the healthcheck to pass.",
    ]))

    story.append(Paragraph("4.7 Verify the healthcheck", h2_style))
    story.append(Paragraph(
        "The container's healthcheck calls <b>GET /api/config</b> on port 8000. "
        "A healthy container returns HTTP 200. You can verify manually:",
        body_style,
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(_code_block(
        "curl -f http://192.168.0.161:8001/api/config"
    ))

    story.append(Paragraph("4.8 Open the app", h2_style))
    story.append(Paragraph(
        "Open <b>http://192.168.0.161:8001</b> in your browser. You should see the "
        "TradingAgents configuration page.",
        body_style,
    ))

    # ============ 5. CONFIGURE API KEYS IN BROWSER ============
    story.append(Paragraph("5. Configure API Keys in the Browser", h1_style))
    story.append(Paragraph(
        "TradingAgents now lets you save API keys directly in the browser — no need to "
        "set them in Coolify. Keys persist to <b>config/credentials.json</b> inside the "
        "container, backed by the <b>tradingagents_config</b> volume.",
        body_style,
    ))
    story.append(Spacer(1, 0.2 * inch))
    story.append(_numbered_list([
        "Open <b>http://192.168.0.161:8001</b>.",
        "In the <b>LLM Configuration</b> section, select your provider (e.g. OpenAI).",
        "Enter your API key in the <b>API Key</b> field.",
        "Click <b>Save Key</b> — a ✓ confirms it was saved to the project config.",
        "Click <b>Validate & Fetch Models</b> to test the key and load available models.",
        "Select your Deep & Quick models, then click <b>Launch Analysis</b>.",
    ]))
    story.append(Paragraph(
        "Saved keys are loaded into the environment at startup, so analysis works "
        "immediately. Keys are stored in plaintext (like .env) and are excluded from "
        "version control via .gitignore.",
        note_style,
    ))

    # ============ 6. PERSISTENT STORAGE ============
    story.append(Paragraph("6. Persistent Storage", h1_style))
    story.append(Paragraph(
        "Two Docker volumes persist data across container restarts and redeploys:",
        body_style,
    ))
    story.append(Spacer(1, 0.1 * inch))
    table_data = [
        ["Volume", "Mount point", "Purpose"],
        ["tradingagents_config", "/home/appuser/app/config", "API keys & settings (credentials.json)"],
        ["tradingagents_data", "/home/appuser/.tradingagents", "Logs, cache, memory"],
    ]
    table = Table(table_data, colWidths=[2.2 * inch, 2.4 * inch, 2.2 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)

    # ============ 7. TROUBLESHOOTING ============
    story.append(Paragraph("7. Troubleshooting", h1_style))

    story.append(Paragraph("7.1 Healthcheck failing", h2_style))
    story.append(Paragraph(
        "If the container shows unhealthy, check that the app is listening on port 8000 "
        "inside the container and that the Dockerfile CMD uses uvicorn (not the desktop "
        "launcher).",
        body_style,
    ))

    story.append(Paragraph("7.2 Port conflict", h2_style))
    story.append(Paragraph(
        "Coolify uses port 8000. If you try to map the app to 8000 as well, the container "
        "will fail to start. Use host port 8001 (or another free port).",
        body_style,
    ))

    story.append(Paragraph("7.3 Cannot reach the app from browser", h2_style))
    story.append(_bullet_list([
        "Verify the VM firewall allows inbound traffic on port 8001.",
        "Confirm the container is running: <b>docker ps</b> on the VM.",
        "Check the app logs in Coolify for startup errors.",
    ]))

    story.append(Paragraph("7.4 API key not working", h2_style))
    story.append(_bullet_list([
        "Ensure you clicked <b>Save Key</b> (not just typed the key).",
        "Verify the key is valid with <b>Validate & Fetch Models</b>.",
        "Check that the <b>tradingagents_config</b> volume is mounted so the key persists.",
    ]))

    # ============ 8. SECURITY ============
    story.append(Paragraph("8. Security Notes", h1_style))
    story.append(_bullet_list([
        "<b>config/credentials.json</b> is excluded from git via .gitignore — never commit API keys.",
        "Keys are stored in plaintext (same as .env). Protect the VM and volume access.",
        "The app is exposed on the LAN. Restrict access with a firewall or Coolify's "
        "authentication if needed.",
        "Use Coolify's environment variables for non-secret config; use the browser "
        "Save Key feature for secrets.",
    ]))

    # ============ 9. SUMMARY ============
    story.append(Paragraph("9. Quick Reference", h1_style))
    story.append(_bullet_list([
        "Coolify dashboard: <b>http://192.168.0.161:8000</b>",
        "TradingAgents app: <b>http://192.168.0.161:8001</b>",
        "Healthcheck: <b>GET /api/config</b>",
        "Config store: <b>config/credentials.json</b> (volume: tradingagents_config)",
        "Build: <b>Dockerfile</b> → uvicorn on 0.0.0.0:8000",
    ]))

    doc.build(story)
    print(f"PDF saved to {OUTPUT_PDF}")


if __name__ == "__main__":
    build_pdf()