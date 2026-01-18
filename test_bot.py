"""
Unit tests for Clod Twitter Bot
Comprehensive test suite covering all functionality
"""

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import anthropic
import tweepy

from bot import (
    BotMetrics,
    CircuitBreaker,
    ClodBot,
    retry_on_error,
    truncate_smart,
    validate_tweet_text,
)
from config import MAX_RESPONSE_LENGTH


class TestTruncateSmart(unittest.TestCase):
    """Tests for the truncate_smart function."""

    def test_short_text_unchanged(self) -> None:
        """Text under limit should not be modified."""
        text = "Hello world!"
        result = truncate_smart(text)
        self.assertEqual(result, text)

    def test_exact_limit_unchanged(self) -> None:
        """Text exactly at limit should not be modified."""
        text = "a" * MAX_RESPONSE_LENGTH
        result = truncate_smart(text)
        self.assertEqual(result, text)

    def test_long_text_truncated(self) -> None:
        """Text over limit should be truncated with ellipsis."""
        text = "a" * 300
        result = truncate_smart(text)
        self.assertTrue(len(result) <= MAX_RESPONSE_LENGTH)
        self.assertTrue(result.endswith("..."))

    def test_preserves_whole_words(self) -> None:
        """Truncation should not cut words in half."""
        text = "This is a test " + "word " * 60
        result = truncate_smart(text)
        self.assertTrue(len(result) <= MAX_RESPONSE_LENGTH)
        without_ellipsis = result[:-3]
        self.assertTrue(
            without_ellipsis.endswith(" ") or
            without_ellipsis[-1].isalpha()
        )

    def test_strips_trailing_punctuation(self) -> None:
        """Trailing punctuation before ellipsis should be stripped."""
        text = "Hello, world! " + "x" * 300
        result = truncate_smart(text, 20)
        self.assertFalse(result.endswith("!..."))
        self.assertFalse(result.endswith(",,..."))

    def test_custom_max_length(self) -> None:
        """Should respect custom max_length parameter."""
        text = "Hello world this is a test"
        result = truncate_smart(text, max_length=15)
        self.assertTrue(len(result) <= 15)
        self.assertTrue(result.endswith("..."))

    def test_empty_string(self) -> None:
        """Empty string should return empty string."""
        result = truncate_smart("")
        self.assertEqual(result, "")

    def test_none_like_empty(self) -> None:
        """None-like values should be handled."""
        result = truncate_smart("")
        self.assertEqual(result, "")

    def test_whitespace_only(self) -> None:
        """Whitespace-only text should be stripped."""
        result = truncate_smart("   ")
        self.assertEqual(result, "")

    def test_strips_leading_trailing_whitespace(self) -> None:
        """Leading/trailing whitespace should be stripped."""
        result = truncate_smart("  hello world  ")
        self.assertEqual(result, "hello world")


class TestValidateTweetText(unittest.TestCase):
    """Tests for tweet text validation."""

    def test_valid_text(self) -> None:
        """Valid text should pass validation."""
        is_valid, error = validate_tweet_text("Hello world!")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_empty_text(self) -> None:
        """Empty text should fail validation."""
        is_valid, error = validate_tweet_text("")
        self.assertFalse(is_valid)
        self.assertIn("empty", error.lower())

    def test_whitespace_only(self) -> None:
        """Whitespace-only text should fail validation."""
        is_valid, error = validate_tweet_text("   ")
        self.assertFalse(is_valid)
        self.assertIn("whitespace", error.lower())

    def test_too_long(self) -> None:
        """Text exceeding limit should fail validation."""
        is_valid, error = validate_tweet_text("a" * 300)
        self.assertFalse(is_valid)
        self.assertIn("exceeds", error.lower())

    def test_exact_limit(self) -> None:
        """Text at exact limit should pass."""
        is_valid, error = validate_tweet_text("a" * MAX_RESPONSE_LENGTH)
        self.assertTrue(is_valid)


