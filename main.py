import asyncio
import os
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from groq import Groq

# Import database module
import database

# Configure logging
import logging
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
INBOX_PATH = os.getenv("INBOX_PATH")

# Initialize Bot, Dispatcher and Groq Client
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))
dp = Dispatcher()
groq_client = Groq(api_key=GROQ_API_KEY)

# Define FSM States
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
            new_interval = int(prev_interval * prev_ef)
        new_repetitions = prev_repetitions + 1
    else:
        new_interval = 1
        new_repetitions = 0

    new_ef = prev_ef + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    if new_ef < 1.3:
        new_ef = 1.3

    return new_interval, new_ef, new_repetitions


# Handler for /start
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
            f"Ready to learn? Send me a new word (text or voice), or run /quiz to review!"
        )
    else:
        await message.answer(
            f"👋 *Hello, {message.from_user.first_name}!*\n"
            f"───────────────────────\n"
            f"I am your automated English Vocab assistant.\n\n"
            f"Please send me the *absolute path* to your Obsidian `1 - Inbox` folder on your computer."
        )
        await state.set_state(VocabStates.waiting_for_path)

# Handler to capture Obsidian path
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


# Handler for /stats command
@dp.message(Command(commands=["stats"]))
async def cmd_stats(message: types.Message):
    user_id = message.from_user.id
    logging.info(f"User {user_id} requested vocab stats")
    stats = await database.get_vocab_stats(user_id)

    await message.answer(
        f"📊 *Your Vocabulary Stats:*\n"
        f"───────────────────────\n"
        f"📚 *Total words in database:* `{stats['total']}`\n"
        f"⏳ *Words scheduled for today:* `{stats['to_review']}`\n\n"
        f"💡 Use /quiz to start your review session!"
    )


# --- VOCABULARY CAPTURE LOGIC ---
async def process_new_word(user_id: int, raw_input: str, is_voice: bool = False):
    inbox_path = await database.get_user_path(user_id)
    if not inbox_path:
        return "❌ Please run /start to configure your Obsidian path first."

    # Updated prompt to strictly output EXAMPLE in the metadata block
    prompt = f"""
    You are an English teacher assistant.
    The user sent you this raw input: "{raw_input}"

    Do the following:
    1. Extract the main English word.
    2. Provide its Russian translation.
    3. Generate a short, elegant example sentence in English with Russian translation in brackets.
    4. Generate a clean Markdown note for Obsidian.

    You MUST format your output strictly like this (use three hyphens --- as a separator):
    WORD: [english_word]
    TRANSLATION: [russian_translation]
    EXAMPLE: [example_sentence]
    ---
    # [english_word]
    #vocabulary #english

    - **Translation:** [russian_translation]
    - **Context/Example:** [example_sentence]
    """

    completion = groq_client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.3-70b-versatile",
    )

    response_text = completion.choices[0].message.content
    try:
        parts = response_text.split("---")
        meta = parts[0].strip().split("\n")
        markdown_note = parts[1].strip()

        extracted_word = meta[0].replace("WORD:", "").strip().lower()
        extracted_translation = meta[1].replace("TRANSLATION:", "").strip().lower()
        extracted_example = meta[2].replace("EXAMPLE:", "").strip()

        # Save word, translation AND example to the SQLite database
        await database.add_word(user_id, extracted_word, extracted_translation, extracted_example)

        filename = f"{extracted_word}.md"
        full_path = os.path.join(inbox_path, filename)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(markdown_note)

        logging.info(f"Word '{extracted_word}' saved to database and Obsidian for user {user_id}")

        return (
            f"✅ *Word Saved!*\n"
            f"───────────────────────\n"
            f"📝 *Word:* `{extracted_word}`\n"
            f"🇷🇺 *Translation:* {extracted_translation}\n"
            f"💡 *Example:* _{extracted_example}_\n\n"
            f"Added to your Obsidian inbox and active review queue!"
        )
    except Exception as e:
        logging.error(f"Error parsing AI response: {e}")
        return f"❌ Failed to parse AI response. Raw output:\n\n{response_text}"

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
    destination = "temp_voice.ogg"

    try:
        file_id = message.voice.file_id
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, destination)

        await msg.edit_text("🎧 Transcribing...")
        with open(destination, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
              file=(destination, audio_file.read()),
              model="whisper-large-v3",
            )
        raw_text = transcription.text

        await msg.edit_text("🧠 Analyzing and saving...")
        result = await process_new_word(user_id, raw_text, is_voice=True)
        await msg.edit_text(result)

    except Exception as e:
        logging.error(f"Voice processing error: {e}")
        await msg.edit_text(f"❌ Error: {e}")
    finally:
        if os.path.exists(destination):
            os.remove(destination)


