"""Host + container watchdog for the Reeltime VMs. Reports to the alert relay.

Follows the Docker event stream for crashes (non-zero exit not caused by a
`docker stop`/`kill`), out-of-memory kills and failing health checks. Every
CHECK_SECONDS it checks disk, memory, load, and that WATCH_CONTAINERS are
running. Each problem is reported once and again when it clears.

Env: RELAY_URL, RELAY_TOKEN, HOST_LABEL, WATCH_CONTAINERS (comma separated),
     CHECK_SECONDS (60), DISK_ALERT_PERCENT (85), MEM_ALERT_PERCENT (90),
     LOAD_ALERT_PER_CPU (2.0). Needs /var/run/docker.sock mounted.
Stdlib only, so the image is just python:alpine plus this file.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DOCKER_SOCKET = "/var/run/docker.sock"
LOG_TAIL_LINES = 25
LOG_TAIL_CHARS = 1800


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, timeout: float | None) -> None:
        super().__init__("localhost", timeout=timeout)

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(DOCKER_SOCKET)
        self.sock = sock


def docker_get(path: str, timeout: float = 10) -> tuple[int, bytes]:
    conn = _UnixHTTPConnection(timeout)
    try:
        conn.request("GET", path)
        res = conn.getresponse()
        return res.status, res.read()
    finally:
        conn.close()


def demux_logs(raw: bytes) -> str:
    """Docker log frames (8-byte header each) -> text. TTY logs pass through."""
    out, i = [], 0
    while i + 8 <= len(raw) and raw[i] in (0, 1, 2) and raw[i + 1 : i + 4] == b"\0\0\0":
        size = int.from_bytes(raw[i + 4 : i + 8], "big")
        out.append(raw[i + 8 : i + 8 + size])
        i += 8 + size
    data = b"".join(out) if i else raw
    return data.decode(errors="replace")


_QUERY = re.compile(r"\?[^\s\"']*")
_BEARER = re.compile(r"(?i)bearer\s+[\w.~+/=-]+")


def redact(text: str) -> str:
    # Playback URLs carry access tokens in the query string (?t=...).
    return _BEARER.sub("Bearer …", _QUERY.sub("?…", text))


def container_log_tail(container: str) -> str:
    status, raw = docker_get(
        f"/containers/{container}/logs?stdout=1&stderr=1&tail={LOG_TAIL_LINES}"
    )
    if status != 200:
        return ""
    return redact(demux_logs(raw).strip())[-LOG_TAIL_CHARS:]


class Condition:
    """Report once after `needed` bad checks in a row, and once when it clears."""

    def __init__(self, needed: int = 1) -> None:
        self.needed = needed
        self.bad_streak = 0
        self.active = False

    def update(self, bad: bool) -> str | None:
        if bad:
            self.bad_streak += 1
            if not self.active and self.bad_streak >= self.needed:
                self.active = True
                return "fire"
            return None
        self.bad_streak = 0
        if self.active:
            self.active = False
            return "resolve"
        return None


def is_crash(exit_code: int, now: float, stopped_at: float | None) -> bool:
    """A non-zero exit nobody asked for (`docker stop/kill` sends a kill event first)."""
    if exit_code == 0:
        return False
    return stopped_at is None or now - stopped_at > 60


def memory_used_percent(meminfo: str) -> float:
    values = {}
    for line in meminfo.splitlines():
        key, _, rest = line.partition(":")
        values[key] = int(rest.split()[0]) if rest.split() else 0
    total = values.get("MemTotal", 0)
    if not total:
        return 0.0
    return 100 * (1 - values.get("MemAvailable", total) / total)


class Watchdog:
    def __init__(self, env: dict[str, str]) -> None:
        self.relay_url = env["RELAY_URL"].rstrip("/") + "/event"
        self.relay_token = env["RELAY_TOKEN"]
        self.host = env.get("HOST_LABEL") or socket.gethostname()
        self.watch = [c.strip() for c in env.get("WATCH_CONTAINERS", "").split(",") if c.strip()]
        self.check_seconds = float(env.get("CHECK_SECONDS", "60"))
        self.disk_limit = float(env.get("DISK_ALERT_PERCENT", "85"))
        self.mem_limit = float(env.get("MEM_ALERT_PERCENT", "90"))
        self.load_limit = float(env.get("LOAD_ALERT_PER_CPU", "2.0"))
        self.disk = Condition()
        self.memory = Condition(needed=3)
        self.load = Condition(needed=3)
        # Two misses so a deploy's quick container swap doesn't page anyone.
        self.down = {name: Condition(needed=2) for name in self.watch}
        self.unhealthy: set[str] = set()
        self.stopped_at: dict[str, float] = {}
        self.oom_at: dict[str, float] = {}

    def send(
        self, level: str, title: str, detail: str = "", fingerprint: str | None = None
    ) -> None:
        body = {
            "source": self.host,
            "level": level,
            "title": title,
            "detail": detail,
            "fingerprint": fingerprint,
        }
        req = urllib.request.Request(
            self.relay_url,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.relay_token}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                res.read()
        except (urllib.error.URLError, OSError) as exc:
            print(f"relay unreachable: {exc!r}", flush=True)

    # --- Docker events -------------------------------------------------------

    def handle_event(self, event: dict) -> None:
        action = event.get("Action", "")
        attrs = (event.get("Actor") or {}).get("Attributes") or {}
        name = attrs.get("name", "?")
        cid = (event.get("Actor") or {}).get("ID", "")
        now = time.monotonic()

        if action in ("kill", "stop"):
            self.stopped_at[cid] = now
        elif action == "oom":
            self.oom_at[cid] = now
        elif action == "die":
            exit_code = int(attrs.get("exitCode", "0") or 0)
            oom = now - self.oom_at.pop(cid, -1e9) < 30
            if not oom and not is_crash(exit_code, now, self.stopped_at.pop(cid, None)):
                return
            title = (
                f"Container {name} was killed: out of memory"
                if oom
                else f"Container {name} crashed (exit {exit_code})"
            )
            try:
                note, logs = self.restart_note(cid), container_log_tail(cid)
            except Exception:  # still send the alert without the extras
                note, logs = "", ""
            detail = f"{note}\n\nLast log lines:\n{logs}" if logs else note
            self.send("error", title, detail, f"{self.host}:crash:{name}")
        elif action.startswith("health_status"):
            status = action.split(":", 1)[-1].strip()
            if status == "unhealthy" and name not in self.unhealthy:
                self.unhealthy.add(name)
                try:
                    output = self.health_output(cid)
                except Exception:
                    output = ""
                self.send(
                    "warning",
                    f"Container {name} is unhealthy",
                    output,
                    f"{self.host}:health:{name}",
                )
            elif status == "healthy" and name in self.unhealthy:
                self.unhealthy.discard(name)
                self.send(
                    "resolved",
                    f"Container {name} is healthy again",
                    "",
                    f"{self.host}:health:{name}",
                )

    def restart_note(self, cid: str) -> str:
        status, raw = docker_get(f"/containers/{cid}/json")
        if status != 200:
            return ""
        policy = json.loads(raw).get("HostConfig", {}).get("RestartPolicy", {}).get("Name") or "no"
        if policy == "no":
            return "No restart policy: it stays down until someone starts it."
        return f"Docker will restart it (restart policy: {policy})."

    def health_output(self, cid: str) -> str:
        status, raw = docker_get(f"/containers/{cid}/json")
        if status != 200:
            return ""
        log = (json.loads(raw).get("State", {}).get("Health") or {}).get("Log") or []
        return redact((log[-1].get("Output") or "").strip())[-LOG_TAIL_CHARS:] if log else ""

    def follow_events(self) -> None:
        query = urllib.parse.urlencode({"filters": json.dumps({"type": ["container"]})})
        while True:
            try:
                conn = _UnixHTTPConnection(timeout=None)
                conn.request("GET", f"/events?{query}")
                res = conn.getresponse()
                for line in res:
                    if line.strip():
                        self.handle_event(json.loads(line))
            except Exception as exc:  # keep watching whatever happens
                print(f"docker events error: {exc!r}", flush=True)
            time.sleep(5)

    # --- Periodic checks -----------------------------------------------------

    def check_host(self) -> None:
        usage = shutil.disk_usage("/")
        disk = 100 * usage.used / usage.total
        self.report(
            self.disk,
            disk >= self.disk_limit,
            "disk",
            f"Disk {disk:.0f}% full",
            f"Disk back to {disk:.0f}%",
        )

        with open("/proc/meminfo") as fh:
            mem = memory_used_percent(fh.read())
        self.report(
            self.memory,
            mem >= self.mem_limit,
            "memory",
            f"Memory {mem:.0f}% used",
            f"Memory back to {mem:.0f}%",
        )

        cpus = os.cpu_count() or 1
        load5 = os.getloadavg()[1]
        self.report(
            self.load,
            load5 / cpus >= self.load_limit,
            "load",
            f"CPU overloaded: load {load5:.1f} on {cpus} vCPU",
            f"CPU load back to {load5:.1f}",
        )

    def check_containers(self) -> None:
        for name, condition in self.down.items():
            status, raw = docker_get(f"/containers/{name}/json")
            state = json.loads(raw).get("State", {}) if status == 200 else {}
            running = bool(state.get("Running")) and not state.get("Restarting")
            what = state.get("Status") or "missing"
            if state.get("ExitCode"):
                what += f", exit {state['ExitCode']}"
            self.report(
                condition,
                not running,
                f"down:{name}",
                f"Container {name} is not running ({what})",
                f"Container {name} is running again",
            )

    def report(self, condition: Condition, bad: bool, key: str, fire: str, resolve: str) -> None:
        change = condition.update(bad)
        if change == "fire":
            self.send("error", fire, "", f"{self.host}:{key}")
        elif change == "resolve":
            self.send("resolved", resolve, "", f"{self.host}:{key}")

    def announce_start(self) -> None:
        with open("/proc/uptime") as fh:
            uptime_min = float(fh.read().split()[0]) / 60
        watching = ", ".join(self.watch) or "no containers"
        if uptime_min < 10:
            self.send(
                "warning", f"Server restarted (up {uptime_min:.0f} min)", f"Watching: {watching}"
            )
        else:
            self.send("info", "Watchdog started", f"Watching: {watching}")

    def run(self) -> None:
        self.announce_start()
        threading.Thread(target=self.follow_events, name="docker-events", daemon=True).start()
        while True:
            for check in (self.check_host, self.check_containers):
                try:
                    check()
                except Exception as exc:
                    print(f"{check.__name__} failed: {exc!r}", flush=True)
            time.sleep(self.check_seconds)


if __name__ == "__main__":
    Watchdog(dict(os.environ)).run()