class TestBotMetrics(unittest.TestCase):
    """Tests for the BotMetrics class."""

    def test_initial_values(self) -> None:
        """Metrics should start at zero."""
        metrics = BotMetrics()
        self.assertEqual(metrics.mentions_processed, 0)
        self.assertEqual(metrics.replies_sent, 0)
        self.assertEqual(metrics.errors_count, 0)
        self.assertEqual(metrics.consecutive_failures, 0)

    def test_record_success(self) -> None:
        """Success should reset consecutive failures."""
        metrics = BotMetrics()
        metrics.consecutive_failures = 5
        metrics.record_success()
        self.assertEqual(metrics.consecutive_failures, 0)
        self.assertIsNotNone(metrics.last_activity)

    def test_record_failure(self) -> None:
        """Failure should increment counters."""
        metrics = BotMetrics()
        metrics.record_failure()
        self.assertEqual(metrics.errors_count, 1)
        self.assertEqual(metrics.consecutive_failures, 1)
        metrics.record_failure()
        self.assertEqual(metrics.errors_count, 2)
        self.assertEqual(metrics.consecutive_failures, 2)

    def test_record_rate_limit(self) -> None:
        """Rate limit should be tracked."""
        metrics = BotMetrics()
        metrics.record_rate_limit()
        self.assertEqual(metrics.rate_limits_hit, 1)

    def test_record_retry(self) -> None:
        """Retry should be tracked."""
        metrics = BotMetrics()
        metrics.record_retry()
        self.assertEqual(metrics.retries_count, 1)

    def test_uptime_calculation(self) -> None:
        """Uptime should be calculated correctly."""
        metrics = BotMetrics()
        uptime = metrics.get_uptime_seconds()
        self.assertGreaterEqual(uptime, 0)

    def test_health_status_healthy(self) -> None:
        """Health status should report healthy when few failures."""
        metrics = BotMetrics()
        status = metrics.get_health_status()
        self.assertTrue(status["healthy"])

    def test_health_status_unhealthy(self) -> None:
        """Health status should report unhealthy after many failures."""
        metrics = BotMetrics()
        metrics.consecutive_failures = 10
        status = metrics.get_health_status()
        self.assertFalse(status["healthy"])


class TestCircuitBreaker(unittest.TestCase):
    """Tests for the CircuitBreaker class."""

    def test_initial_state_closed(self) -> None:
        """Circuit should start closed."""
        cb = CircuitBreaker()
        self.assertEqual(cb.state, "closed")
        self.assertTrue(cb.can_execute())

    def test_opens_after_threshold(self) -> None:
        """Circuit should open after failure threshold."""
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, "closed")
        cb.record_failure()
        self.assertEqual(cb.state, "open")

    def test_open_blocks_execution(self) -> None:
        """Open circuit should block execution."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        cb.record_failure()
        self.assertFalse(cb.can_execute())

    def test_success_resets_circuit(self) -> None:
        """Success should close the circuit."""
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        self.assertEqual(cb.state, "open")
        cb.record_success()
        self.assertEqual(cb.state, "closed")
        self.assertEqual(cb.failures, 0)

    def test_half_open_after_timeout(self) -> None:
        """Circuit should go half-open after recovery timeout."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        self.assertEqual(cb.state, "open")
        # After timeout, should allow execution
        self.assertTrue(cb.can_execute())
        self.assertEqual(cb.state, "half-open")


