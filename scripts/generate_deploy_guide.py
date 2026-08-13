"""Generate the Coolify deployment guide PDF for TradingAgents.

Produces docs/Coolify_Deployment_Guide.pdf with embedded diagrams and
step-by-step instructions for deploying on a self-hosted Coolify v4 instance.

This version matches the Coolify dashboard fields shown in the user's screenshot
and explains why the default "Nixpacks" build pack fails for this project.
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
    story.append(Paragraph("Deployment Guide for Self-Hosted Coolify v4", subtitle_style))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        "Version 1.1  |  Ubuntu VM  |  Coolify at <b>http://192.168.0.161:8000</b>",
        body_style,
    ))
    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph(
        "This guide walks you through deploying the TradingAgents multi-agent LLM "
        "financial trading framework on your self-hosted Coolify instance. It is "
        "written for the Coolify dashboard fields shown in your screenshot and "
        "covers the exact build-pack, port, and environment settings needed to "
        "deploy without errors.",
        body_style,
    ))
    story.append(PageBreak())

    # ============ 1. WHY THE DEFAULT DEPLOYMENT FAILS ============
    story.append(Paragraph("1. Why the default deployment fails", h1_style))
    story.append(Paragraph(
        "In the Coolify dashboard screenshot the resource is configured as a "
        "<b>Nixpacks</b> application with <b>Ports Expose = 3000</b> and a long set of "
        "Nix-specific <b>Custom Docker Options</b>. That is the wrong build pack for "
        "this project and it produces a build/deploy error.",
        body_style,
    ))
    story.append(Spacer(1, 0.15 * inch))
    story.append(_bullet_list([
        "<b>TradingAgents is not a Nixpacks / static-site project.</b> It is a Python "
        "project that ships its own <b>Dockerfile</b> and <b>docker-compose.coolify.yml</b>.",
        "<b>Nixpacks cannot auto-detect the correct start command</b> because the entry "
        "point is a custom uvicorn command inside the Dockerfile.",
        "<b>Port 3000 is wrong</b> for this app. The container listens internally on "
        "<b>8000</b>; Coolify itself already uses host port <b>8000</b>, so the app must "
        "be exposed on a different host port (e.g. <b>8001</b>) or through a Coolify domain.",
        "<b>The Nixpacks custom Docker options must be removed.</b> They are only needed "
        "when Coolify builds with Nixpacks.",
    ]))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(
        "Fix: change the <b>Build Pack</b> to <b>Docker Compose</b> (recommended) or "
        "<b>Dockerfile</b>, clear the custom options, and expose the correct port.",
        warn_style,
    ))

    # ============ 2. PREREQUISITES ============
    story.append(Paragraph("2. Prerequisites", h1_style))
    story.append(_bullet_list([
        "<b>Ubuntu VM</b> with Docker installed and running.",
        "<b>Coolify v4</b> installed and accessible at <b>http://192.168.0.161:8000</b>.",
        "<b>Git repository</b> (GitHub, GitLab, or Gitea) containing the TradingAgents project.",
        "<b>LLM API key</b> for at least one provider (OpenAI, Anthropic, Google, etc.) — or enter it later in the browser.",
        "Network access from your browser to the VM on the LAN.",
    ]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(
        "<b>Note:</b> Coolify itself occupies host port <b>8000</b>. The TradingAgents app "
        "will be exposed on host port <b>8001</b> to avoid a conflict.",
        note_style,
    ))

    # ============ 3. ARCHITECTURE ============
    story.append(Paragraph("3. Architecture Overview", h1_style))
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
        "Coolify routes that to the container's internal port <b>8000</b>. "
        "API keys saved in the browser persist to the <b>tradingagents_config</b> volume.",
        body_style,
    ))

    # ============ 4. COOLIFY CONFIGURATION (Docker Compose) ============
    story.append(Paragraph("4. Recommended Coolify Configuration", h1_style))
    story.append(Paragraph(
        "Use the <b>Docker Compose</b> build pack. It reads the project's "
        "<b>docker-compose.coolify.yml</b> file, so ports, environment variables, "
        "volumes, and the healthcheck are applied automatically.",
        body_style,
    ))
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("4.1 General tab", h2_style))
    fields = [
        ["Field", "Value"],
        ["Build Pack", "Docker Compose"],
        ["Base Directory", "/"],
        ["Docker Compose Location", "docker-compose.coolify.yml"],
        ["Is it a static site?", "No / unchecked"],
        ["Custom Docker Options", "Leave empty"],
    ]
    table = Table(fields, colWidths=[2.8 * inch, 4.0 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(
        "<b>Important:</b> Do <b>not</b> select <b>Nixpacks</b>. The Nixpacks options "
        "you saw in the screenshot are not used for this project.",
        warn_style,
    ))

    story.append(Paragraph("4.2 Network tab", h2_style))
    story.append(Paragraph(
        "The <b>docker-compose.coolify.yml</b> file already maps the correct ports. "
        "You only need to make sure Coolify exposes the container port:",
        body_style,
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(_code_block(
        "Ports Expose:  8000\n"
        "Port Mapping: 8001:8000   # host 8001 -> container 8000"
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(
        "If you prefer to use Coolify's automatic domain/SSL instead of an IP:port, set "
        "<b>Ports Expose = 8000</b> and leave the Port Mapping blank. Coolify will "
        "proxy the generated domain to port 8000 inside the container.",
        note_style,
    ))

    story.append(Paragraph("4.3 Environment variables", h2_style))
    story.append(Paragraph(
        "The Docker Compose file already sets <b>PORT=8000</b>. Add only the "
        "variables you need. At minimum you can leave all API-key variables empty "
        "and enter the key later in the browser.",
        body_style,
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(_code_block(
        "PORT=8000\n"
        "TRADINGAGENTS_LLM_PROVIDER=openai\n"
        "# Optional: pre-seed API keys (otherwise save them in the browser)\n"
        "# OPENAI_API_KEY=sk-...\n"
        "# ANTHROPIC_API_KEY=sk-ant-...\n"
        "# GOOGLE_API_KEY=AIza...\n"
        "# CLOUDFLARE_ACCOUNT_ID=...\n"
        "# CLOUDFLARE_GATEWAY_ID=...\n"
        "# CLOUDFLARE_BYOK_ALIAS=default"
    ))

    # ============ 5. DEPLOYMENT FLOW ============
    story.append(Paragraph("5. Step-by-Step Deployment", h1_style))
    flow_img = DIAGRAM_DIR / "deploy_flow.png"
    if flow_img.exists():
        story.append(Image(str(flow_img), width=6.8 * inch, height=7.4 * inch))
    story.append(PageBreak())

    story.append(Paragraph("5.1 Push the code to a Git repository", h2_style))
    story.append(_numbered_list([
        "Create a repository on GitHub, GitLab, or Gitea.",
        "Push the TradingAgents project (including <b>Dockerfile</b>, <b>pyproject.toml</b>, and <b>docker-compose.coolify.yml</b>).",
        "Ensure <b>config/credentials.json</b> is NOT committed (it is in .gitignore).",
    ]))

    story.append(Paragraph("5.2 Add the repository in Coolify", h2_style))
    story.append(_numbered_list([
        "Log in to Coolify at <b>http://192.168.0.161:8000</b>.",
        "Go to <b>Projects</b> → <b>New Project</b> → give it a name (e.g. 'TradingAgents').",
        "Click <b>New Resource</b> → <b>Public Repository</b> (or Private Repository / GitHub App if needed).",
        "Paste the repository URL and select the branch (e.g. <b>main</b>).",
    ]))

    story.append(Paragraph("5.3 Configure the build pack", h2_style))
    story.append(_numbered_list([
        "Open the <b>General</b> tab of the new resource.",
        "Set <b>Build Pack</b> to <b>Docker Compose</b>.",
        "Set <b>Base Directory</b> to <b>/</b>.",
        "Set <b>Docker Compose Location</b> to <b>docker-compose.coolify.yml</b>.",
        "Make sure <b>Custom Docker Options</b> is empty.",
    ]))

    story.append(Paragraph("5.4 Configure the network", h2_style))
    story.append(_numbered_list([
        "Open the <b>Network</b> / <b>Ports</b> section.",
        "Set <b>Ports Expose</b> to <b>8000</b>.",
        "Set <b>Port Mapping</b> to <b>8001:8000</b> (host 8001 → container 8000).",
        "Leave the mapping blank if you will use a Coolify-generated domain instead.",
    ]))

    story.append(Paragraph("5.5 Set environment variables (optional)", h2_style))
    story.append(_numbered_list([
        "Open the <b>Environment Variables</b> tab.",
        "Add <b>PORT=8000</b> if it is not already inherited from the compose file.",
        "Add <b>TRADINGAGENTS_LLM_PROVIDER=openai</b> (or google, anthropic, etc.).",
        "API keys can be left empty and entered later in the browser.",
    ]))

    story.append(Paragraph("5.6 Deploy", h2_style))
    story.append(_numbered_list([
        "Click <b>Deploy</b>.",
        "Watch the build logs — Coolify will build the Docker image and start the container.",
        "Wait for the status to show <b>Running</b> and the healthcheck to pass.",
    ]))

    story.append(Paragraph("5.7 Verify the healthcheck", h2_style))
    story.append(Paragraph(
        "The compose file's healthcheck calls <b>GET /api/config</b> on port 8000. "
        "A healthy container returns HTTP 200. You can verify manually:",
        body_style,
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(_code_block(
        "curl -f http://192.168.0.161:8001/api/config"
    ))

    story.append(Paragraph("5.8 Open the app", h2_style))
    story.append(Paragraph(
        "Open <b>http://192.168.0.161:8001</b> in your browser. You should see the "
        "TradingAgents configuration page.",
        body_style,
    ))

    # ============ 6. DOCKERFILE ALTERNATIVE ============
    story.append(Paragraph("6. Dockerfile Build Pack (alternative)", h1_style))
    story.append(Paragraph(
        "If you prefer not to use Docker Compose, you can deploy with the "
        "<b>Dockerfile</b> build pack instead. In that case you must configure "
        "ports, environment variables, and storage manually in the Coolify UI.",
        body_style,
    ))
    story.append(Spacer(1, 0.15 * inch))
    story.append(_bullet_list([
        "<b>Build Pack</b> = Dockerfile",
        "<b>Base Directory</b> = /",
        "<b>Ports Expose</b> = 8000",
        "<b>Port Mapping</b> = 8001:8000",
        "Add the environment variables from section 4.3 manually.",
        "Add two <b>Persistent Storage</b> mounts: <b>/home/appuser/.tradingagents</b> and <b>/home/appuser/app/config</b>.",
    ]))

    # ============ 7. CONFIGURE API KEYS IN BROWSER ============
    story.append(Paragraph("7. Configure API Keys in the Browser", h1_style))
    story.append(Paragraph(
        "TradingAgents lets you save API keys directly in the browser — no need to "
        "set them in Coolify. Keys persist to <b>config/credentials.json</b> inside the "
        "container, backed by the <b>tradingagents_config</b> volume.",
        body_style,
    ))
    story.append(Spacer(1, 0.2 * inch))
    story.append(_numbered_list([
        "Open <b>http://192.168.0.161:8001</b> (or your Coolify domain).",
        "In the <b>LLM Configuration</b> section, select your provider (e.g. OpenAI).",
        "Enter your API key in the <b>API Key</b> field.",
        "Click <b>Save Key</b> — a checkmark confirms it was saved to the project config.",
        "Click <b>Validate & Fetch Models</b> to test the key and load available models.",
        "Select your Deep & Quick models, then click <b>Launch Analysis</b>.",
    ]))
    story.append(Paragraph(
        "Saved keys are loaded into the environment at startup, so analysis works "
        "immediately. Keys are stored in plaintext (like .env) and are excluded from "
        "version control via .gitignore.",
        note_style,
    ))

    # ============ 8. PERSISTENT STORAGE ============
    story.append(Paragraph("8. Persistent Storage", h1_style))
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

    # ============ 9. TROUBLESHOOTING ============
    story.append(Paragraph("9. Troubleshooting", h1_style))

    story.append(Paragraph("9.1 Build fails or container exits immediately", h2_style))
    story.append(_bullet_list([
        "Make sure the <b>Build Pack</b> is <b>Docker Compose</b> (or Dockerfile), not Nixpacks.",
        "Confirm <b>Ports Expose</b> is <b>8000</b>, not 3000.",
        "Check that <b>Custom Docker Options</b> does not contain Nixpacks flags.",
        "Look at the <b>Logs</b> tab in Coolify for the exact error.",
    ]))

    story.append(Paragraph("9.2 Healthcheck failing", h2_style))
    story.append(Paragraph(
        "If the container shows unhealthy, check that the app is listening on port 8000 "
        "inside the container and that the Dockerfile CMD uses uvicorn:",
        body_style,
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(_code_block(
        'CMD ["uvicorn", "app.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]'
    ))

    story.append(Paragraph("9.3 Port conflict", h2_style))
    story.append(Paragraph(
        "Coolify uses host port 8000. If you try to map the app to host port 8000 as "
        "well, the container will fail to start. Use host port 8001 (or another free "
        "port) and point Coolify at container port 8000.",
        body_style,
    ))

    story.append(Paragraph("9.4 Cannot reach the app from browser", h2_style))
    story.append(_bullet_list([
        "Verify the VM firewall allows inbound traffic on port 8001.",
        "Confirm the container is running: <b>docker ps</b> on the VM.",
        "Check the app logs in Coolify for startup errors.",
        "If you used a Coolify domain, make sure DNS resolves to the VM.",
    ]))

    story.append(Paragraph("9.5 API key not working", h2_style))
    story.append(_bullet_list([
        "Ensure you clicked <b>Save Key</b> (not just typed the key).",
        "Verify the key is valid with <b>Validate & Fetch Models</b>.",
        "Check that the <b>tradingagents_config</b> volume is mounted so the key persists.",
    ]))

    # ============ 10. SECURITY ============
    story.append(Paragraph("10. Security Notes", h1_style))
    story.append(_bullet_list([
        "<b>config/credentials.json</b> is excluded from git via .gitignore — never commit API keys.",
        "Keys are stored in plaintext (same as .env). Protect the VM and volume access.",
        "The app is exposed on the LAN. Restrict access with a firewall or Coolify's "
        "authentication if needed.",
        "Use Coolify's environment variables for non-secret config; use the browser "
        "Save Key feature for secrets.",
    ]))

    # ============ 11. SUMMARY ============
    story.append(Paragraph("11. Quick Reference", h1_style))
    story.append(_bullet_list([
        "Coolify dashboard: <b>http://192.168.0.161:8000</b>",
        "TradingAgents app: <b>http://192.168.0.161:8001</b>",
        "Build pack: <b>Docker Compose</b> with <b>docker-compose.coolify.yml</b>",
        "Container port: <b>8000</b>",
        "Host port: <b>8001</b>",
        "Healthcheck: <b>GET /api/config</b>",
        "Config store: <b>config/credentials.json</b> (volume: tradingagents_config)",
        "Web server: <b>Dockerfile</b> → uvicorn on 0.0.0.0:8000",
    ]))

    doc.build(story)
    print(f"PDF saved to {OUTPUT_PDF}")


if __name__ == "__main__":
    build_pdf()
