import asyncio
import json
import os
import re
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from groq import Groq

import database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INBOX_PATH = os.getenv("INBOX_PATH")  # fallback if no DB path

if not BOT_TOKEN or not GROQ_API_KEY:
    raise RuntimeError("BOT_TOKEN and GROQ_API_KEY are required")

# Initialize Bot, Dispatcher and Groq Client
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))
dp = Dispatcher()
groq_client = Groq(api_key=GROQ_API_KEY)


# --- FSM STATES ---
class VocabStates(StatesGroup):
    waiting_for_path = State()
    quiz_active = State()


# --- SUPERMEMO-2 (SM-2) ALGORITHM ---
def calculate_sm2(q: int, prev_interval: int, prev_ef: float, prev_repetitions: int):
    if q >= 3:
        if prev_repetitions == 0:
            new_interval = 1
        elif prev_repetitions == 1:
            new_interval = 6
        else:
            new_interval = int(round(prev_interval * prev_ef))
        new_repetitions = prev_repetitions + 1
    else:
        new_interval = 1
        new_repetitions = 0

    new_ef = prev_ef + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_ef = max(1.3, new_ef)

    return new_interval, new_ef, new_repetitions


# --- HELPERS ---
def safe_filename(word: str) -> str:
    """Remove unsafe characters and prevent directory traversal."""
    cleaned = re.sub(r"[^\w\s-]", "", word).strip().replace(" ", "_")
    return (cleaned[:50] or "word") + ".md"


def now_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def get_inbox_path(user_id: int) -> str | None:
    """Return user path from DB or fallback from env."""
    user_path = await database.get_user_path(user_id)
    if user_path and os.path.isdir(user_path):
        return user_path
    if INBOX_PATH and os.path.isdir(INBOX_PATH):
        return INBOX_PATH
    return None


# --- HANDLERS ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    logging.info(f"User {user_id} triggered /start")
    user_path = await database.get_user_path(user_id)

    if user_path:
        await message.answer(
            f"👋 *Welcome back, {message.from_user.first_name}!*\n"
            f"───────────────────────\n"
            f"📂 *Your Obsidian Path:*\n`{user_path}`\n\n"
            f"Send me a new word (text or voice), or run /quiz to review!"
        )
    else:
        await message.answer(
            f"👋 *Hello, {message.from_user.first_name}!*\n"
            f"───────────────────────\n"
            f"I am your automated English Vocab assistant.\n\n"
            f"Please send me the *absolute path* to your Obsidian `1 - Inbox` folder."
        )
        await state.set_state(VocabStates.waiting_for_path)


@dp.message(VocabStates.waiting_for_path)
async def process_path(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    path = message.text.strip().replace("\\", "/")

    if not os.path.isdir(path):
        await message.answer("❌ *Invalid Path!* This directory does not exist. Please try again.")
        return

    await database.save_user_path(user_id, path)
    logging.info(f"User {user_id} configured path: {path}")
    await message.answer("✅ *Path saved successfully!* Now send me a word or record a voice note.")
    await state.clear()


@dp.message(Command(commands=["stats"]))
async def cmd_stats(message: types.Message):
    user_id = message.from_user.id
    logging.info(f"User {user_id} requested vocab stats")
    stats = await database.get_vocab_stats(user_id)

    await message.answer(
        f"📊 *Your Vocabulary Stats:*\n"
        f"───────────────────────\n"
        f"📚 *Total words:* `{stats['total']}`\n"
        f"⏳ *Words to review:* `{stats['to_review']}`\n\n"
        f"💡 Use /quiz to start your review session!"
    )


# --- VOCABULARY CAPTURE ---
async def process_new_word(user_id: int, raw_input: str, is_voice: bool = False):
    inbox_path = await get_inbox_path(user_id)
    if not inbox_path:
        return "❌ Please run /start to configure your Obsidian path first."

    prompt = f"""
You are an English vocabulary assistant. The user sent: "{raw_input}".

Identify the main English word. If the input is in Russian, translate it to English first.
Return ONLY a valid JSON object with exactly these keys:
- "word": the English word
- "translation": Russian translation
- "example": a short English example sentence with Russian translation in brackets

Example output:
{{"word": "friction", "translation": "трение", "example": "There was some friction between the team members. [Между членами команды возникло некоторое трение.]"}}
"""

    try:
        completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        data = json.loads(completion.choices[0].message.content)
        word = data["word"].strip().lower()
        translation = data["translation"].strip()
        example = data["example"].strip()

        if not word or not translation:
            raise ValueError("LLM returned empty word or translation")

        # Check for duplicate before saving
        existing = await database.find_word(user_id, word)
        if existing:
            return (
                f"⚠️ Word `{existing['word']}` already exists in your library.\n"
                f"🇷🇺 {existing['translation']}\n"
                f"💡 _{existing['example']}_"
            )

        # Save to database
        await database.add_word(user_id, word, translation, example)

        # Save Markdown note to Obsidian
        markdown_note = (
            f"# {word}\n"
            f"#vocabulary #english\n\n"
            f"- **Translation:** {translation}\n"
            f"- **Context/Example:** {example}\n"
        )
        filename = safe_filename(word)
        full_path = os.path.join(inbox_path, filename)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(markdown_note)

        logging.info(f"Word '{word}' saved for user {user_id}")

        return (
            f"✅ *Word Saved!*\n"
            f"───────────────────────\n"
            f"📝 *Word:* `{word}`\n"
            f"🇷🇺 *Translation:* {translation}\n"
            f"💡 *Example:* _{example}_\n\n"
            f"Added to your Obsidian inbox and review queue!"
        )

    except Exception as e:
        logging.error(f"Error processing word for user {user_id}: {e}")
        return "❌ Failed to process the word. Please try again with clearer input."


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_capture(message: types.Message):
    user_id = message.from_user.id
    msg = await message.answer("🧠 Processing word...")
    result = await process_new_word(user_id, message.text)
    await msg.edit_text(result)


@dp.message(F.voice)
async def handle_voice_capture(message: types.Message):
    user_id = message.from_user.id
    msg = await message.answer("⏳ Downloading audio...")

    # Unique temp file per user & message to avoid race conditions
    temp_file = f"temp_voice_{user_id}_{message.message_id}.ogg"

    try:
        file = await bot.get_file(message.voice.file_id)
        await bot.download_file(file.file_path, temp_file)

        await msg.edit_text("🎧 Transcribing...")
        with open(temp_file, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
                file=(temp_file, audio_file.read()),
                model="whisper-large-v3",
            )

        await msg.edit_text("🧠 Analyzing and saving...")
        result = await process_new_word(user_id, transcription.text, is_voice=True)
        await msg.edit_text(result)

    except Exception as e:
        logging.error(f"Voice processing error for user {user_id}: {e}")
        await msg.edit_text("❌ Could not process voice message. Please try text.")
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)