class TestClodBotState(unittest.TestCase):
    """Tests for state persistence."""

    def setUp(self) -> None:
        """Create a temporary directory for state files."""
        self.temp_dir = tempfile.mkdtemp()
        self.state_file = os.path.join(self.temp_dir, "test_state.json")

    def tearDown(self) -> None:
        """Clean up temporary files."""
        if os.path.exists(self.state_file):
            os.remove(self.state_file)
        os.rmdir(self.temp_dir)

    def test_load_state_empty(self) -> None:
        """Loading non-existent state should return empty dict."""
        bot = ClodBot()
        with patch('bot.STATE_FILE', self.state_file):
            state = bot.load_state()
        self.assertEqual(state, {})

    def test_save_and_load_state(self) -> None:
        """State should persist across save/load cycle."""
        bot = ClodBot()
        bot.state = {"last_mention_id": "12345"}

        with patch('bot.STATE_FILE', self.state_file):
            result = bot.save_state()
            self.assertTrue(result)

            bot2 = ClodBot()
            loaded = bot2.load_state()

        self.assertEqual(loaded, {"last_mention_id": "12345"})

    def test_load_corrupted_state(self) -> None:
        """Corrupted state file should return empty dict."""
        with open(self.state_file, 'w') as f:
            f.write("not valid json {{{")

        bot = ClodBot()
        with patch('bot.STATE_FILE', self.state_file):
            state = bot.load_state()
        self.assertEqual(state, {})

    def test_load_invalid_type_state(self) -> None:
        """State file with non-dict should return empty dict."""
        with open(self.state_file, 'w') as f:
            json.dump(["list", "not", "dict"], f)

        bot = ClodBot()
        with patch('bot.STATE_FILE', self.state_file):
            state = bot.load_state()
        self.assertEqual(state, {})


class TestClodBotAPIKeys(unittest.TestCase):
    """Tests for API key validation."""

    def test_missing_keys_exits(self) -> None:
        """Missing API keys should cause sys.exit."""
        bot = ClodBot()

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                bot.check_api_keys()

    def test_all_keys_present(self) -> None:
        """All keys present should not raise."""
        bot = ClodBot()

        env = {
            'TWITTER_API_KEY': 'test',
            'TWITTER_API_SECRET': 'test',
            'TWITTER_ACCESS_TOKEN': 'test',
            'TWITTER_ACCESS_SECRET': 'test',
            'ANTHROPIC_API_KEY': 'test'
        }

        with patch.dict(os.environ, env, clear=True):
            bot.check_api_keys()

    def test_partial_keys_exits(self) -> None:
        """Partial keys should cause sys.exit."""
        bot = ClodBot()

        env = {
            'TWITTER_API_KEY': 'test',
            'TWITTER_API_SECRET': 'test',
        }

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit):
                bot.check_api_keys()


class TestClodBotSignalHandler(unittest.TestCase):
    """Tests for graceful shutdown."""

    def test_signal_handler_sets_running_false(self) -> None:
        """Signal handler should set running to False."""
        bot = ClodBot()
        self.assertTrue(bot.running)

        bot.signal_handler(2, None)

        self.assertFalse(bot.running)


class TestClodBotMentionProcessing(unittest.TestCase):
    """Tests for mention processing logic."""

    def setUp(self) -> None:
        """Create a bot with mocked clients."""
        self.bot = ClodBot()
        self.bot.twitter_client = MagicMock()
        self.bot.claude_client = MagicMock()
        self.bot.my_user_id = "123"
        self.bot.state = {}

    def test_fetch_mentions_empty(self) -> None:
        """No mentions should return empty list."""
        self.bot.twitter_client.get_users_mentions.return_value = MagicMock(data=None)

        result = self.bot.fetch_mentions()

        self.assertEqual(result, [])

    def test_fetch_mentions_returns_reversed(self) -> None:
        """Mentions should be returned in chronological order."""
        mock_mentions = [MagicMock(id=1), MagicMock(id=2), MagicMock(id=3)]
        self.bot.twitter_client.get_users_mentions.return_value = MagicMock(data=mock_mentions)

        result = self.bot.fetch_mentions()

        self.assertEqual([m.id for m in result], [3, 2, 1])

    def test_process_mention_success(self) -> None:
        """Successful mention processing should return True."""
        mention = MagicMock(id="456", author_id="789", text="Hello @AI_clod")

        self.bot.twitter_client.get_user.return_value = MagicMock(
            data=MagicMock(username="testuser")
        )

        self.bot.claude_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Hello there!")]
        )

        self.bot.twitter_client.create_tweet.return_value = MagicMock()

        result = self.bot.process_mention(mention)

        self.assertTrue(result)
        self.bot.twitter_client.create_tweet.assert_called_once()

    def test_process_mention_no_response(self) -> None:
        """Failed response generation should return False."""
        mention = MagicMock(id="456", author_id="789", text="Hello @AI_clod")

        self.bot.twitter_client.get_user.return_value = MagicMock(
            data=MagicMock(username="testuser")
        )

        self.bot.claude_client.messages.create.side_effect = anthropic.APIError(
            message="API Error",
            request=MagicMock(),
            body=None
        )

        result = self.bot.process_mention(mention)

        self.assertFalse(result)

    def test_fetch_mentions_no_client(self) -> None:
        """No client should return empty list."""
        self.bot.twitter_client = None
        result = self.bot.fetch_mentions()
        self.assertEqual(result, [])

    def test_fetch_mentions_no_user_id(self) -> None:
        """No user ID should return empty list."""
        self.bot.my_user_id = None
        result = self.bot.fetch_mentions()
        self.assertEqual(result, [])


