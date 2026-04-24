import aiomysql
import json
import asyncio

with open('config.json', encoding="utf-8") as f:
    config = json.load(f)

db_config = config['DATABASE']

class Database:
    _pool = None

    @classmethod
    async def get_pool(cls):
        if cls._pool is None:
            cls._pool = await aiomysql.create_pool(
                host=db_config['HOST'],
                port=db_config['PORT'],
                user=db_config['USER'],
                password=db_config['PASS'],
                db=db_config['NAME'],
                autocommit=True
            )
        return cls._pool

    @classmethod
    async def execute(cls, query, params=None):
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchall()

    @classmethod
    async def init_db(cls):
        queries = [
            """
            CREATE TABLE IF NOT EXISTS scheduled_announcements (
                id INT AUTO_INCREMENT PRIMARY KEY,
                channel_id BIGINT NOT NULL,
                message TEXT NOT NULL,
                embed_json TEXT,
                scheduled_at DATETIME NOT NULL,
                sent BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS bot_crashes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                error_type VARCHAR(255),
                error_message TEXT,
                stack_trace TEXT,
                cog_name VARCHAR(255),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS staff_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                staff_id BIGINT,
                action VARCHAR(255),
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS member_stats (
                id INT AUTO_INCREMENT PRIMARY KEY,
                guild_id BIGINT,
                member_count INT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        ]
        
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for query in queries:
                    await cur.execute(query)
        print("Database initialized successfully.")

async def main():
    await Database.init_db()

if __name__ == "__main__":
    asyncio.run(main())
