"""Unit tests for app.db_connect module.

Tests cover:
- URL parsing and validation
- Error classification (transient vs permanent)
- Retry logic with exponential backoff
- Connection argument generation
- SSL/TLS configuration
"""

import asyncio
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import certifi
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError

from app.db_connect import (
    DatabaseWarmup,
    asyncpg_connect_args,
    database_connection_label,
    exception_from_db_layer,
    is_transient_db_error,
    run_with_db_retry,
    sqlalchemy_engine_kwargs,
    validate_database_url,
)


class TestURLParsing:
    """Test URL parsing and validation."""

    def test_database_connection_label_with_port(self):
        """Should format connection label with host and port."""
        url = "postgresql+asyncpg://user:pass@db.supabase.co:5432/db"
        label = database_connection_label(url)
        assert label == "db.supabase.co:5432"

    def test_database_connection_label_without_port(self):
        """Should format connection label with host only when no port."""
        url = "postgresql+asyncpg://user:pass@localhost/db"
        label = database_connection_label(url)
        assert label == "localhost"

    def test_database_connection_label_localhost(self):
        """Should handle localhost connections."""
        url = "postgresql+asyncpg://user:pass@127.0.0.1:5432/db"
        label = database_connection_label(url)
        assert label == "127.0.0.1:5432"


class TestValidation:
    """Test database URL validation and warnings."""

    def test_validate_warns_on_transaction_pooler_port(self):
        """Should warn when using port 6543 (transaction pooler)."""
        url = "postgresql+asyncpg://user:pass@db.supabase.co:6543/db"
        warnings = validate_database_url(url, pooler_configured=True)
        assert any("6543" in w for w in warnings)

    def test_validate_warns_on_direct_supabase_host_without_pooler(self):
        """Should warn when using direct Supabase host without pooler URL."""
        url = "postgresql+asyncpg://user:pass@db.project.supabase.co:5432/db"
        warnings = validate_database_url(url, pooler_configured=False)
        assert any("POOLER_DATABASE_URL" in w for w in warnings)

    def test_validate_no_warnings_on_pooler_url(self):
        """Should not warn when using pooler URL correctly."""
        url = "postgresql+asyncpg://user:pass@pooler.project.supabase.co:5432/db"
        warnings = validate_database_url(url, pooler_configured=True)
        assert len(warnings) == 0


class TestErrorClassification:
    """Test transient vs permanent error detection."""

    def test_timeout_error_is_transient(self):
        """TimeoutError should be classified as transient."""
        exc = TimeoutError("Connection timed out")
        assert is_transient_db_error(exc) is True

    def test_connection_error_is_transient(self):
        """ConnectionError should be classified as transient."""
        exc = ConnectionError("Connection reset")
        assert is_transient_db_error(exc) is True

    def test_os_error_is_transient(self):
        """OSError should be classified as transient."""
        exc = OSError("Connection refused")
        assert is_transient_db_error(exc) is True

    def test_operational_error_with_timeout_keyword_is_transient(self):
        """OperationalError containing 'timeout' should be transient."""
        exc = OperationalError("Connection timeout", None, None)
        assert is_transient_db_error(exc) is True

    def test_operational_error_with_connection_keyword_is_transient(self):
        """OperationalError containing 'connection' should be transient."""
        exc = OperationalError("Connection closed by server", None, None)
        assert is_transient_db_error(exc) is True

    def test_exception_with_transient_cause_is_transient(self):
        """Exception with transient __cause__ should be transient."""
        cause = TimeoutError("timed out")
        exc = RuntimeError("Wrapped error")
        exc.__cause__ = cause
        assert is_transient_db_error(exc) is True

    def test_sqlalchemy_pool_timeout_is_transient(self):
        """Pool-checkout TimeoutError (sqlalchemy.exc) should be transient."""
        exc = SATimeoutError("QueuePool limit of size 3 overflow 2 reached")
        assert is_transient_db_error(exc) is True


