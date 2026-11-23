"""Desktop launcher: opens the app in its own window (no address bar, no tabs,
no browser look), like a Cordova / Electron app.

Preferred : pywebview  (uses Edge WebView2, already on Windows 10/11)
Fallback  : Edge / Chrome in --app mode (also a chrome-less window)
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

from werkzeug.serving import make_server

from app import app
from backup import start_backup_scheduler

TITLE = "Agni Gas Agency"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _find_browser() -> str | None:
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if not base:
            continue
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            path = os.path.join(base, rel)
            if os.path.exists(path):
                return path
    return None


def _app_window_fallback(url: str) -> None:
    browser = _find_browser()
    if not browser:
        import webbrowser

        webbrowser.open(url)
        threading.Event().wait()  # keep serving until the process is closed
        return
    # A private profile makes the process stay alive until the window closes.
    profile = tempfile.mkdtemp(prefix="agni-window-")
    subprocess.call([browser, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1366,820"])
    shutil.rmtree(profile, ignore_errors=True)


def main() -> None:
    backup_stop, backup_thread = start_backup_scheduler()
    port = _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"

    try:
        import webview
    except ImportError:
        webview = None

    if webview:
        webview.create_window(TITLE, url, width=1366, height=820, min_size=(1000, 650))
        webview.start()
    else:
        _app_window_fallback(url)

    server.shutdown()
    backup_stop.set()
    backup_thread.join(timeout=2)
    sys.exit(0)


if __name__ == "__main__":
    main()
