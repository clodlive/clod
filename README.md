# Clod - AI Twitter Reply Bot

A Twitter bot that automatically replies to mentions using Claude AI with a witty, humorous personality.

## How It Works

1. Bot monitors Twitter for mentions of @AI_clod
2. New mentions are sent to Claude API with a custom personality prompt
3. Claude generates a contextual reply (under 280 characters)
4. Bot posts the reply back to Twitter

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed technical documentation.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your API keys

# Run the bot
python bot.py
```

## Required API Keys

Get these from their respective developer portals:

| Key | Source |
|-----|--------|
| `TWITTER_API_KEY` | [Twitter Developer Portal](https://developer.twitter.com/) |
| `TWITTER_API_SECRET` | [Twitter Developer Portal](https://developer.twitter.com/) |
| `TWITTER_ACCESS_TOKEN` | [Twitter Developer Portal](https://developer.twitter.com/) |
| `TWITTER_ACCESS_SECRET` | [Twitter Developer Portal](https://developer.twitter.com/) |
| `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com/) |

## Bot Personality

Clod is configured with a witty, slightly edgy personality:
- Concise and conversational
- Funny with immature humor
- Sarcastic and nonchalant
- Never acknowledges being an AI

See `config.py` to customize the personality prompt.

## Configuration

All settings are in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `CHECK_MENTIONS_INTERVAL` | 60s | How often to poll for new mentions |
| `MAX_RESPONSE_LENGTH` | 280 | Twitter character limit |
| `RATE_LIMIT_DELAY` | 15s | Wait time when rate limited |
| `MAX_RETRIES` | 3 | Retry attempts for failed API calls |
| `REPLY_DELAY` | 10s | Delay between consecutive replies |

## Technical Details

- **Language:** Python 3.8+
- **AI Model:** Claude Sonnet 4
- **Twitter Library:** Tweepy
- **Features:** Retry logic, rate limit handling, graceful shutdown, state persistence

## License

Apache 2.0 License
