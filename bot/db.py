import aiosqlite
import json
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / 'bot.db'

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                username TEXT,
                personal_data_accepted INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                request_type TEXT,
                city TEXT,
                street TEXT,
                house_apartment TEXT,
                description TEXT,
                phone TEXT,
                audio_file_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        async with db.execute("PRAGMA table_info(requests)") as cur:
            cols = [row[1] for row in await cur.fetchall()]
        if cols and "phone" not in cols:
            await db.execute("ALTER TABLE requests ADD COLUMN phone TEXT")

        await db.commit()

async def get_user(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT * FROM users WHERE user_id = ?', (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def create_user(user_id: int, name: str = None, username: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''INSERT OR IGNORE INTO users (user_id, name, username) 
               VALUES (?, ?, ?)''',
            (user_id, name, username)
        )
        await db.commit()

async def update_consent(user_id: int, accepted: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'UPDATE users SET personal_data_accepted = ? WHERE user_id = ?',
            (1 if accepted else 0, user_id)
        )
        await db.commit()

async def save_request(
    user_id: int,
    request_type: str,
    city: str,
    street: str,
    house_apartment: str,
    description: str,
    phone: str = "",
    audio_file_id: str = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''INSERT INTO requests 
               (user_id, request_type, city, street, house_apartment, description, phone, audio_file_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                user_id,
                request_type,
                city,
                street,
                house_apartment,
                description,
                phone or "",
                audio_file_id,
            ),
        )
        await db.commit()
        async with db.execute(
            'SELECT last_insert_rowid() as id'
        ) as cursor:
            row = await cursor.fetchone()
            return row[0]


async def get_request(request_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM requests WHERE id = ?", (request_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_latest_request_id_for_user(user_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM requests WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else None


async def update_request_status(request_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            (status, request_id),
        )
        await db.commit()