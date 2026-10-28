import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cfq_tunnel import publishers
from cfq_tunnel.publishers import Command, EdgeConfig, File, Webhook


@pytest.fixture
def server():
    seen = []
    status = {"code": 200}

    class Handler(BaseHTTPRequestHandler):
        def _handle(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            seen.append({"method": self.command, "path": self.path, "auth": self.headers.get("Authorization"),
                         "body": json.loads(body or b"null")})
            self.send_response(status["code"])
            self.end_headers()
            self.wfile.write(b"{}")

        do_POST = do_PATCH = _handle

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", seen, status
    httpd.shutdown()


def test_edge_config_upserts_the_item(server, monkeypatch):
    base, seen, _ = server
    monkeypatch.setattr(EdgeConfig, "api", base)
    assert EdgeConfig("ecfg_1", "tok", key="api_origin", team_id="team_9").publish("https://a.trycloudflare.com")
    assert seen == [{"method": "PATCH", "path": "/v1/edge-config/ecfg_1/items?teamId=team_9", "auth": "Bearer tok",
                     "body": {"items": [{"operation": "upsert", "key": "api_origin",
                                         "value": "https://a.trycloudflare.com"}]}}]


def test_edge_config_reports_rejection(server, monkeypatch):
    base, _, status = server
    status["code"] = 403
    monkeypatch.setattr(EdgeConfig, "api", base)
    assert EdgeConfig("ecfg_1", "tok").publish("https://a.trycloudflare.com") is False


def test_edge_config_needs_id_and_token():
    with pytest.raises(ValueError):
        EdgeConfig("ecfg_1", "")


def test_webhook_posts_url_and_hostname(server):
    base, seen, _ = server
    assert Webhook(base + "/hook", token="s3cret").publish("https://b.trycloudflare.com")
    assert seen[0]["body"] == {"url": "https://b.trycloudflare.com", "hostname": "b.trycloudflare.com"}
    assert seen[0]["auth"] == "Bearer s3cret"


def test_webhook_without_token_sends_no_auth(server):
    base, seen, _ = server
    Webhook(base).publish("https://b.trycloudflare.com")
    assert seen[0]["auth"] is None


def test_webhook_failure(server):
    base, _, status = server
    status["code"] = 500
    assert Webhook(base).publish("https://b.trycloudflare.com") is False


def test_file_is_written(tmp_path):
    target = tmp_path / "nested" / "url.txt"
    assert File(str(target)).publish("https://c.trycloudflare.com")
    assert target.read_text() == "https://c.trycloudflare.com\n"
    assert os.listdir(target.parent) == ["url.txt"]  # no temp files left behind


def test_command_gets_the_url(tmp_path):
    out = tmp_path / "out"
    assert Command(f'echo "$CFQ_URL $CFQ_HOSTNAME {{url}}" > {out}').publish("https://d.trycloudflare.com")
    assert out.read_text().split() == ["https://d.trycloudflare.com", "d.trycloudflare.com", "https://d.trycloudflare.com"]


def test_command_failure_is_reported():
    assert Command("exit 3").publish("https://d.trycloudflare.com") is False


def test_command_timeout(monkeypatch):
    assert Command("sleep 5", timeout=0.2).publish("https://d.trycloudflare.com") is False


def test_unreachable_endpoints_fail_cleanly(monkeypatch):
    monkeypatch.setattr(EdgeConfig, "api", "http://127.0.0.1:9")
    assert EdgeConfig("ecfg_1", "tok").publish("https://x") is False
    assert Webhook("http://127.0.0.1:9").publish("https://x") is False
    assert publishers  # module imported
