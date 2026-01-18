"""
Configuration for Clod Twitter Bot
Contains the AI personality and bot settings
"""

from typing import Final

# Claude AI System Prompt - Defines Clod's personality
CLOD_SYSTEM_PROMPT: Final[str] = """You are Clod, a funny and witty personality on Twitter.

Your personality:
- Concise and conversational
- Funny and jokeful
- Slightly witty and nonchalant
- You don't acknowledge you're an AI bot
- Edgy and sarcastic

Guidelines:
- Keep responses under 280 characters
- Be funny and creative
- Use immature humour
- If someone asks something harmful, politely decline
- You can use emojis sparingly
"""

# Twitter Settings
MAX_RESPONSE_LENGTH: Final[int] = 280  # Twitter character limit
REPLY_DELAY: Final[int] = 10  # Seconds between replies to avoid spam

# Rate Limiting
RATE_LIMIT_DELAY: Final[int] = 15  # Seconds to wait when rate limited by Twitter
MAX_RETRIES: Final[int] = 3  # Number of retry attempts for failed API calls
RETRY_DELAY: Final[int] = 5  # Seconds between retry attempts

# Polling Settings
CHECK_MENTIONS_INTERVAL: Final[int] = 60  # How often to check for new mentions (seconds)

# State Persistence
STATE_FILE: Final[str] = "state.json"  # File to persist bot state between restarts

# Circuit Breaker Settings
CIRCUIT_BREAKER_THRESHOLD: Final[int] = 5  # Failures before circuit opens
CIRCUIT_BREAKER_TIMEOUT: Final[int] = 60  # Seconds before circuit attempts recovery

# Backoff Settings
MAX_BACKOFF_TIME: Final[int] = 300  # Maximum backoff time in seconds (5 minutes)
BACKOFF_MULTIPLIER: Final[int] = 10  # Multiply consecutive failures by this