class TestClodBotClaudeResponse(unittest.TestCase):
    """Tests for Claude response generation."""

    def setUp(self) -> None:
        """Create a bot with mocked Claude client."""
        self.bot = ClodBot()
        self.bot.claude_client = MagicMock()

    def test_empty_tweet_text(self) -> None:
        """Empty tweet text should return None."""
        result = self.bot.get_claude_response("", "user")
        self.assertIsNone(result)

    def test_whitespace_tweet_text(self) -> None:
        """Whitespace-only tweet text should return None."""
        result = self.bot.get_claude_response("   ", "user")
        self.assertIsNone(result)

    def test_no_client(self) -> None:
        """No Claude client should return None."""
        self.bot.claude_client = None
        result = self.bot.get_claude_response("Hello", "user")
        self.assertIsNone(result)

    def test_successful_response(self) -> None:
        """Successful response should be returned and truncated."""
        self.bot.claude_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="This is a response")]
        )

        result = self.bot.get_claude_response("Hello", "testuser")

        self.assertEqual(result, "This is a response")

    def test_long_response_truncated(self) -> None:
        """Long response should be truncated."""
        long_text = "a" * 500
        self.bot.claude_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=long_text)]
        )

        result = self.bot.get_claude_response("Hello", "testuser")

        self.assertIsNotNone(result)
        self.assertTrue(len(result) <= MAX_RESPONSE_LENGTH)


class TestClodBotPostReply(unittest.TestCase):
    """Tests for posting replies."""

    def setUp(self) -> None:
        """Create a bot with mocked Twitter client."""
        self.bot = ClodBot()
        self.bot.twitter_client = MagicMock()

    def test_no_client(self) -> None:
        """No client should return False."""
        self.bot.twitter_client = None
        result = self.bot.post_reply("Hello", "123")
        self.assertFalse(result)

    def test_empty_text(self) -> None:
        """Empty text should return False."""
        result = self.bot.post_reply("", "123")
        self.assertFalse(result)

    def test_too_long_text(self) -> None:
        """Too long text should return False."""
        result = self.bot.post_reply("a" * 300, "123")
        self.assertFalse(result)

    def test_successful_post(self) -> None:
        """Successful post should return True and update metrics."""
        self.bot.twitter_client.create_tweet.return_value = MagicMock()

        result = self.bot.post_reply("Hello!", "123")

        self.assertTrue(result)
        self.assertEqual(self.bot.metrics.replies_sent, 1)


class TestClodBotHealth(unittest.TestCase):
    """Tests for health check functionality."""

    def test_get_health(self) -> None:
        """Health check should return complete status."""
        bot = ClodBot()
        health = bot.get_health()

        self.assertIn("healthy", health)
        self.assertIn("running", health)
        self.assertIn("circuit_breaker_state", health)
        self.assertIn("uptime_seconds", health)
        self.assertIn("mentions_processed", health)
        self.assertIn("replies_sent", health)

    def test_health_reflects_running_state(self) -> None:
        """Health should reflect running state."""
        bot = ClodBot()
        self.assertTrue(bot.get_health()["running"])

        bot.running = False
        self.assertFalse(bot.get_health()["running"])


