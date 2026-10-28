"""Command line: run the watchdog, show the current address, or print a systemd unit."""

import argparse
import logging
import os
import shlex
import signal
import sys

from cfq_tunnel import __version__, cloudflared
from cfq_tunnel.publishers import Command, EdgeConfig, File, Webhook
from cfq_tunnel.watchdog import Settings, Watchdog, force_ipv4

DEFAULT_METRICS = "127.0.0.1:20242"


def normalize_target_url(target: str) -> str:
    """Normalizes a port number or raw host into a valid http(s) URL."""
    target = target.strip()
    if target.isdigit():
        return f"http://127.0.0.1:{target}"
    if not target.startswith(("http://", "https://")):
        return f"http://{target}"
    return target


def _env(name):
    return os.environ.get(name, "") if name else ""


def build_publishers(args):
    publishers = []
    if args.edge_config:
        publishers.append(EdgeConfig(args.edge_config, _env(args.vercel_token_env), key=args.edge_config_key,
                                     team_id=args.vercel_team or _env("VERCEL_TEAM_ID")))
    for endpoint in args.webhook or []:
        publishers.append(Webhook(endpoint, _env(args.webhook_token_env)))
    for path in args.write_file or []:
        publishers.append(File(path))
    for command in args.on_change or []:
        publishers.append(Command(command))
    return publishers


def add_run_arguments(parser, url_required=True):
    if url_required:
        parser.add_argument("--url", required=True, help="origin the tunnel serves, e.g. http://127.0.0.1:8000")
    else:
        parser.add_argument("port_or_url", nargs="?", default="",
                            help="port or URL the tunnel serves (e.g. 3000, http://127.0.0.1:3000)")
        parser.add_argument("--url", default="", help="origin the tunnel serves (optional when port_or_url is given)")

    parser.add_argument("--health-path", default="/", help="path checked through the tunnel (default: /)")
    parser.add_argument("--interval", type=float, default=15, help="seconds between health checks (default: 15)")
    parser.add_argument("--failures", type=int, default=3, help="failed checks before a fresh tunnel (default: 3)")
    parser.add_argument("--metrics", default=DEFAULT_METRICS,
                        help=f"cloudflared metrics address; unique per tunnel (default: {DEFAULT_METRICS})")
    parser.add_argument("--cloudflared", default="", help="path to cloudflared (default: from PATH)")
    parser.add_argument("--ipv4", action="store_true", help="resolve over IPv4 only for health checks")
    pub = parser.add_argument_group("publishing a new address")
    pub.add_argument("--edge-config", metavar="ID", help="Vercel Edge Config id (ecfg_...) to upsert the URL into")
    pub.add_argument("--edge-config-key", default="api_origin", help="Edge Config item key (default: api_origin)")
    pub.add_argument("--vercel-team", default="", help="Vercel team id, if the Edge Config belongs to a team")
    pub.add_argument("--vercel-token-env", default="VERCEL_TOKEN",
                     help="environment variable holding the Vercel token (default: VERCEL_TOKEN)")
    pub.add_argument("--webhook", action="append", metavar="URL", help='POST {"url", "hostname"} here (repeatable)')
    pub.add_argument("--webhook-token-env", default="CFQ_WEBHOOK_TOKEN",
                     help="environment variable with a bearer token for webhooks (default: CFQ_WEBHOOK_TOKEN)")
    pub.add_argument("--write-file", action="append", metavar="PATH", help="write the URL to this file (repeatable)")
    pub.add_argument("--on-change", action="append", metavar="CMD",
                     help="shell command run with $CFQ_URL / $CFQ_HOSTNAME / {url} (repeatable)")


