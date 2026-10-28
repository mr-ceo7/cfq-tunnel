"""Places a new tunnel address can be published to. Each publisher's publish(url) returns True on success."""

import json
import logging
import os
import subprocess
import tempfile
import urllib.error
import urllib.request

log = logging.getLogger("cfq-tunnel")


def _request(url, body, headers, method="POST", timeout=15):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method=method,
                                     headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status


class EdgeConfig:
    """Upserts the address into a Vercel Edge Config item, read by a Vercel middleware proxy."""

    name = "vercel-edge-config"
    api = "https://api.vercel.com"

    def __init__(self, config_id, token, key="api_origin", team_id=""):
        if not config_id or not token:
            raise ValueError("Edge Config publishing needs a config id and a Vercel token")
        self.config_id, self.token, self.key, self.team_id = config_id, token, key, team_id

    def publish(self, url):
        endpoint = f"{self.api}/v1/edge-config/{self.config_id}/items"
        if self.team_id:
            endpoint += f"?teamId={self.team_id}"
        try:
            _request(endpoint, {"items": [{"operation": "upsert", "key": self.key, "value": url}]},
                     {"Authorization": f"Bearer {self.token}"}, method="PATCH")
            return True
        except urllib.error.HTTPError as exc:
            log.error("Edge Config update failed: HTTP %s %s", exc.code, exc.read()[:200])
        except OSError as exc:
            log.error("Edge Config update failed: %s", exc)
        return False


class Webhook:
    """POSTs {"url": ..., "hostname": ...} to an endpoint, with an optional bearer token."""

    name = "webhook"

    def __init__(self, endpoint, token=""):
        self.endpoint, self.token = endpoint, token

    def publish(self, url):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            status = _request(self.endpoint, {"url": url, "hostname": url.split("://", 1)[-1]}, headers)
            return 200 <= status < 300
        except urllib.error.HTTPError as exc:
            log.error("Webhook %s answered HTTP %s", self.endpoint, exc.code)
        except OSError as exc:
            log.error("Webhook %s failed: %s", self.endpoint, exc)
        return False


class File:
    """Writes the address to a file (atomically), for anything that reads it from disk."""

    name = "file"

    def __init__(self, path):
        self.path = os.path.expanduser(path)

    def publish(self, url):
        directory = os.path.dirname(os.path.abspath(self.path))
        try:
            os.makedirs(directory, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", dir=directory, delete=False) as handle:
                handle.write(url + "\n")
            os.replace(handle.name, self.path)
            return True
        except OSError as exc:
            log.error("Couldn't write %s: %s", self.path, exc)
            return False


class Command:
    """Runs a shell command with the address in $CFQ_URL and $CFQ_HOSTNAME (and `{url}` substituted)."""

    name = "command"

    def __init__(self, command, timeout=60):
        self.command, self.timeout = command, timeout

    def publish(self, url):
        env = {**os.environ, "CFQ_URL": url, "CFQ_HOSTNAME": url.split("://", 1)[-1]}
        try:
            result = subprocess.run(self.command.replace("{url}", url), shell=True, env=env,
                                    capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            log.error("Hook timed out after %ss: %s", self.timeout, self.command)
            return False
        if result.returncode != 0:
            log.error("Hook exited %s: %s", result.returncode, (result.stderr or result.stdout).strip()[:300])
            return False
        return True
