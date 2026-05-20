import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "app.db"

# 플랜별 월 검색 한도
FREE_LIMIT    = 5
STARTER_LIMIT = 120
PRO_LIMIT     = 400

PLAN_LIMITS = {
    "free":    FREE_LIMIT,
    "starter": STARTER_LIMIT,
    "pro":     PRO_LIMIT,
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS blogs (
                blog_id    TEXT PRIMARY KEY,
                post_count INTEGER DEFAULT 0,
                indexed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS posts (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                blog_id TEXT NOT NULL,
                title   TEXT NOT NULL,
                url     TEXT NOT NULL,
                date    TEXT,
                UNIQUE(blog_id, url)
            );

            CREATE TABLE IF NOT EXISTS users (
                session_id   TEXT PRIMARY KEY,
                blog_id      TEXT,
                plan         TEXT DEFAULT 'free',
                search_count INTEGER DEFAULT 0,
                is_paid      INTEGER DEFAULT 0,
                created_at   TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS ip_searches (
                ip           TEXT PRIMARY KEY,
                search_count INTEGER DEFAULT 0,
                created_at   TEXT DEFAULT (datetime('now'))
            );
        """)
        # 기존 DB 마이그레이션
        try:
            conn.execute("ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'")
        except Exception:
            pass


def get_search_count(session_id: str):
    """(count, plan) 반환"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT search_count, plan, is_paid FROM users WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        if not row:
            return 0, "free"
        plan = row["plan"] if row["plan"] else ("starter" if row["is_paid"] else "free")
        return row["search_count"], plan


def get_limit(plan: str) -> int:
    return PLAN_LIMITS.get(plan, FREE_LIMIT)


def get_ip_search_count(ip: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT search_count FROM ip_searches WHERE ip = ?", (ip,)
        ).fetchone()
        return row["search_count"] if row else 0


def increment_ip_search(ip: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO ip_searches (ip, search_count)
            VALUES (?, 1)
            ON CONFLICT(ip) DO UPDATE SET search_count = search_count + 1
        """, (ip,))


def increment_search(session_id: str, blog_id: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (session_id, blog_id, search_count)
            VALUES (?, ?, 1)
            ON CONFLICT(session_id) DO UPDATE SET search_count = search_count + 1
        """, (session_id, blog_id))


def save_posts(blog_id: str, posts: list):
    with get_conn() as conn:
        conn.executemany("""
            INSERT OR IGNORE INTO posts (blog_id, title, url, date)
            VALUES (?, ?, ?, ?)
        """, [(blog_id, p["title"], p["url"], p.get("date", "")) for p in posts])
        conn.execute("""
            INSERT INTO blogs (blog_id, post_count, indexed_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(blog_id) DO UPDATE SET
                post_count = excluded.post_count,
                indexed_at = excluded.indexed_at
        """, (blog_id, len(posts)))


def get_posts(blog_id: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT title, url FROM posts WHERE blog_id = ?", (blog_id,)
        ).fetchall()
        return [{"title": r["title"], "url": r["url"]} for r in rows]


def get_blog(blog_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM blogs WHERE blog_id = ?", (blog_id,)
        ).fetchone()