def cmd_run(args):
    # Resolve target URL from either positional port_or_url or --url
    origin_url = getattr(args, "url", None)
    port_or_url = getattr(args, "port_or_url", None)

    if not origin_url and port_or_url:
        origin_url = normalize_target_url(port_or_url)
    elif origin_url:
        origin_url = normalize_target_url(origin_url)
    else:
        sys.exit("cfq-tunnel: specify a port or URL to tunnel (e.g. cfq-tunnel http 3000 or cfq-tunnel run --url http://127.0.0.1:8000)")

    if args.ipv4:
        force_ipv4()
    try:
        publishers = build_publishers(args)
    except ValueError as exc:
        sys.exit(f"cfq-tunnel: {exc}")
    settings = Settings(origin=origin_url, health_path=args.health_path, interval=args.interval,
                        failures=args.failures, metrics=args.metrics, binary=args.cloudflared)
    watchdog = Watchdog(settings, publishers)
    signal.signal(signal.SIGTERM, watchdog.stop)
    signal.signal(signal.SIGINT, watchdog.stop)
    watchdog.run()


def cmd_status(args):
    host = cloudflared.hostname(args.metrics)
    if not host:
        print(f"No quick tunnel answering on {args.metrics}", file=sys.stderr)
        return 1
    print(f"https://{host}")
    return 0


def cmd_systemd(args, run_args):
    has_valid_target = any(
        arg == "--url" or arg == "http" or arg.isdigit() for arg in run_args
    )
    if not run_args or not has_valid_target:
        sys.exit("cfq-tunnel systemd: pass the run options after --, e.g. cfq-tunnel systemd -- --url http://127.0.0.1:8000")
    executable = os.path.abspath(sys.argv[0]) if os.path.basename(sys.argv[0]).startswith("cfq-tunnel") else "cfq-tunnel"

    cmd_parts = list(run_args)
    if cmd_parts[0] != "run" and cmd_parts[0] != "http":
        if cmd_parts[0].isdigit():
            cmd_parts = ["http"] + cmd_parts
        else:
            cmd_parts = ["run"] + cmd_parts

    lines = [
        "[Unit]",
        f"Description=Cloudflare quick tunnel ({args.name})",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        f"User={args.user}",
    ]
    if args.env_file:
        lines.append(f"EnvironmentFile=-{args.env_file}")
    lines += [
        f"ExecStart={executable} {' '.join(shlex.quote(a) for a in cmd_parts)}",
        "Restart=always",
        "RestartSec=5",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
    ]
    print("\n".join(lines))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    run_args = []
    if "--" in argv:
        index = argv.index("--")
        argv, run_args = argv[:index], argv[index + 1:]

    # Convenience shorthand: if first arg is a number or URL, automatically prepend "http"
    if argv and argv[0] not in ("run", "status", "systemd", "http", "-h", "--help", "-v", "--version"):
        if argv[0].isdigit() or argv[0].startswith(("http://", "https://", "localhost:")):
            argv = ["http"] + argv

    parser = argparse.ArgumentParser(prog="cfq-tunnel",
                                     description="Keep a Cloudflare quick tunnel alive and publish its address.")
    parser.add_argument("--version", action="version", version=f"cfq-tunnel {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    
    # "http" shorthand command: e.g. cfq-tunnel http 3000
    http_parser = sub.add_parser("http", help="run a quick tunnel to a local port or URL (e.g. cfq-tunnel http 3000)")
    add_run_arguments(http_parser, url_required=False)

    # "run" full command: e.g. cfq-tunnel run --url http://127.0.0.1:8000
    add_run_arguments(sub.add_parser("run", help="run the tunnel and the watchdog"))

    status = sub.add_parser("status", help="print the current tunnel URL")
    status.add_argument("--metrics", default=DEFAULT_METRICS)
    unit = sub.add_parser("systemd", help="print a systemd unit; put the run options after --")
    unit.add_argument("--name", default="cfq-tunnel")
    unit.add_argument("--user", default=os.environ.get("USER", "root"))
    unit.add_argument("--env-file", default="", help="EnvironmentFile for tokens (VERCEL_TOKEN, ...)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    if args.command in ("run", "http"):
        cmd_run(args)
    elif args.command == "status":
        sys.exit(cmd_status(args))
    else:
        cmd_systemd(args, run_args)


if __name__ == "__main__":
    main()
