# Obsidian Vocabulary Builder Bot 🎙📚

An intelligent Telegram bot that helps you capture and master English vocabulary using the **SuperMemo-2 (SM-2)** spaced repetition algorithm.

## Features
- **Frictionless Capture:** Send any word via text or voice.
- **AI Translation & Context:** Whisper transcribes voice, LLaMA 3.3 translates and creates usage examples.
- **Obsidian Sync:** Saves structured `.md` cards directly into your local Obsidian Inbox.
- **Interactive Quiz:** Daily review sessions with SM-2 scheduling and self-grading (0–5).
- **Async SQLite:** Local-first database for users, words, and review intervals.

## Tech Stack
- Python 3.11+
- aiogram 3
- Groq API (LLaMA 3.3 + Whisper)
- aiosqlite

## Setup
1. Clone the repo:
```bash
git clone https://github.com/danzansho/obsidian-vocab-bot.git
cd obsidian-vocab-bot