# --- INTERACTIVE QUIZ (SM-2) LOGIC ---
class QuizSession:
    def __init__(self, words_list):
        self.words = words_list
        self.current_index = 0

active_quizzes = {}

# Start a review session
@dp.message(Command(commands=["quiz"]))
async def cmd_quiz(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    words_to_review = await database.get_words_to_review(user_id)

    if not words_to_review:
        await message.answer("🎉 *Excellent!* No words to review today. You are completely caught up!")
        return

    active_quizzes[user_id] = QuizSession(words_to_review)
    await state.set_state(VocabStates.quiz_active)
    await ask_next_word(message, user_id)

async def ask_next_word(message: types.Message, user_id: int):
    session = active_quizzes.get(user_id)
    if not session or session.current_index >= len(session.words):
        await bot.send_message(
            chat_id=user_id,
            text="🏁 *Quiz Completed!* Great job. All scheduled words reviewed."
        )
        active_quizzes.pop(user_id, None)
        return

    current_item = session.words[session.current_index]
    total_words = len(session.words)
    current_num = session.current_index + 1

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👁 Show Translation", callback_data=f"reveal_{current_item['word_id']}")]
    ])

    # Clean and structured question card
    await bot.send_message(
        chat_id=user_id,
        text=f"📊 *Word {current_num} of {total_words}*\n"
             f"───────────────────────\n"
             f"How do you translate this word?\n\n"
             f"👉 *{current_item['word'].upper()}*",
        reply_markup=keyboard
    )

@dp.callback_query(F.data.startswith("reveal_"))
async def process_reveal(callback: types.CallbackQuery):
    word_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    session = active_quizzes.get(user_id)

    if not session:
        await callback.answer("Session expired.")
        return

    current_item = session.words[session.current_index]
    total_words = len(session.words)
    current_num = session.current_index + 1

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="0️⃣ (Forgot)", callback_data=f"grade_0_{word_id}"),
            InlineKeyboardButton(text="1️⃣", callback_data=f"grade_1_{word_id}"),
            InlineKeyboardButton(text="2️⃣", callback_data=f"grade_2_{word_id}")
        ],
        [
            InlineKeyboardButton(text="3️⃣", callback_data=f"grade_3_{word_id}"),
            InlineKeyboardButton(text="4️⃣", callback_data=f"grade_4_{word_id}"),
            InlineKeyboardButton(text="5️⃣ (Perfect)", callback_data=f"grade_5_{word_id}")
        ]
    ])

    # Premium-looking reveal card with example sentence!
    await callback.message.edit_text(
        text=f"📊 *Word {current_num} of {total_words}*\n"
             f"───────────────────────\n"
             f"📝 *Word:* ` {current_item['word'].upper()} `\n"
             f"🇷🇺 *Translation:* *{current_item['translation'].upper()}*\n\n"
             f"💡 *Context:* _{current_item['example']}_\n"
             f"───────────────────────\n"
             f"Rate how well you remembered it (0 = forgot, 5 = instant):",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("grade_"))
async def process_grade(callback: types.CallbackQuery, state: FSMContext):
    data_parts = callback.data.split("_")
    grade = int(data_parts[1])
    word_id = int(data_parts[2])
    user_id = callback.from_user.id
    session = active_quizzes.get(user_id)

    if not session:
        await callback.answer("Session expired.")
        return

    current_item = session.words[session.current_index]

    new_interval, new_ef, new_rep = calculate_sm2(
        grade,
        current_item["interval"],
        current_item["ease_factor"],
        current_item["repetitions"]
    )

    next_date = (datetime.datetime.now() + datetime.timedelta(days=new_interval)).strftime("%Y-%m-%d")
    await database.update_word_progress(word_id, new_interval, new_ef, new_rep, next_date)

    logging.info(f"Updated word {word_id} for user {user_id}. Next review: {next_date}, interval: {new_interval}")

    session.current_index += 1
    await callback.message.delete()
    await callback.answer(f"Recorded! Grade: {grade}")

    await ask_next_word(callback.message, user_id)

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