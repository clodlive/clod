"""
Clod - AI Twitter Reply Bot
Monitors mentions and replies using Claude AI
"""

import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from types import FrameType
from typing import Any, Callable, Optional, TypeVar

import anthropic
import tweepy
from dotenv import load_dotenv

from config import (
    CHECK_MENTIONS_INTERVAL,
    CLOD_SYSTEM_PROMPT,
    MAX_RESPONSE_LENGTH,
    MAX_RETRIES,
    RATE_LIMIT_DELAY,
    REPLY_DELAY,
    RETRY_DELAY,
    STATE_FILE,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Type variable for generic return types
T = TypeVar('T')


@dataclass
class BotMetrics:
    """Tracks bot performance metrics."""

    mentions_processed: int = 0
    replies_sent: int = 0
    errors_count: int = 0
    rate_limits_hit: int = 0
    retries_count: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    last_activity: Optional[datetime] = None
    consecutive_failures: int = 0

    def record_success(self) -> None:
        """Record a successful operation."""
        self.last_activity = datetime.now()
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        """Record a failed operation."""
        self.errors_count += 1
        self.consecutive_failures += 1
        self.last_activity = datetime.now()

    def record_rate_limit(self) -> None:
        """Record a rate limit hit."""
        self.rate_limits_hit += 1
        self.last_activity = datetime.now()

    def record_retry(self) -> None:
        """Record a retry attempt."""
        self.retries_count += 1

    def get_uptime_seconds(self) -> float:
        """Get bot uptime in seconds."""
        return (datetime.now() - self.start_time).total_seconds()

    def get_health_status(self) -> dict[str, Any]:
        """Get current health status."""
        return {
            "healthy": self.consecutive_failures < 5,
            "uptime_seconds": self.get_uptime_seconds(),
            "mentions_processed": self.mentions_processed,
            "replies_sent": self.replies_sent,
            "errors_count": self.errors_count,
            "rate_limits_hit": self.rate_limits_hit,
            "retries_count": self.retries_count,
            "consecutive_failures": self.consecutive_failures,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
        }


class CircuitBreaker:
    """Circuit breaker pattern for API calls."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures: int = 0
        self.last_failure_time: Optional[float] = None
        self.state: str = "closed"  # closed, open, half-open

    def record_failure(self) -> None:
        """Record a failure and potentially open the circuit."""
        self.failures += 1
        self.last_failure_time = time.time()

        if self.failures >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failures} failures")

    def record_success(self) -> None:
        """Record a success and reset the circuit."""
        self.failures = 0
        self.state = "closed"

    def can_execute(self) -> bool:
        """Check if the circuit allows execution."""
        if self.state == "closed":
            return True

        if self.state == "open":
            if self.last_failure_time is None:
                return True

            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = "half-open"
                logger.info("Circuit breaker half-open, allowing test request")
                return True
            return False

        # half-open: allow one request
        return True


def retry_on_error(
    max_retries: int = MAX_RETRIES,
    delay: int = RETRY_DELAY,
    metrics: Optional[BotMetrics] = None,
    circuit_breaker: Optional[CircuitBreaker] = None
) -> Callable[[Callable[..., T]], Callable[..., Optional[T]]]:
    """Decorator for retrying failed API calls with circuit breaker support."""

    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Optional[T]:
            if circuit_breaker and not circuit_breaker.can_execute():
                logger.warning(f"Circuit breaker open, skipping {func.__name__}")
                return None

            last_exception: Optional[Exception] = None

            for attempt in range(max_retries):
                try:
                    result = func(*args, **kwargs)
                    if circuit_breaker:
                        circuit_breaker.record_success()
                    return result

                except tweepy.TooManyRequests as e:
                    logger.warning(f"Rate limited, waiting {RATE_LIMIT_DELAY}s...")
                    if metrics:
                        metrics.record_rate_limit()
                        metrics.record_retry()
                    time.sleep(RATE_LIMIT_DELAY)
                    last_exception = e

                except (tweepy.TweepyException, anthropic.APIError) as e:
                    last_exception = e
                    if metrics:
                        metrics.record_retry()

                    if attempt < max_retries - 1:
                        logger.warning(
                            f"Attempt {attempt + 1} failed: {e}. "
                            f"Retrying in {delay}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"All {max_retries} attempts failed: {e}")
                        if circuit_breaker:
                            circuit_breaker.record_failure()

            return None
        return wrapper
    return decorator


def truncate_smart(text: str, max_length: int = MAX_RESPONSE_LENGTH) -> str:
    """
    Truncate text to max_length without cutting words.

    Args:
        text: Text to truncate
        max_length: Maximum length (default: Twitter's 280)

    Returns:
        Truncated text with ellipsis if needed
    """
    if not text:
        return ""

    text = text.strip()

    if len(text) <= max_length:
        return text

    # Reserve space for ellipsis
    truncated = text[:max_length - 3]

    # Find last space to avoid cutting words
    last_space = truncated.rfind(' ')
    if last_space > max_length // 2:  # Only if we don't lose too much
        truncated = truncated[:last_space]

    return truncated.rstrip('.,!? ') + "..."


def validate_tweet_text(text: str) -> tuple[bool, str]:
    """
    Validate tweet text before posting.

    Args:
        text: Tweet text to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not text:
        return False, "Tweet text is empty"

    if not text.strip():
        return False, "Tweet text contains only whitespace"

    if len(text) > MAX_RESPONSE_LENGTH:
        return False, f"Tweet exceeds {MAX_RESPONSE_LENGTH} characters"

    return True, ""


class ClodBot:
    """Twitter bot that replies to mentions using Claude AI."""

    def __init__(self) -> None:
        self.running: bool = True
        self.twitter_client: Optional[tweepy.Client] = None
        self.claude_client: Optional[anthropic.Anthropic] = None
        self.my_user_id: Optional[str] = None
        self.state: dict[str, Any] = {}
        self.metrics: BotMetrics = BotMetrics()
        self.circuit_breaker: CircuitBreaker = CircuitBreaker()

    def check_api_keys(self) -> None:
        """Verify all required API keys are present."""
        required_keys = [
            'TWITTER_API_KEY',
            'TWITTER_API_SECRET',
            'TWITTER_ACCESS_TOKEN',
            'TWITTER_ACCESS_SECRET',
            'ANTHROPIC_API_KEY'
        ]

        missing = [key for key in required_keys if not os.getenv(key)]

        if missing:
            logger.error(f"Missing API keys: {', '.join(missing)}")
            logger.error("Please set them in .env file")
            sys.exit(1)

    def load_state(self) -> dict[str, Any]:
        """Load bot state from file."""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        logger.warning("State file contains invalid data type")
                        return {}
                    return data
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load state: {e}")
        return {}

    def save_state(self) -> bool:
        """
        Save bot state to file.

        Returns:
            True if save was successful, False otherwise
        """
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2)
            return True
        except IOError as e:
            logger.error(f"Could not save state: {e}")
            return False

    def signal_handler(self, signum: int, frame: Optional[FrameType]) -> None:
        """Handle shutdown signals gracefully."""
        logger.info("Shutdown signal received, finishing up...")
        self.running = False

    def initialize_clients(self) -> None:
        """Initialize Twitter and Claude API clients."""
        self.twitter_client = tweepy.Client(
            consumer_key=os.getenv('TWITTER_API_KEY'),
            consumer_secret=os.getenv('TWITTER_API_SECRET'),
            access_token=os.getenv('TWITTER_ACCESS_TOKEN'),
            access_token_secret=os.getenv('TWITTER_ACCESS_SECRET')
        )

        self.claude_client = anthropic.Anthropic(
            api_key=os.getenv('ANTHROPIC_API_KEY')
        )

    def authenticate(self) -> None:
        """Authenticate with Twitter and get user info."""
        try:
            if self.twitter_client is None:
                raise tweepy.TweepyException("Twitter client not initialized")

            my_user = self.twitter_client.get_me()
            if not my_user or not my_user.data:
                raise tweepy.TweepyException("Could not get user data")
            self.my_user_id = str(my_user.data.id)
            logger.info(f"Logged in as @{my_user.data.username}")
        except tweepy.TweepyException as e:
            logger.error(f"Failed to authenticate with Twitter: {e}")
            sys.exit(1)

    def get_claude_response(
        self,
        tweet_text: str,
        author_username: str
    ) -> Optional[str]:
        """
        Get AI-generated response from Claude.

        Args:
            tweet_text: The tweet content
            author_username: Username of the tweet author

        Returns:
            Response text or None on error
        """
        if self.claude_client is None:
            logger.error("Claude client not initialized")
            return None

        if not tweet_text or not tweet_text.strip():
            logger.warning("Empty tweet text received")
            return None

        @retry_on_error(
            metrics=self.metrics,
            circuit_breaker=self.circuit_breaker
        )
        def _call_claude() -> str:
            message = self.claude_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                system=CLOD_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"Tweet from @{author_username}: {tweet_text}"
                }]
            )
            return message.content[0].text

        response = _call_claude()
        if response:
            return truncate_smart(response)
        return None

    def get_username_by_id(self, user_id: str) -> str:
        """Get Twitter username by user ID."""
        if self.twitter_client is None:
            return user_id

        @retry_on_error(
            metrics=self.metrics,
            circuit_breaker=self.circuit_breaker
        )
        def _get_user() -> Optional[str]:
            user = self.twitter_client.get_user(id=user_id)
            if user and user.data:
                return user.data.username
            return None

        result = _get_user()
        return result if result else user_id

    def post_reply(self, text: str, reply_to_id: str) -> bool:
        """
        Post a reply tweet.

        Args:
            text: Reply text
            reply_to_id: ID of tweet to reply to

        Returns:
            True if successful, False otherwise
        """
        if self.twitter_client is None:
            logger.error("Twitter client not initialized")
            return False

        is_valid, error_msg = validate_tweet_text(text)
        if not is_valid:
            logger.error(f"Invalid tweet text: {error_msg}")
            return False

        @retry_on_error(
            metrics=self.metrics,
            circuit_breaker=self.circuit_breaker
        )
        def _post() -> bool:
            self.twitter_client.create_tweet(
                text=text,
                in_reply_to_tweet_id=reply_to_id
            )
            return True

        result = _post()
        if result:
            self.metrics.replies_sent += 1
            self.metrics.record_success()
            return True

        self.metrics.record_failure()
        return False

    def fetch_mentions(self) -> list[Any]:
        """Fetch new mentions since last check."""
        if self.twitter_client is None or self.my_user_id is None:
            return []

        @retry_on_error(
            metrics=self.metrics,
            circuit_breaker=self.circuit_breaker
        )
        def _fetch() -> list[Any]:
            last_mention_id = self.state.get('last_mention_id')

            mentions = self.twitter_client.get_users_mentions(
                id=self.my_user_id,
                since_id=last_mention_id,
                max_results=10
            )

            return list(reversed(mentions.data)) if mentions and mentions.data else []

        result = _fetch()
        return result if result else []

    def process_mention(self, mention: Any) -> bool:
        """
        Process a single mention and reply.

        Args:
            mention: Twitter mention object

        Returns:
            True if reply was sent successfully
        """
        author_username = self.get_username_by_id(str(mention.author_id))
        logger.info(f"New mention from @{author_username}: {mention.text}")

        response = self.get_claude_response(mention.text, author_username)

        if not response:
            logger.warning(f"Could not generate response for mention {mention.id}")
            self.metrics.record_failure()
            return False

        if self.post_reply(response, str(mention.id)):
            logger.info(f"Replied: {response}")
            self.metrics.mentions_processed += 1
            return True

        return False

    def check_mentions(self) -> None:
        """Check for new mentions and reply to each."""
        if not self.circuit_breaker.can_execute():
            logger.warning("Circuit breaker open, skipping mention check")
            return

        mentions = self.fetch_mentions()

        if not mentions:
            logger.info("No new mentions")
            return

        logger.info(f"Found {len(mentions)} new mention(s)")

        for mention in mentions:
            if not self.running:
                break

            self.process_mention(mention)

            # Update state after each mention
            self.state['last_mention_id'] = str(mention.id)
            self.save_state()

            # Delay between replies to avoid rate limits
            if self.running and mention != mentions[-1]:
                time.sleep(REPLY_DELAY)

    def get_health(self) -> dict[str, Any]:
        """
        Get current bot health status.

        Returns:
            Health status dictionary
        """
        return {
            **self.metrics.get_health_status(),
            "circuit_breaker_state": self.circuit_breaker.state,
            "running": self.running,
        }

    def run(self) -> None:
        """Main bot loop."""
        logger.info("Clod bot starting...")

        # Setup
        self.check_api_keys()
        self.initialize_clients()
        self.authenticate()
        self.state = self.load_state()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        logger.info(f"Checking mentions every {CHECK_MENTIONS_INTERVAL} seconds")
        logger.info("Press Ctrl+C to stop")

        # Main loop
        while self.running:
            try:
                self.check_mentions()
                self.metrics.record_success()
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                self.metrics.record_failure()

                # Back off if too many consecutive failures
                if self.metrics.consecutive_failures >= 3:
                    backoff_time = min(
                        self.metrics.consecutive_failures * 10,
                        300  # Max 5 minutes
                    )
                    logger.warning(
                        f"Multiple failures, backing off for {backoff_time}s"
                    )
                    time.sleep(backoff_time)

            # Sleep in small increments for faster shutdown response
            for _ in range(CHECK_MENTIONS_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

        # Log final metrics on shutdown
        logger.info(f"Final metrics: {self.metrics.get_health_status()}")
        logger.info("Bot stopped")


def main() -> None:
    """Entry point."""
    bot = ClodBot()
    bot.run()


if __name__ == "__main__":
    main()
