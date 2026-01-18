# Clod Bot Architecture

## Overview

Clod is a Twitter bot that uses Claude AI to automatically reply to mentions. This document explains the system architecture and implementation details.

## System Flow

```
┌─────────────────┐
│ Twitter Mention │
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│ Circuit Breaker     │──── OPEN ────► Skip processing
│ Check               │
└────────┬────────────┘
         │ CLOSED/HALF-OPEN
         ▼
┌─────────────────────┐
│ ClodBot.fetch_      │
│ mentions()          │
│ (with retry logic)  │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ ClodBot.get_claude_ │
│ response()          │
│ (with retry logic)  │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ validate_tweet_text │
│ truncate_smart()    │
│ (word-aware trim)   │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ ClodBot.post_reply()│
│ (with retry logic)  │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Update metrics      │
│ Save state          │
└─────────────────────┘
```

## Components

### 1. ClodBot Class (`bot.py`)

Main bot class with the following responsibilities:

| Method | Purpose |
|--------|---------|
| `run()` | Main entry point and event loop |
| `fetch_mentions()` | Poll Twitter for new mentions |
| `get_claude_response()` | Generate AI response |
| `post_reply()` | Send reply to Twitter |
| `process_mention()` | Handle single mention end-to-end |
| `get_health()` | Return current health status |
| `check_api_keys()` | Validate required environment variables |

### 2. BotMetrics Class (`bot.py`)

Dataclass for tracking operational metrics:

```python
@dataclass
class BotMetrics:
    mentions_processed: int = 0
    replies_sent: int = 0
    errors_count: int = 0
    rate_limits_hit: int = 0
    retries_count: int = 0
    start_time: datetime
    last_activity: Optional[datetime]
    consecutive_failures: int = 0
```

Methods:
- `record_success()` - Reset consecutive failures
- `record_failure()` - Increment error counters
- `record_rate_limit()` - Track rate limit hits
- `get_health_status()` - Return health dictionary

### 3. CircuitBreaker Class (`bot.py`)

Implements the circuit breaker pattern:

| State | Behavior |
|-------|----------|
| **Closed** | Normal operation, all requests allowed |
| **Open** | Requests blocked, waiting for recovery |
| **Half-Open** | Single test request allowed |

Configuration:
- `failure_threshold`: Failures before opening (default: 5)
- `recovery_timeout`: Seconds before half-open (default: 60)

### 4. Retry Decorator (`bot.py`)

The `@retry_on_error()` decorator wraps all API calls with:

- **Automatic retries:** Configurable number of attempts (default: 3)
- **Rate limit handling:** Detects `TooManyRequests` and waits `RATE_LIMIT_DELAY` seconds
- **Exponential backoff:** Waits `RETRY_DELAY` seconds between retries
- **Metrics integration:** Records retries and rate limits
- **Circuit breaker integration:** Respects open circuit state

### 5. Input Validation (`bot.py`)

`validate_tweet_text()` checks:
- Non-empty text
- Non-whitespace content
- Within 280 character limit

### 6. Smart Truncation (`bot.py`)

The `truncate_smart()` function ensures responses fit Twitter's 280 character limit:

- Handles empty/whitespace input
- Preserves complete words (no mid-word cuts)
- Adds ellipsis when truncated
- Strips trailing punctuation before ellipsis

### 7. Configuration (`config.py`)

Centralized settings with `typing.Final` for immutability:

```python
# Twitter Settings
MAX_RESPONSE_LENGTH: Final[int] = 280
REPLY_DELAY: Final[int] = 10

# Rate Limiting
RATE_LIMIT_DELAY: Final[int] = 15
MAX_RETRIES: Final[int] = 3
RETRY_DELAY: Final[int] = 5

# Polling
CHECK_MENTIONS_INTERVAL: Final[int] = 60

# Circuit Breaker
CIRCUIT_BREAKER_THRESHOLD: Final[int] = 5
CIRCUIT_BREAKER_TIMEOUT: Final[int] = 60

# Backoff
MAX_BACKOFF_TIME: Final[int] = 300
BACKOFF_MULTIPLIER: Final[int] = 10
```

### 8. State Persistence

Bot state is saved to `state.json` after processing each mention:

```json
{
  "last_mention_id": "1234567890"
}
```

This prevents duplicate replies after restarts.

## Error Handling

| Error Type | Handling |
|------------|----------|
| Rate limit (429) | Wait `RATE_LIMIT_DELAY` seconds, then retry |
| Twitter API error | Retry up to `MAX_RETRIES` times |
| Claude API error | Retry up to `MAX_RETRIES` times |
| Network timeout | Retry with backoff |
| Circuit open | Skip request, log warning |
| Unexpected error | Log, increment failure count, backoff if needed |

### Backoff Strategy

On consecutive failures in main loop:
1. If `consecutive_failures >= 3`: Calculate backoff time
2. Backoff = `min(consecutive_failures * 10, 300)` seconds
3. Log warning and sleep

## Health Monitoring

`get_health()` returns:

```python
{
    "healthy": True,  # False if consecutive_failures >= 5
    "running": True,
    "uptime_seconds": 3600.5,
    "mentions_processed": 42,
    "replies_sent": 40,
    "errors_count": 2,
    "rate_limits_hit": 1,
    "retries_count": 5,
    "consecutive_failures": 0,
    "last_activity": "2025-01-18T12:00:00",
    "circuit_breaker_state": "closed"
}
```

## Graceful Shutdown

The bot handles `SIGINT` and `SIGTERM` signals:

1. Sets `running = False`
2. Completes current mention processing
3. Logs final metrics
4. Saves state
5. Exits cleanly

## Security

- API keys stored in `.env` (never committed)
- `.gitignore` excludes sensitive files
- No credentials in source code
- Input validation prevents malformed tweets

## Testing

65 unit tests covering:

| Test Class | Coverage |
|------------|----------|
| `TestTruncateSmart` | 10 tests |
| `TestValidateTweetText` | 5 tests |
| `TestBotMetrics` | 8 tests |
| `TestCircuitBreaker` | 5 tests |
| `TestClodBotState` | 4 tests |
| `TestClodBotAPIKeys` | 3 tests |
| `TestClodBotSignalHandler` | 1 test |
| `TestClodBotMentionProcessing` | 5 tests |
| `TestClodBotClaudeResponse` | 5 tests |
| `TestClodBotPostReply` | 4 tests |
| `TestClodBotHealth` | 2 tests |
| `TestRetryDecorator` | 6 tests |
| `TestClodBotAuthentication` | 3 tests |
| `TestClodBotGetUsername` | 3 tests |

Run tests:
```bash
python -m unittest test_bot -v
```

## Limitations

- Polling-based (not real-time webhooks)
- Single-threaded processing
- No conversation context between mentions
- No persistent metrics storage (in-memory only)
