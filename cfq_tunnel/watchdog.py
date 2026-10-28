"""
The supervisor: run cloudflared, check the origin through the tunnel, start a fresh tunnel after
repeated failures, and publish every new address.
"""

import logging
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from cfq_tunnel import cloudflared

log = logging.getLogger("cfq-tunnel")


@dataclass
class Settings:
    origin: str                       # what the tunnel points at, e.g. http://127.0.0.1:8000
    health_path: str = "/"            # checked through the tunnel; any 2xx/3xx/4xx below 500 counts as up
    interval: float = 15.0            # seconds between health checks
    failures: int = 3                 # failed checks in a row before starting a fresh tunnel
    metrics: str = "127.0.0.1:20242"  # cloudflared metrics address (each tunnel on a machine needs its own)
    binary: str = ""
    startup_timeout: float = 60.0     # how long cloudflared may take to report an address
    settle_timeout: float = 60.0      # how long a new hostname may take to start answering
    extra_args: list = field(default_factory=list)


def force_ipv4():
    """Resolve over IPv4 only. Some networks route IPv6 badly and make fresh tunnels look dead."""
    original = socket.getaddrinfo

    def ipv4_only(host, port, family=0, *args, **kwargs):
        return original(host, port, socket.AF_INET, *args, **kwargs)

    socket.getaddrinfo = ipv4_only


def check(url, timeout=10):
    """True when the URL answers with anything below 500 (Cloudflare answers 502/530 for a dead tunnel)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "cfq-tunnel"}),
                                    timeout=timeout) as response:
            return response.status < 500
    except urllib.error.HTTPError as exc:
        return exc.code < 500
    except OSError:
        return False


class Watchdog:
    def __init__(self, settings, publishers, *, start=None, hostname=None, healthy=None, sleep=None, clock=None):
        self.settings = settings
        self.publishers = list(publishers)
        binary = cloudflared.find_binary(settings.binary)
        self._start = start or (lambda: cloudflared.start(binary, settings.origin, settings.metrics, settings.extra_args))
        self._hostname = hostname or (lambda: cloudflared.hostname(settings.metrics))
        self._healthy = healthy or (lambda host: check(f"https://{host}{settings.health_path}"))
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self.running = True
        self.process = None
        self.host = ""
        self.published = ""
        self.restarts = 0
        self.failures = 0

    # -- one tunnel's life ------------------------------------------------------------------
    def _launch(self):
        log.info("Starting a quick tunnel to %s", self.settings.origin)
        self.process = self._start()
        deadline = self._clock() + self.settings.startup_timeout
        while self.running and self._clock() < deadline and self.process.poll() is None:
            host = self._hostname()
            if host:
                return host
            self._sleep(1)
        return ""

    def _settle(self, host):
        """A brand-new hostname takes a few seconds to resolve; wait for it before publishing."""
        deadline = self._clock() + self.settings.settle_timeout
        while self.running and self._clock() < deadline:
            if self._healthy(host):
                return True
            self._sleep(3)
        return False

    def _stop_process(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except Exception:  # noqa: BLE001 - a stuck cloudflared just gets killed
                self.process.kill()
        self.process = None

    def _publish(self, host):
        url = f"https://{host}"
        results = {p.name: p.publish(url) for p in self.publishers}
        if not self.publishers:
            log.info("Tunnel address: %s (no publishers configured)", url)
        elif all(results.values()):
            log.info("Published %s to %s", url, ", ".join(results))
        else:
            log.warning("Published %s; failed: %s (will retry)", url, ", ".join(k for k, ok in results.items() if not ok))
        return all(results.values())

    # -- the loop ---------------------------------------------------------------------------
    def step(self):
        """One pass: (re)start if needed, publish if the address changed, then one health check."""
        if self.process is None or self.process.poll() is not None:
            if self.process is not None:
                log.warning("cloudflared exited with %s", self.process.poll())
                self.restarts += 1
            self.host = self._launch()
            if not self.host:
                log.error("cloudflared reported no address; trying again")
                self._stop_process()
                self._sleep(5)
                return
            if not self._settle(self.host):
                log.warning("%s isn't answering yet; publishing anyway", self.host)
            self.failures = 0
        if self.host != self.published and self._publish(self.host):
            self.published = self.host
        self._sleep(self.settings.interval)
        if not self.running:
            return
        if self._healthy(self.host):
            self.failures = 0
            return
        self.failures += 1
        log.warning("Health check through %s failed (%s/%s)", self.host, self.failures, self.settings.failures)
        if self.failures >= self.settings.failures:
            self._stop_process()
            self.restarts += 1

    def run(self):
        try:
            while self.running:
                self.step()
        finally:
            self._stop_process()

    def stop(self, *_):
        self.running = False
