import aiosqlite
from datetime import datetime, timezone

DB_PATH = "vocab.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                obsidian_path TEXT,
                notes_created INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS words (
                word_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                word TEXT,
                translation TEXT,
                example TEXT,
                next_review TEXT,
                interval INTEGER DEFAULT 0,
                ease_factor REAL DEFAULT 2.5,
                repetitions INTEGER DEFAULT 0,
                created_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)
        await db.commit()


async def save_user_path(user_id: int, path: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, obsidian_path)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET obsidian_path = excluded.obsidian_path
        """, (user_id, path))
        await db.commit()


async def get_user_path(user_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT obsidian_path FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def find_word(user_id: int, word: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT word_id, word, translation, example FROM words "
            "WHERE user_id = ? AND LOWER(word) = ?",
            (user_id, word.lower().strip())
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "word_id": row[0],
                    "word": row[1],
                    "translation": row[2],
                    "example": row[3]
                }
            return None


async def add_word(user_id: int, word: str, translation: str, example: str):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO words (user_id, word, translation, example, next_review, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, word.lower().strip(), translation.strip(), example.strip(), today, today))
        await db.commit()


async def get_words_to_review(user_id: int):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT word_id, word, translation, example, interval, ease_factor, repetitions
            FROM words
            WHERE user_id = ? AND next_review <= ?
            ORDER BY next_review ASC, word ASC
        """, (user_id, today)) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "word_id": r[0],
                    "word": r[1],
                    "translation": r[2],
                    "example": r[3],
                    "interval": r[4],
                    "ease_factor": r[5],
                    "repetitions": r[6]
                } for r in rows
            ]


async def update_word_progress(word_id: int, interval: int, ease_factor: float, repetitions: int, next_review_date: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE words
            SET interval = ?, ease_factor = ?, repetitions = ?, next_review = ?
            WHERE word_id = ?
        """, (interval, ease_factor, repetitions, next_review_date, word_id))
        await db.commit()


async def get_vocab_stats(user_id: int):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM words WHERE user_id = ?", (user_id,)) as cursor:
            total_words = (await cursor.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM words WHERE user_id = ? AND next_review <= ?",
            (user_id, today)
        ) as cursor:
            to_review = (await cursor.fetchone())[0]

        return {"total": total_words, "to_review": to_review}