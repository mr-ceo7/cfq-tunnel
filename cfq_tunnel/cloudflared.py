"""Starting cloudflared and asking it for the quick tunnel's address."""

import json
import shutil
import subprocess
import urllib.request


def find_binary(explicit=None):
    path = explicit or shutil.which("cloudflared") or "/usr/local/bin/cloudflared"
    return path


def start(binary, origin, metrics, extra_args=()):
    """Run `cloudflared tunnel --url <origin>` with its metrics server on `metrics` (host:port)."""
    command = [binary, "tunnel", "--no-autoupdate", "--metrics", metrics, *extra_args, "--url", origin]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def hostname(metrics, timeout=3):
    """The *.trycloudflare.com host cloudflared was given, from its /quicktunnel endpoint; '' if not ready."""
    try:
        with urllib.request.urlopen(f"http://{metrics}/quicktunnel", timeout=timeout) as response:
            return (json.loads(response.read() or b"{}") or {}).get("hostname") or ""
    except (OSError, ValueError, AttributeError):
        return ""