class TestRetryDecorator(unittest.TestCase):
    """Tests for the retry decorator."""

    def test_successful_call_no_retry(self) -> None:
        """Successful call should not retry."""
        call_count = 0

        @retry_on_error(max_retries=3, delay=0)
        def successful_func() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()

        self.assertEqual(result, "success")
        self.assertEqual(call_count, 1)

    def test_retry_on_tweepy_error(self) -> None:
        """Should retry on TweepyException."""
        call_count = 0

        @retry_on_error(max_retries=3, delay=0)
        def failing_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise tweepy.TweepyException("Error")
            return "success"

        result = failing_func()

        self.assertEqual(result, "success")
        self.assertEqual(call_count, 3)

    def test_returns_none_after_max_retries(self) -> None:
        """Should return None after all retries exhausted."""
        @retry_on_error(max_retries=2, delay=0)
        def always_fails() -> str:
            raise tweepy.TweepyException("Error")

        result = always_fails()

        self.assertIsNone(result)

    def test_metrics_tracked_on_retry(self) -> None:
        """Metrics should be updated on retry."""
        metrics = BotMetrics()

        @retry_on_error(max_retries=2, delay=0, metrics=metrics)
        def failing_func() -> str:
            raise tweepy.TweepyException("Error")

        failing_func()

        self.assertGreater(metrics.retries_count, 0)

    def test_circuit_breaker_blocks(self) -> None:
        """Circuit breaker should block execution when open."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        cb.record_failure()

        @retry_on_error(max_retries=3, delay=0, circuit_breaker=cb)
        def func() -> str:
            return "success"

        result = func()

        self.assertIsNone(result)

    def test_rate_limit_handling(self) -> None:
        """Should handle rate limit errors specially."""
        metrics = BotMetrics()
        call_count = 0

        @retry_on_error(max_retries=3, delay=0, metrics=metrics)
        def rate_limited_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise tweepy.TooManyRequests(MagicMock())
            return "success"

        with patch('bot.RATE_LIMIT_DELAY', 0):
            result = rate_limited_func()

        self.assertEqual(result, "success")
        self.assertEqual(metrics.rate_limits_hit, 1)


class TestClodBotAuthentication(unittest.TestCase):
    """Tests for Twitter authentication."""

    def test_authenticate_success(self) -> None:
        """Successful auth should set user ID."""
        bot = ClodBot()
        bot.twitter_client = MagicMock()
        bot.twitter_client.get_me.return_value = MagicMock(
            data=MagicMock(id=12345, username="testbot")
        )

        bot.authenticate()

        self.assertEqual(bot.my_user_id, "12345")

    def test_authenticate_no_client(self) -> None:
        """No client should exit."""
        bot = ClodBot()
        bot.twitter_client = None

        with self.assertRaises(SystemExit):
            bot.authenticate()

    def test_authenticate_no_data(self) -> None:
        """No user data should exit."""
        bot = ClodBot()
        bot.twitter_client = MagicMock()
        bot.twitter_client.get_me.return_value = MagicMock(data=None)

        with self.assertRaises(SystemExit):
            bot.authenticate()


class TestClodBotGetUsername(unittest.TestCase):
    """Tests for username lookup."""

    def setUp(self) -> None:
        """Create a bot with mocked Twitter client."""
        self.bot = ClodBot()
        self.bot.twitter_client = MagicMock()

    def test_successful_lookup(self) -> None:
        """Successful lookup should return username."""
        self.bot.twitter_client.get_user.return_value = MagicMock(
            data=MagicMock(username="founduser")
        )

        result = self.bot.get_username_by_id("123")

        self.assertEqual(result, "founduser")

    def test_no_client_returns_id(self) -> None:
        """No client should return the ID."""
        self.bot.twitter_client = None

        result = self.bot.get_username_by_id("123")

        self.assertEqual(result, "123")

    def test_lookup_fails_returns_id(self) -> None:
        """Failed lookup should return the ID."""
        self.bot.twitter_client.get_user.return_value = MagicMock(data=None)

        result = self.bot.get_username_by_id("123")

        self.assertEqual(result, "123")


if __name__ == "__main__":
    unittest.main()
