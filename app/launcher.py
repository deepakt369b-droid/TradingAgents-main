"""TradingAgents Desktop Launcher.

Opens the FastAPI server in a background thread and launches a native
``pywebview`` window.  The system tray (via ``pystray``) keeps the app alive
when the window is closed and shows notifications when analysis finishes in
the background.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 18710
_APP_TITLE = "TradingAgents v0.3.0"
_WINDOW_WIDTH = 1400
_WINDOW_HEIGHT = 900
_MIN_WIDTH = 1000
_MIN_HEIGHT = 650

# Globals for cross-thread coordination
_server_thread: threading.Thread | None = None
_tray_icon = None
_webview_window = None
_shutdown_event = threading.Event()


def _find_free_port(preferred: int = _DEFAULT_PORT) -> int:
    """Return *preferred* if available, otherwise pick a random free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def _start_server(port: int) -> None:
    """Run the uvicorn server in the current thread (blocking)."""
    try:
        import uvicorn
        from app.server import create_app

        app = create_app()
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            # Disable access logs to keep the console clean
            access_log=False,
        )
    except Exception as e:
        import traceback
        with open("server_crash.log", "w") as f:
            traceback.print_exc(file=f)


def _create_tray_icon(port: int):
    """Build and return a pystray system tray icon.

    Falls back gracefully when pystray or Pillow are unavailable (e.g. during
    development without the [desktop] extra).
    """
    global _tray_icon
    try:
        import pystray
        from PIL import Image, ImageDraw

        # Generate a simple icon (blue circle with "TA" text)
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Background circle
        draw.ellipse([4, 4, 60, 60], fill=(0, 212, 255, 230))
        # Simple "T" letter
        draw.text((20, 16), "T", fill=(255, 255, 255, 255))

        def on_open(icon, item):
            """Show the webview window."""
            global _webview_window
            if _webview_window:
                try:
                    _webview_window.show()
                    _webview_window.restore()
                except Exception:
                    pass

        def on_new_analysis(icon, item):
            """Open window and navigate to config view."""
            on_open(icon, item)

        def on_check_updates(icon, item):
            """Trigger update check."""
            try:
                from app.updater import check_for_update
                result = check_for_update()
                if result.get("update_available"):
                    icon.notify(
                        f"Update available: {result['latest_version']}",
                        "TradingAgents Update",
                    )
                else:
                    icon.notify(
                        f"You're up to date (v{result['current_version']})",
                        "TradingAgents",
                    )
            except Exception:
                pass

        def on_quit(icon, item):
            """Shut down everything."""
            _shutdown_event.set()
            icon.stop()
            # Close webview window
            global _webview_window
            if _webview_window:
                try:
                    _webview_window.destroy()
                except Exception:
                    pass

        menu = pystray.Menu(
            pystray.MenuItem("Open Window", on_open, default=True),
            pystray.MenuItem("New Analysis", on_new_analysis),
            pystray.MenuItem("Check for Updates", on_check_updates),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        )

        _tray_icon = pystray.Icon(
            name="TradingAgents",
            icon=img,
            title="TradingAgents",
            menu=menu,
        )
        return _tray_icon

    except ImportError:
        logger.warning("pystray/Pillow not installed — system tray disabled")
        return None


def _on_window_closing():
    """Called when the user closes the webview window.

    Instead of quitting, minimize to system tray.
    """
    global _webview_window, _tray_icon
    if _tray_icon is not None:
        # Hide the window instead of destroying it
        try:
            _webview_window.hide()
        except Exception:
            pass
        return False  # Prevent default close behavior
    return True  # No tray → actually close


def main():
    """Entry point for ``tradingagents-desktop`` and ``python -m app``."""

    # Ensure UTF-8 on Windows
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONUTF8", "1")

    # Fix for uvicorn crashing when sys.stdout is None in PyInstaller windowed mode
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"

    # Start server in a daemon thread
    global _server_thread
    _server_thread = threading.Thread(
        target=_start_server,
        args=(port,),
        daemon=True,
        name="uvicorn-server",
    )
    _server_thread.start()

    # Wait for the server to be ready
    import time
    for _ in range(50):  # Wait up to 5 seconds
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.1)

    # Create system tray icon (runs in its own thread)
    tray = _create_tray_icon(port)
    if tray is not None:
        tray_thread = threading.Thread(
            target=tray.run,
            daemon=True,
            name="system-tray",
        )
        tray_thread.start()

    # Create native window
    try:
        import webview

        global _webview_window
        _webview_window = webview.create_window(
            title=_APP_TITLE,
            url=url,
            width=_WINDOW_WIDTH,
            height=_WINDOW_HEIGHT,
            min_size=(_MIN_WIDTH, _MIN_HEIGHT),
            resizable=True,
            text_select=True,
        )

        # If we have a tray, intercept close to minimize instead
        if tray is not None:
            _webview_window.events.closing += _on_window_closing

        # Start the webview event loop (blocks until window is destroyed)
        webview.start(debug=False)

    except ImportError:
        # pywebview not installed — fall back to browser
        logger.warning("pywebview not installed — opening in browser")
        import webbrowser
        webbrowser.open(url)
        print(f"\n  TradingAgents Desktop running at {url}")
        print("  Press Ctrl+C to stop.\n")
        try:
            _shutdown_event.wait()
        except KeyboardInterrupt:
            pass

    # Cleanup
    if tray is not None:
        try:
            tray.stop()
        except Exception:
            pass

    print("TradingAgents Desktop stopped.")


if __name__ == "__main__":
    main()
