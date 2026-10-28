from cfq_tunnel.watchdog import Settings, Watchdog


class FakeProcess:
    def __init__(self, host):
        self.host = host
        self.code = None
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        self.code = -9


class Recorder:
    name = "recorder"

    def __init__(self, ok=True):
        self.urls = []
        self.ok = ok

    def publish(self, url):
        self.urls.append(url)
        return self.ok


class Harness:
    """Drives a Watchdog with fake cloudflared processes, health and time."""

    def __init__(self, hosts, publisher=None, failures=3):
        self.hosts = list(hosts)
        self.processes = []
        self.health = {}
        self.now = 0.0
        self.publisher = publisher or Recorder()
        settings = Settings(origin="http://127.0.0.1:8000", failures=failures, interval=15,
                            startup_timeout=10, settle_timeout=10)
        self.watchdog = Watchdog(settings, [self.publisher], start=self.start, hostname=self.hostname,
                                 healthy=lambda host: self.health.get(host, True), sleep=self.sleep,
                                 clock=lambda: self.now)

    def start(self):
        process = FakeProcess(self.hosts.pop(0) if self.hosts else "")
        self.processes.append(process)
        return process

    def hostname(self):
        return self.processes[-1].host

    def sleep(self, seconds):
        self.now += seconds


def test_publishes_the_first_address_once():
    h = Harness(["one.trycloudflare.com"])
    for _ in range(4):
        h.watchdog.step()
    assert h.publisher.urls == ["https://one.trycloudflare.com"]
    assert len(h.processes) == 1


def test_restarts_after_repeated_failures_and_publishes_the_new_address():
    h = Harness(["one.trycloudflare.com", "two.trycloudflare.com"])
    h.watchdog.step()
    h.health["one.trycloudflare.com"] = False
    for _ in range(3):
        h.watchdog.step()
    assert h.processes[0].terminated
    h.watchdog.step()
    assert h.publisher.urls == ["https://one.trycloudflare.com", "https://two.trycloudflare.com"]
    assert h.watchdog.restarts == 1


def test_a_single_failure_does_not_restart():
    h = Harness(["one.trycloudflare.com"])
    h.watchdog.step()
    h.health["one.trycloudflare.com"] = False
    h.watchdog.step()
    h.health["one.trycloudflare.com"] = True
    for _ in range(5):
        h.watchdog.step()
    assert len(h.processes) == 1 and h.watchdog.failures == 0


def test_a_crashed_cloudflared_is_replaced():
    h = Harness(["one.trycloudflare.com", "two.trycloudflare.com"])
    h.watchdog.step()
    h.processes[0].code = 1
    h.watchdog.step()
    assert len(h.processes) == 2
    assert h.publisher.urls[-1] == "https://two.trycloudflare.com"


def test_no_address_means_try_again():
    h = Harness(["", "one.trycloudflare.com"])
    h.watchdog.step()
    assert h.processes[0].terminated and h.publisher.urls == []
    h.watchdog.step()
    assert h.publisher.urls == ["https://one.trycloudflare.com"]


def test_failed_publish_is_retried_on_the_next_pass():
    publisher = Recorder(ok=False)
    h = Harness(["one.trycloudflare.com"], publisher=publisher)
    h.watchdog.step()
    publisher.ok = True
    h.watchdog.step()
    h.watchdog.step()
    assert publisher.urls == ["https://one.trycloudflare.com"] * 2


def test_publishes_even_if_the_new_host_is_slow_to_answer():
    h = Harness(["slow.trycloudflare.com"])
    h.health["slow.trycloudflare.com"] = False
    h.watchdog.step()
    assert h.publisher.urls == ["https://slow.trycloudflare.com"]