# --- INTERACTIVE QUIZ (FSM) ---
@dp.message(Command(commands=["quiz"]))
async def cmd_quiz(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    words_to_review = await database.get_words_to_review(user_id)

    if not words_to_review:
        await message.answer("🎉 *Excellent!* No words to review today. You are completely caught up!")
        return

    await state.set_state(VocabStates.quiz_active)
    await state.update_data(words=words_to_review, index=0)
    await ask_next_word(user_id, state)


async def ask_next_word(user_id: int, state: FSMContext):
    data = await state.get_data()
    words = data.get("words", [])
    index = data.get("index", 0)

    if index >= len(words):
        await bot.send_message(chat_id=user_id, text="🏁 *Quiz completed!* Great job.")
        await state.clear()
        return

    current = words[index]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👁 Show Translation", callback_data="reveal")]
    ])

    await bot.send_message(
        chat_id=user_id,
        text=f"📊 *Word {index + 1} of {len(words)}*\n"
             f"───────────────────────\n"
             f"How do you translate this word?\n\n"
             f"👉 *{current['word'].upper()}*",
        reply_markup=keyboard
    )


@dp.callback_query(F.data == "reveal")
async def process_reveal(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    words = data.get("words", [])
    index = data.get("index", 0)

    if not words or index >= len(words):
        await callback.answer("Session expired.")
        return

    current = words[index]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="0️⃣", callback_data="grade_0"),
            InlineKeyboardButton(text="1️⃣", callback_data="grade_1"),
            InlineKeyboardButton(text="2️⃣", callback_data="grade_2"),
        ],
        [
            InlineKeyboardButton(text="3️⃣", callback_data="grade_3"),
            InlineKeyboardButton(text="4️⃣", callback_data="grade_4"),
            InlineKeyboardButton(text="5️⃣", callback_data="grade_5"),
        ]
    ])

    await callback.message.edit_text(
        text=f"📊 *Word {index + 1} of {len(words)}*\n"
             f"───────────────────────\n"
             f"📝 *Word:* `{current['word'].upper()}`\n"
             f"🇷🇺 *Translation:* {current['translation'].upper()}\n\n"
             f"💡 *Context:* _{current['example']}_\n"
             f"───────────────────────\n"
             f"Rate how well you remembered it (0 = forgot, 5 = perfect):",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("grade_"))
async def process_grade(callback: types.CallbackQuery, state: FSMContext):
    grade = int(callback.data.split("_")[1])
    data = await state.get_data()
    words = data.get("words", [])
    index = data.get("index", 0)

    if not words or index >= len(words):
        await callback.answer("Session expired.")
        return

    current = words[index]
    new_interval, new_ef, new_rep = calculate_sm2(
        grade,
        current["interval"],
        current["ease_factor"],
        current["repetitions"]
    )

    next_date = (datetime.now(timezone.utc) + timedelta(days=new_interval)).strftime("%Y-%m-%d")
    await database.update_word_progress(current["word_id"], new_interval, new_ef, new_rep, next_date)

    logging.info(f"Updated word {current['word_id']} for user {callback.from_user.id}. Next: {next_date}")

    await state.update_data(index=index + 1)
    await callback.message.delete()
    await callback.answer(f"Recorded: {grade}")

    await ask_next_word(callback.from_user.id, state)


async def main():
    await database.init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="Set up or update your Obsidian path"),
        BotCommand(command="quiz", description="Start daily vocabulary review session"),
        BotCommand(command="stats", description="Check your vocabulary stats")
    ])
    logging.info("Database initialized. Vocab Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())