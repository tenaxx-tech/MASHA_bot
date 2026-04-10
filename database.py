import aiosqlite
import time
from datetime import datetime, timedelta

DB_PATH = "bot_data.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                current_model TEXT,
                last_activity TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS weekly_image_usage (
                user_id INTEGER,
                week_start TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, week_start)
            )
        ''')
        await db.commit()

async def get_user_balance(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def add_balance(user_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        if db.total_changes == 0:
            await db.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, amount))
        await db.commit()

async def deduct_balance(user_id: int, amount: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] >= amount:
                await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
                await db.commit()
                return True
        return False

async def save_message(user_id: int, role: str, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )
        await db.commit()

async def get_history(user_id: int, limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return list(reversed(rows))

async def clear_history(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
        await db.commit()

def get_week_start():
    today = datetime.now().date()
    start = today - timedelta(days=today.weekday())
    return start.isoformat()

async def get_weekly_image_count(user_id: int) -> int:
    week_start = get_week_start()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT count FROM weekly_image_usage WHERE user_id = ? AND week_start = ?",
            (user_id, week_start)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def increment_weekly_image_count(user_id: int):
    week_start = get_week_start()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO weekly_image_usage (user_id, week_start, count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, week_start) DO UPDATE SET count = count + 1
        ''', (user_id, week_start))
        await db.commit()
