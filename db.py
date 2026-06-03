import os
from datetime import date
import psycopg2
import psycopg2.extras


FREE_LIMIT    = 5
STARTER_LIMIT = 120
PRO_LIMIT     = 400

PLAN_LIMITS = {
    "free":    FREE_LIMIT,
    "starter": STARTER_LIMIT,
    "pro":     PRO_LIMIT,
}


def get_conn():
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS blogs (
            blog_id    TEXT PRIMARY KEY,
            post_count INTEGER DEFAULT 0,
            indexed_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id      SERIAL PRIMARY KEY,
            blog_id TEXT NOT NULL,
            title   TEXT NOT NULL,
            url     TEXT NOT NULL,
            date    TEXT,
            UNIQUE(blog_id, url)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            session_id   TEXT PRIMARY KEY,
            blog_id      TEXT,
            plan         TEXT DEFAULT 'free',
            search_count INTEGER DEFAULT 0,
            is_paid      INTEGER DEFAULT 0,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ip_searches (
            ip           TEXT PRIMARY KEY,
            search_count INTEGER DEFAULT 0,
            reset_date   TEXT DEFAULT '',
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        cur.execute("ALTER TABLE ip_searches ADD COLUMN IF NOT EXISTS reset_date TEXT DEFAULT ''")
    except Exception:
        conn.rollback()
    try:
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT DEFAULT 'free'")
    except Exception:
        conn.rollback()
    conn.commit()
    conn.close()


def ensure_user(session_id: str, blog_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (session_id, blog_id, plan, search_count)
        VALUES (%s, %s, 'free', 0)
        ON CONFLICT (session_id) DO NOTHING
    """, (session_id, blog_id))
    conn.commit()
    conn.close()


def get_search_count(session_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT search_count, plan, is_paid FROM users WHERE session_id = %s",
        (session_id,)
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return 0, "free"
    plan = row["plan"] if row["plan"] else ("starter" if row["is_paid"] else "free")
    return row["search_count"], plan


def get_limit(plan: str) -> int:
    return PLAN_LIMITS.get(plan, FREE_LIMIT)


def get_ip_search_count(ip: str) -> int:
    today = date.today().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT search_count, reset_date FROM ip_searches WHERE ip = %s", (ip,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return 0
    # 날짜가 바뀌면 0으로 초기화
    if row["reset_date"] != today:
        return 0
    return row["search_count"]


def increment_ip_search(ip: str):
    today = date.today().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ip_searches (ip, search_count, reset_date)
        VALUES (%s, 1, %s)
        ON CONFLICT (ip) DO UPDATE SET
            search_count = CASE
                WHEN ip_searches.reset_date = %s THEN ip_searches.search_count + 1
                ELSE 1
            END,
            reset_date = %s
    """, (ip, today, today, today))
    conn.commit()
    conn.close()


def increment_search(session_id: str, blog_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (session_id, blog_id, search_count)
        VALUES (%s, %s, 1)
        ON CONFLICT (session_id) DO UPDATE SET search_count = users.search_count + 1
    """, (session_id, blog_id))
    conn.commit()
    conn.close()


def save_posts(blog_id: str, posts: list):
    conn = get_conn()
    cur = conn.cursor()
    cur.executemany("""
        INSERT INTO posts (blog_id, title, url, date)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (blog_id, url) DO UPDATE SET
            title = EXCLUDED.title,
            date  = EXCLUDED.date
    """, [(blog_id, p["title"], p["url"], p.get("date", "")) for p in posts])
    cur.execute("""
        INSERT INTO blogs (blog_id, post_count, indexed_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (blog_id) DO UPDATE SET
            post_count = EXCLUDED.post_count,
            indexed_at = EXCLUDED.indexed_at
    """, (blog_id, len(posts)))
    conn.commit()
    conn.close()


def get_posts(blog_id: str) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT title, url, date FROM posts WHERE blog_id = %s", (blog_id,))
    rows = cur.fetchall()
    conn.close()
    return [{"title": r["title"], "url": r["url"], "date": r["date"] or ""} for r in rows]


def get_blog(blog_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM blogs WHERE blog_id = %s", (blog_id,))
    row = cur.fetchone()
    conn.close()
    return row