class TestRetryLogic:
    """Test automatic retry behavior."""

    @pytest.mark.asyncio
    async def test_operation_succeeds_on_first_attempt(self):
        """Should return immediately if operation succeeds."""
        mock_op = AsyncMock(return_value="success")
        result = await run_with_db_retry(mock_op, attempts=3)
        assert result == "success"
        assert mock_op.call_count == 1

    @pytest.mark.asyncio
    async def test_operation_retries_on_transient_error(self):
        """Should retry on transient errors."""
        mock_op = AsyncMock(
            side_effect=[
                TimeoutError("timeout"),
                TimeoutError("timeout"),
                "success",
            ]
        )
        result = await run_with_db_retry(mock_op, attempts=3, base_delay_seconds=0.01)
        assert result == "success"
        assert mock_op.call_count == 3

    @pytest.mark.asyncio
    async def test_operation_fails_on_permanent_error(self):
        """Should not retry on permanent errors (e.g., ValueError)."""
        mock_op = AsyncMock(side_effect=ValueError("Bad value"))
        with pytest.raises(ValueError):
            await run_with_db_retry(mock_op, attempts=3)
        assert mock_op.call_count == 1

    @pytest.mark.asyncio
    async def test_operation_fails_after_max_attempts(self):
        """Should fail after exhausting retry attempts."""
        mock_op = AsyncMock(side_effect=TimeoutError("always timeout"))
        with pytest.raises(TimeoutError):
            await run_with_db_retry(mock_op, attempts=2, base_delay_seconds=0.01)
        assert mock_op.call_count == 2

    @pytest.mark.asyncio
    async def test_exponential_backoff_with_jitter(self):
        """Should use exponential backoff with jitter."""
        mock_op = AsyncMock(side_effect=TimeoutError("timeout"))
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            try:
                await run_with_db_retry(
                    mock_op,
                    attempts=3,
                    base_delay_seconds=1.0,
                )
            except TimeoutError:
                pass

            # Should have called sleep twice (for 2nd and 3rd attempts)
            assert mock_sleep.call_count == 2
            # Sleep durations should increase (exponential backoff)
            delays = [call[0][0] for call in mock_sleep.call_args_list]
            assert delays[1] >= delays[0]


class TestConnectionArguments:
    """Test asyncpg and SQLAlchemy configuration."""

    def test_asyncpg_args_disables_prepared_statements(self):
        """Should disable prepared statement caches for PgBouncer."""
        url = "postgresql+asyncpg://user:pass@localhost/db"
        args = asyncpg_connect_args(url)
        assert args["statement_cache_size"] == 0
        assert args["prepared_statement_cache_size"] == 0

    def test_asyncpg_args_sets_timeouts(self):
        """Should set connection and command timeouts."""
        url = "postgresql+asyncpg://user:pass@localhost/db"
        args = asyncpg_connect_args(url)
        assert args["timeout"] > 0
        assert args["command_timeout"] > 0

    def test_asyncpg_args_disables_ssl_for_localhost(self):
        """Should not enable SSL for localhost connections."""
        url = "postgresql+asyncpg://user:pass@localhost/db"
        args = asyncpg_connect_args(url)
        assert "ssl" not in args

    def test_asyncpg_args_enables_ssl_for_remote_host(self):
        """Should enable SSL for remote hosts."""
        url = "postgresql+asyncpg://user:pass@db.supabase.co/db"
        args = asyncpg_connect_args(url)
        assert "ssl" in args
        assert isinstance(args["ssl"], ssl.SSLContext)

    def test_asyncpg_args_ssl_context_disables_verification(self):
        """SSL context should not verify hostname for pooler cert issues."""
        url = "postgresql+asyncpg://user:pass@db.supabase.co/db"
        args = asyncpg_connect_args(url)
        ssl_ctx = args["ssl"]
        assert ssl_ctx.check_hostname is False
        assert ssl_ctx.verify_mode == ssl.CERT_NONE

    def test_sqlalchemy_engine_kwargs_has_correct_pool_size(self):
        """Should configure pool size for Supabase limits."""
        url = "postgresql+asyncpg://user:pass@localhost/db"
        kwargs = sqlalchemy_engine_kwargs(url)
        assert kwargs["pool_size"] == 3
        assert kwargs["max_overflow"] == 2

    def test_sqlalchemy_engine_kwargs_includes_connect_args(self):
        """Should include asyncpg connect args."""
        url = "postgresql+asyncpg://user:pass@localhost/db"
        kwargs = sqlalchemy_engine_kwargs(url)
        assert "connect_args" in kwargs
        assert isinstance(kwargs["connect_args"], dict)

    def test_sqlalchemy_engine_kwargs_pre_ping_enabled(self):
        """Should enable pool pre-ping to validate connections."""
        url = "postgresql+asyncpg://user:pass@localhost/db"
        kwargs = sqlalchemy_engine_kwargs(url)
        assert kwargs["pool_pre_ping"] is True

    def test_sqlalchemy_engine_kwargs_respects_debug_flag(self):
        """Should enable SQL echo when debug=True."""
        url = "postgresql+asyncpg://user:pass@localhost/db"
        kwargs_debug = sqlalchemy_engine_kwargs(url, debug=True)
        kwargs_normal = sqlalchemy_engine_kwargs(url, debug=False)
        assert kwargs_debug["echo"] is True
        assert kwargs_normal["echo"] is False

    def test_asyncpg_args_with_root_cert_enables_verification(self):
        """Providing a CA bundle should turn certificate verification back on."""
        url = "postgresql+asyncpg://user:pass@db.supabase.co/db"
        args = asyncpg_connect_args(url, ssl_root_cert=certifi.where())
        ssl_ctx = args["ssl"]
        assert ssl_ctx.verify_mode == ssl.CERT_REQUIRED
        assert ssl_ctx.check_hostname is True

    def test_sqlalchemy_engine_kwargs_passes_root_cert_through(self):
        """Engine kwargs should honour ssl_root_cert for remote hosts."""
        url = "postgresql+asyncpg://user:pass@db.supabase.co/db"
        kwargs = sqlalchemy_engine_kwargs(url, ssl_root_cert=certifi.where())
        assert kwargs["connect_args"]["ssl"].verify_mode == ssl.CERT_REQUIRED


