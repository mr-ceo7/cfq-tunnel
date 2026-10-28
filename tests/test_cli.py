import pytest

from cfq_tunnel import cli
from cfq_tunnel.publishers import Command, EdgeConfig, File, Webhook


def parse(*argv):
    import argparse
    parser = argparse.ArgumentParser()
    cli.add_run_arguments(parser)
    return parser.parse_args(argv)


def test_publishers_from_flags(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "tok")
    monkeypatch.setenv("CFQ_WEBHOOK_TOKEN", "hook")
    args = parse("--url", "http://127.0.0.1:8000", "--edge-config", "ecfg_1", "--vercel-team", "team_1",
                 "--webhook", "https://a/hook", "--write-file", "/tmp/u", "--on-change", "echo {url}")
    kinds = [type(p) for p in cli.build_publishers(args)]
    assert kinds == [EdgeConfig, Webhook, File, Command]
    edge = cli.build_publishers(args)[0]
    assert (edge.token, edge.team_id, edge.key) == ("tok", "team_1", "api_origin")


def test_edge_config_without_token_is_refused(monkeypatch):
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    with pytest.raises(ValueError):
        cli.build_publishers(parse("--url", "http://x", "--edge-config", "ecfg_1"))


def test_status_without_a_tunnel(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["status", "--metrics", "127.0.0.1:9"])
    assert exc.value.code == 1


def test_systemd_unit(capsys):
    cli.main(["systemd", "--name", "api", "--user", "svc", "--env-file", "/etc/cfq.env", "--",
              "--url", "http://127.0.0.1:8000", "--health-path", "/health"])
    unit = capsys.readouterr().out
    assert "User=svc" in unit and "EnvironmentFile=-/etc/cfq.env" in unit
    assert "run --url http://127.0.0.1:8000 --health-path /health" in unit


def test_systemd_needs_run_options():
    with pytest.raises(SystemExit):
        cli.main(["systemd"])


def test_normalize_target_url():
    assert cli.normalize_target_url("3000") == "http://127.0.0.1:3000"
    assert cli.normalize_target_url("8080") == "http://127.0.0.1:8080"
    assert cli.normalize_target_url("localhost:3000") == "http://localhost:3000"
    assert cli.normalize_target_url("http://127.0.0.1:9000") == "http://127.0.0.1:9000"
    assert cli.normalize_target_url("https://example.com") == "https://example.com"


def test_http_subcommand_dispatch(monkeypatch):
    recorded_settings = []

    class DummyWatchdog:
        def __init__(self, settings, publishers):
            recorded_settings.append(settings)

        def stop(self, *a):
            pass

        def run(self):
            pass

    monkeypatch.setattr(cli, "Watchdog", DummyWatchdog)

    # Test "http 3000"
    cli.main(["http", "3000"])
    assert recorded_settings[-1].origin == "http://127.0.0.1:3000"

    # Test shorthand "3000"
    cli.main(["3000"])
    assert recorded_settings[-1].origin == "http://127.0.0.1:3000"

    # Test "http http://localhost:8080"
    cli.main(["http", "http://localhost:8080"])
    assert recorded_settings[-1].origin == "http://localhost:8080"

