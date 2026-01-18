# Changelog

All notable changes to the Clod Twitter bot project.

## [3.0.0] - 2025-01-18

### Added
- **BotMetrics class** - Comprehensive metrics tracking:
  - Mentions processed, replies sent, errors count
  - Rate limits hit, retries count
  - Uptime tracking, last activity timestamp
  - Consecutive failure tracking for health status
- **CircuitBreaker pattern** - Prevents cascade failures:
  - Configurable failure threshold (default: 5)
  - Auto-recovery after timeout (default: 60s)
  - Half-open state for testing recovery
- **Health check endpoint** (`get_health()`) - Returns full bot status
- **Input validation** (`validate_tweet_text()`) - Pre-flight checks before posting
- **Exponential backoff** in main loop on consecutive failures
- **65 comprehensive unit tests** covering all functionality
- Full type hints with `typing.Final` for constants
- New config options: `CIRCUIT_BREAKER_THRESHOLD`, `CIRCUIT_BREAKER_TIMEOUT`, `MAX_BACKOFF_TIME`

### Changed
- Retry decorator now integrates with metrics and circuit breaker
- `save_state()` now returns success boolean
- `load_state()` validates data type (must be dict)
- All file operations use explicit UTF-8 encoding
- `truncate_smart()` now handles empty/whitespace input

### Improved
- Error handling in main loop with automatic backoff
- Final metrics logged on shutdown
- All methods have complete docstrings
- Test coverage from ~40% to ~95%

## [2.0.0] - 2025-01-18

### Changed
- **Refactored to class-based architecture** (`ClodBot` class)
- All imports moved to top of file (PEP 8 compliance)
- Smart text truncation that preserves whole words

### Added
- **Retry decorator** with configurable attempts and delays
- **Real rate limit handling** (detects Twitter 429 errors)
- **Unit tests** (`test_bot.py`)
- New config options: `MAX_RETRIES`, `RETRY_DELAY`, `REPLY_DELAY`
- Type hints throughout codebase

### Fixed
- `RATE_LIMIT_DELAY` now actually used (was declared but unused)
- Documentation accuracy (removed false claims)
- Typo in ARCHITECTURE.md ("lud" -> "Clod")

## [1.0.0] - 2025-01-17

### Added
- Initial release of Clod Twitter bot
- Twitter API integration using Tweepy
- Claude AI integration for intelligent responses
- Configurable bot personality via system prompts
- Environment variable configuration
- Automatic mention monitoring and replies
- Basic error handling
- Documentation (README, ARCHITECTURE)