def _raise_timeout_in_module(module_name: str) -> TimeoutError:
    """Raise and capture a TimeoutError whose traceback claims the given module."""
    namespace = {"__name__": module_name}
    exec("def boom():\n    raise TimeoutError('timed out')", namespace)
    try:
        namespace["boom"]()
    except TimeoutError as exc:
        return exc
    raise AssertionError("unreachable")


class TestDbLayerClassification:
    """Test attribution of timeouts to the database stack via traceback frames."""

    def test_timeout_from_sqlalchemy_frame_is_db_layer(self):
        exc = _raise_timeout_in_module("sqlalchemy.pool.base")
        assert exception_from_db_layer(exc) is True

    def test_timeout_from_asyncpg_frame_is_db_layer(self):
        exc = _raise_timeout_in_module("asyncpg.connection")
        assert exception_from_db_layer(exc) is True

    def test_timeout_from_app_code_is_not_db_layer(self):
        exc = _raise_timeout_in_module("app.services.transcode_client")
        assert exception_from_db_layer(exc) is False

    def test_timeout_with_db_layer_cause_is_db_layer(self):
        exc = TimeoutError("wrapper")
        exc.__cause__ = _raise_timeout_in_module("asyncpg.protocol")
        assert exception_from_db_layer(exc) is True


class TestDatabaseWarmup:
    """Test the single-flight reconnect gate used by the warmup middleware."""

    @pytest.mark.asyncio
    async def test_returns_true_when_ping_succeeds(self):
        ping = AsyncMock()
        warmup = DatabaseWarmup(ping, cooldown_seconds=60, timeout_seconds=1)
        assert await warmup.try_connect() is True
        ping.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failure_applies_cooldown(self):
        """A failed probe should suppress further probes for the cooldown window."""
        ping = AsyncMock(side_effect=ConnectionError("db down"))
        warmup = DatabaseWarmup(ping, cooldown_seconds=60, timeout_seconds=1)
        assert await warmup.try_connect() is False
        assert await warmup.try_connect() is False
        ping.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retries_after_cooldown_expires(self):
        ping = AsyncMock(side_effect=ConnectionError("db down"))
        warmup = DatabaseWarmup(ping, cooldown_seconds=0.0, timeout_seconds=1)
        assert await warmup.try_connect() is False
        assert await warmup.try_connect() is False
        assert ping.await_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_callers_share_one_probe(self):
        """Requests arriving while a probe is in flight must not start their own."""
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def ping():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()

        warmup = DatabaseWarmup(ping, cooldown_seconds=60, timeout_seconds=5)
        first = asyncio.create_task(warmup.try_connect())
        await started.wait()
        assert await warmup.try_connect() is False
        release.set()
        assert await first is True
        assert calls == 1

    @pytest.mark.asyncio
    async def test_hung_ping_times_out(self):
        """A probe must be bounded by timeout_seconds, not the 30s connect timeout."""

        async def ping():
            await asyncio.sleep(30)

        warmup = DatabaseWarmup(ping, cooldown_seconds=60, timeout_seconds=0.05)
        assert await asyncio.wait_for(warmup.try_connect(), timeout=1) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
