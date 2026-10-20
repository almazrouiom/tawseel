"""Production launcher for the Tawseel website.

On Windows the app is served with Waitress. On Linux/macOS use Gunicorn
through the Procfile/Dockerfile, or `waitress-serve --listen=0.0.0.0:8000 wsgi:app`.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser

from tawseel import create_app

app = create_app()


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _pick_port(host: str, preferred: int) -> int:
    if _port_available(host, preferred):
        return preferred
    for port in range(preferred + 1, preferred + 20):
        if _port_available(host, port):
            print(f"Port {preferred} is busy; using {port} instead.", file=sys.stderr)
            return port
    raise SystemExit(f"No free port found near {preferred}. Stop the other server or pass --port.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Tawseel website.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    parser.add_argument("--open", action="store_true", help="Open the site in the default browser.")
    parser.add_argument("--no-port-fallback", action="store_true")
    args = parser.parse_args()

    port = args.port if args.no_port_fallback else _pick_port(args.host, args.port)
    base_url = app.config["PUBLIC_BASE_URL"]
    print()
    print("  Tawseel")
    print(f"  Public site: {base_url}")
    print(f"  Local URL:   http://{args.host}:{port}/")
    print(f"  Admin:       http://{args.host}:{port}/admin/login")
    print(f"  Environment: {app.config['APP_ENV']}")
    if app.config["SMS_PROVIDER"] == "log":
        print("  SMS:         development console mode (OTP printed in this terminal)")
    else:
        print(f"  SMS:         {app.config['SMS_PROVIDER']}")
    print("  Press Ctrl+C to stop.")
    print()

    if args.open:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://{args.host}:{port}/")).start()

    try:
        from waitress import serve
    except ImportError:
        print("Waitress is not installed; falling back to Flask's development server.", file=sys.stderr)
        app.run(host=args.host, port=port, debug=False, threaded=True)
        return

    serve(
        app,
        host=args.host,
        port=port,
        threads=8,
        ident="Tawseel",
        channel_timeout=120,
    )


if __name__ == "__main__":
    main()
