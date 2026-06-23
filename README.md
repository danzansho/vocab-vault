# Obsidian Vocabulary Builder Bot 🎙📚

An intelligent, automated Telegram bot written in Python that helps you capture and master new English vocabulary. Using the scientifically proven **SuperMemo-2 (SM-2) Spaced Repetition Algorithm** (the same algorithm behind Anki), the bot manages your learning curve automatically.

## Features
- **Frictionless Capture:** Send any English word via text (e.g., `friction`) or dictate it via voice.
- **AI Translation & Context:** **Whisper** transcribes your voice, and **LLaMA 3.3** automatically translates the word, creates an elegant usage example, and formats it.
- **Direct Vault Sync:** Saves a structured `.md` card directly into your local Obsidian `Inbox` folder.
- **Interactive Quizzes (`/quiz`):** Starts a daily review session inside Telegram, tracking your progress and calculating optimal review intervals based on your self-reported grades (0-5).
- **SQLite Backend:** Completely asynchronous, local-first database structure (`vocab.db`) to keep track of user states and learning intervals.

## Prerequisites
- Python 3.11+
- A Telegram Bot Token (from @BotFather)
- A Groq API Key (from console.groq.com)
- A local Obsidian vault

## Installation & Setup
1. Clone the repository:
git clone https://github.com/danzansho/obsidian-vocab-bot.git
cd obsidian-vocab-bot

2. Create and activate a virtual environment:
python -m venv venv
source venv/Scripts/activate # On Windows Git Bash

3. Install dependencies:
pip install aiogram python-dotenv groq aiosqlite

4. Configure your `.env` file:
BOT_TOKEN=your_telegram_bot_token
GROQ_API_KEY=your_groq_api_key
INBOX_PATH=C:/Path/To/Your/Obsidian/Vault/1 - Inbox

## Usage
Run the bot locally on your machine:
python main.py

Commands:
- `/start`: Set up or update your Obsidian path.
- `/quiz`: Start your daily vocabulary review session.
- `/stats`: Check your learning progress and scheduled reviews.