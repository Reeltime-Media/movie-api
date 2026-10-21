"""VM watchdog (ops/watchdog): crash detection, log handling, alert states."""

import json

import pytest

from ops.watchdog import watchdog
from ops.watchdog.watchdog import (
    Condition,
    Watchdog,
    demux_logs,
    is_crash,
    memory_used_percent,
    redact,
)


def _frame(stream: int, text: str) -> bytes:
    data = text.encode()
    return bytes([stream, 0, 0, 0]) + len(data).to_bytes(4, "big") + data


def test_demux_joins_stdout_and_stderr_frames() -> None:
    raw = _frame(1, "started\n") + _frame(2, "Traceback: boom\n")

    assert demux_logs(raw) == "started\nTraceback: boom\n"


def test_demux_passes_tty_logs_through() -> None:
    assert demux_logs(b"plain tty output\n") == "plain tty output\n"


def test_redact_strips_query_strings_and_bearer_tokens() -> None:
    line = "GET /playback/1/master.m3u8?t=eyJhbGciOi.secret HTTP/1.1 Authorization: Bearer abc.def"

    assert redact(line) == "GET /playback/1/master.m3u8?… HTTP/1.1 Authorization: Bearer …"


def test_condition_fires_after_streak_and_resolves_once() -> None:
    condition = Condition(needed=2)

    assert condition.update(True) is None
    assert condition.update(True) == "fire"
    assert condition.update(True) is None
    assert condition.update(False) == "resolve"
    assert condition.update(False) is None


@pytest.mark.parametrize(
    ("exit_code", "stopped_at", "expected"),
    [(0, None, False), (1, None, True), (137, 95.0, False), (1, 10.0, True)],
)
def test_is_crash(exit_code: int, stopped_at: float | None, expected: bool) -> None:
    assert is_crash(exit_code, 100.0, stopped_at) is expected


def test_memory_used_percent() -> None:
    meminfo = "MemTotal:  4000000 kB\nMemFree:  100 kB\nMemAvailable:  1000000 kB\n"

    assert memory_used_percent(meminfo) == pytest.approx(75.0)


@pytest.fixture
def dog(monkeypatch: pytest.MonkeyPatch) -> tuple[Watchdog, list[tuple]]:
    inspect = {
        "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
        "State": {"Health": {"Log": [{"Output": "curl: (7) connection refused"}]}},
    }

    def fake_docker_get(path: str, timeout: float = 10) -> tuple[int, bytes]:
        if path.endswith("/json"):
            return 200, json.dumps(inspect).encode()
        return 200, _frame(2, "ValueError: boom\n")

    monkeypatch.setattr(watchdog, "docker_get", fake_docker_get)
    sent: list[tuple] = []
    dog = Watchdog({"RELAY_URL": "https://relay.test", "RELAY_TOKEN": "t", "HOST_LABEL": "vm"})
    monkeypatch.setattr(dog, "send", lambda *args: sent.append(args))
    return dog, sent


def _event(action: str, **attrs: str) -> dict:
    return {"Action": action, "Actor": {"ID": "c1", "Attributes": {"name": "api", **attrs}}}


def test_stop_during_a_deploy_is_not_a_crash(dog) -> None:
    watchdog_, sent = dog

    watchdog_.handle_event(_event("kill", signal="15"))
    watchdog_.handle_event(_event("die", exitCode="143"))

    assert sent == []


def test_crash_alert_has_restart_note_and_last_logs(dog) -> None:
    watchdog_, sent = dog

    watchdog_.handle_event(_event("die", exitCode="1"))

    level, title, detail, fingerprint = sent[0]
    assert (level, title, fingerprint) == (
        "error",
        "Container api crashed (exit 1)",
        "vm:crash:api",
    )
    assert "Docker will restart it (restart policy: unless-stopped)." in detail
    assert "ValueError: boom" in detail


def test_out_of_memory_kill_is_named(dog) -> None:
    watchdog_, sent = dog

    watchdog_.handle_event(_event("oom"))
    watchdog_.handle_event(_event("die", exitCode="137"))

    assert [s[1] for s in sent] == ["Container api was killed: out of memory"]


def test_health_changes_are_reported_once_each(dog) -> None:
    watchdog_, sent = dog

    watchdog_.handle_event(_event("health_status: unhealthy"))
    watchdog_.handle_event(_event("health_status: unhealthy"))
    watchdog_.handle_event(_event("health_status: healthy"))

    assert [(s[0], s[1]) for s in sent] == [
        ("warning", "Container api is unhealthy"),
        ("resolved", "Container api is healthy again"),
    ]
    assert sent[0][2] == "curl: (7) connection refused"
