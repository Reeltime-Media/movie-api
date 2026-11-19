"""The migration history must stay a single line.

Two migrations that share a revision id or the same parent make `alembic upgrade head`
fail, and the API container then refuses to start (production outage on 2026-11-19, and a
number clash on 0063 before that). CI should catch it before a deploy does.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_ROOT = Path(__file__).resolve().parents[1]


def _script() -> ScriptDirectory:
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_there_is_exactly_one_migration_head():
    heads = _script().get_heads()
    assert len(heads) == 1, f"multiple alembic heads: {heads}"


def test_every_revision_id_is_used_by_one_file_only():
    seen: dict[str, str] = {}
    for path in sorted((_ROOT / "alembic" / "versions").glob("*.py")):
        for line in path.read_text().splitlines():
            if line.startswith("revision"):
                revision = line.split("=", 1)[1].strip().strip("\"'")
                assert revision not in seen, f"{revision} is in {seen[revision]} and {path.name}"
                seen[revision] = path.name
                break
