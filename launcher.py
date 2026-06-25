"""
launcher.py — PyInstaller entry point for Survey Generator.
Invokes Streamlit programmatically so the binary works without
needing `streamlit run` on the command line.
"""
import sys
import os
import socket
from pathlib import Path


def _find_free_port(start=8501, end=8510):
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("localhost", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found between {start} and {end}")


def main():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    app  = str(base / "survey_app.py")

    from streamlit.web import cli as stcli

    port = _find_free_port()

    os.environ["STREAMLIT_SERVER_HEADLESS"]            = "true"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"]    = "false"
    os.environ["STREAMLIT_SERVER_PORT"]                = str(port)

    import threading, webbrowser, time
    def open_browser():
        time.sleep(4)
        webbrowser.open(f"http://localhost:{port}")
    threading.Thread(target=open_browser, daemon=True).start()

    sys.argv = ["streamlit", "run", app, "--server.port", str(port)]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
