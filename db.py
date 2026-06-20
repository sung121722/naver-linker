import os
from datetime import date
import psycopg2
import psycopg2.extras


FREE_LIMIT = 30

PLAN_LIMITS = {
    "free":    FREE_LIMIT,
    "light":   200,
    "basic":   500,
    "pro":     1000,
}


def get_conn():
    url = os.environ.get("SUPABASE_URL") or os.environ.get("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id          SERIAL PRIMARY KEY,
            order_id    TEXT UNIQUE NOT NULL,
            session_id  TEXT NOT NULL,
            plan        TEXT NOT NULL,
            amount      INTEGER NOT NULL,
            payment_key TEXT,
            status      TEXT DEFAULT 'pending',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ip_registrations (
            ip      TEXT NOT NULL,
            blog_id TEXT NOT NULL,
            PRIMARY KEY (ip, blog_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_blogs (
            session_id  TEXT NOT NULL,
            blog_id     TEXT NOT NULL,
            added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (session_id, blog_id)
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
    try:
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_at TIMESTAMP")
    except Exception:
        conn.rollback()
    try:
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS billing_key TEXT")
    except Exception:
        conn.rollback()
    try:
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS customer_key TEXT")
    except Exception:
        conn.rollback()
    try:
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS next_billing_date DATE")
    except Exception:
        conn.rollback()
    conn.commit()
    conn.close()


MAX_BLOGS_PER_IP = 3  # Pro 플랜 IP 한도
MAX_BLOGS_PER_IP_DEFAULT = 1  # free/light/basic IP 한도

def check_and_record_ip_registration(ip: str, blog_id: str, max_blogs: int = MAX_BLOGS_PER_IP_DEFAULT) -> bool:
    """IP당 등록 가능한 blogId 수를 확인하고 기록. 초과 시 False 반환."""
    conn = get_conn()
    cur = conn.cursor()
    # 이미 이 IP로 등록한 blogId 목록 조회
    cur.execute("SELECT blog_id FROM ip_registrations WHERE ip = %s", (ip,))
    registered = {r["blog_id"] for r in cur.fetchall()}

    if blog_id in registered:
        # 동일 blogId 재수집 → 항상 허용
        conn.close()
        return True

    if len(registered) >= max_blogs:
        conn.close()
        return False

    # 새 blogId 기록
    cur.execute(
        "INSERT INTO ip_registrations (ip, blog_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (ip, blog_id)
    )
    conn.commit()
    conn.close()
    return True


def remove_ip_registration(ip: str, blog_id: str = ""):
    """ip_registrations에서 제거. blog_id 없으면 해당 IP 전체 제거."""
    conn = get_conn()
    cur = conn.cursor()
    if blog_id:
        cur.execute("DELETE FROM ip_registrations WHERE ip = %s AND blog_id = %s", (ip, blog_id))
    else:
        cur.execute("DELETE FROM ip_registrations WHERE ip = %s", (ip,))
    conn.commit()
    conn.close()


def remove_user_blog(session_id: str, blog_id: str):
    """user_blogs에서 특정 블로그 제거 (Pro ✕ 버튼용)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_blogs WHERE session_id = %s AND blog_id = %s", (session_id, blog_id))
    conn.commit()
    conn.close()


def clear_user_blogs(session_id: str):
    """세션의 모든 user_blogs 제거 (non-pro 교체 시)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_blogs WHERE session_id = %s", (session_id,))
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
    this_month = date.today().strftime("%Y-%m")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT search_count, reset_date FROM ip_searches WHERE ip = %s", (ip,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return 0
    # 월이 바뀌면 0으로 초기화
    if (row["reset_date"] or "")[:7] != this_month:
        return 0
    return row["search_count"]


def increment_ip_search(ip: str):
    today = date.today().isoformat()
    this_month = date.today().strftime("%Y-%m")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ip_searches (ip, search_count, reset_date)
        VALUES (%s, 1, %s)
        ON CONFLICT (ip) DO UPDATE SET
            search_count = CASE
                WHEN LEFT(ip_searches.reset_date, 7) = %s THEN ip_searches.search_count + 1
                ELSE 1
            END,
            reset_date = %s
    """, (ip, today, this_month, today))
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


def get_latest_by_keyword(blog_id: str, keyword: str, n: int) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT title, url, date FROM posts WHERE blog_id = %s AND LOWER(title) LIKE LOWER(%s)",
        (blog_id, f"%{keyword}%")
    )
    rows = cur.fetchall()
    conn.close()
    result = [{"title": r["title"], "url": r["url"], "date": r["date"] or "", "score": 80} for r in rows]
    def logno(p):
        part = p["url"].rsplit("/", 1)[-1]
        return int(part) if part.isdigit() else 0
    result.sort(key=logno, reverse=True)
    return result[:n]


def get_posts(blog_id: str) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT title, url, date FROM posts WHERE blog_id = %s ORDER BY id DESC", (blog_id,))
    rows = cur.fetchall()
    conn.close()
    return [{"title": r["title"], "url": r["url"], "date": r["date"] or ""} for r in rows]


def create_order(order_id: str, session_id: str, plan: str, amount: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO payments (order_id, session_id, plan, amount)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (order_id) DO NOTHING
    """, (order_id, session_id, plan, amount))
    conn.commit()
    conn.close()


def confirm_payment(order_id: str, payment_key: str):
    """결제 승인 처리: payments 업데이트 + 해당 유저 plan 업그레이드 & search_count 리셋"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM payments WHERE order_id = %s", (order_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    cur.execute(
        "UPDATE payments SET status = 'paid', payment_key = %s WHERE order_id = %s",
        (payment_key, order_id)
    )
    cur.execute(
        "UPDATE users SET plan = %s, search_count = 0, reset_at = NOW() WHERE session_id = %s",
        (row["plan"], row["session_id"])
    )
    conn.commit()
    result = dict(row)
    conn.close()
    return result


def get_plan_info(session_id: str):
    """현재 플랜 + 사용량 조회"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT plan, search_count FROM users WHERE session_id = %s", (session_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"plan": "free", "search_count": 0, "daily_limit": FREE_LIMIT}
    plan = row["plan"] or "free"
    limit = get_limit(plan)
    return {"plan": plan, "search_count": row["search_count"], "daily_limit": limit}


def get_blog(blog_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM blogs WHERE blog_id = %s", (blog_id,))
    row = cur.fetchone()
    conn.close()
    return row


def reset_monthly_if_due(session_id: str):
    """유료 플랜 30일 주기 검색 횟수 자동 리셋 (lazy 방식)."""
    from datetime import datetime, timedelta
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT plan, reset_at FROM users WHERE session_id = %s", (session_id,))
    row = cur.fetchone()
    if not row or row["plan"] == "free" or not row["reset_at"]:
        conn.close()
        return
    if datetime.now() >= row["reset_at"] + timedelta(days=30):
        cur.execute(
            "UPDATE users SET search_count = 0, reset_at = NOW() WHERE session_id = %s",
            (session_id,)
        )
        conn.commit()
    conn.close()


def cancel_subscription(session_id: str):
    """구독 해지: 플랜을 free로 즉시 전환 + 빌링키 삭제 (재청구 방지)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """UPDATE users
           SET plan = 'free', search_count = 0,
               billing_key = NULL, customer_key = NULL, next_billing_date = NULL
           WHERE session_id = %s""",
        (session_id,)
    )
    conn.commit()
    conn.close()


MAX_BLOGS_PRO = 3

def add_user_blog(session_id: str, blog_id: str, max_blogs: int = 0) -> bool:
    """블로그 목록에 추가. max_blogs > 0이면 한도 초과 시 False 반환."""
    conn = get_conn()
    cur = conn.cursor()
    # 이미 등록된 블로그면 OK
    cur.execute("SELECT 1 FROM user_blogs WHERE session_id = %s AND blog_id = %s", (session_id, blog_id))
    if cur.fetchone():
        conn.close()
        return True
    # 한도 체크
    if max_blogs > 0:
        cur.execute("SELECT COUNT(*) AS cnt FROM user_blogs WHERE session_id = %s", (session_id,))
        if cur.fetchone()["cnt"] >= max_blogs:
            conn.close()
            return False
    cur.execute(
        "INSERT INTO user_blogs (session_id, blog_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (session_id, blog_id)
    )
    conn.commit()
    conn.close()
    return True


def save_billing_key(session_id: str, billing_key: str, customer_key: str, plan: str, amount: int):
    """빌링키 저장 + 플랜 활성화 + 다음 결제일 설정."""
    from datetime import datetime, timedelta
    conn = get_conn()
    cur = conn.cursor()
    next_date = (datetime.now() + timedelta(days=30)).date()
    cur.execute("""
        UPDATE users
        SET billing_key = %s, customer_key = %s, plan = %s,
            search_count = 0, reset_at = NOW(), next_billing_date = %s
        WHERE session_id = %s
    """, (billing_key, customer_key, plan, next_date, session_id))
    conn.commit()
    conn.close()


def get_users_due_for_billing():
    """오늘 결제일이 된 유료 유저 목록 반환."""
    from datetime import date as date_type
    conn = get_conn()
    cur = conn.cursor()
    today = date_type.today()
    cur.execute("""
        SELECT session_id, billing_key, customer_key, plan
        FROM users
        WHERE plan != 'free'
          AND billing_key IS NOT NULL
          AND next_billing_date <= %s
    """, (today,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_next_billing_date(session_id: str):
    """결제 성공 후 다음 결제일 30일 연장 + 횟수 리셋."""
    from datetime import datetime, timedelta
    conn = get_conn()
    cur = conn.cursor()
    next_date = (datetime.now() + timedelta(days=30)).date()
    cur.execute("""
        UPDATE users
        SET next_billing_date = %s, search_count = 0, reset_at = NOW()
        WHERE session_id = %s
    """, (next_date, session_id))
    conn.commit()
    conn.close()


def downgrade_to_free(session_id: str):
    """결제 실패 시 free 플랜으로 다운그레이드."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE users
        SET plan = 'free', billing_key = NULL, customer_key = NULL,
            next_billing_date = NULL
        WHERE session_id = %s
    """, (session_id,))
    conn.commit()
    conn.close()


def get_user_blogs(session_id: str) -> list:
    """세션이 등록한 블로그 목록 반환 (최신 등록 순)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT blog_id FROM user_blogs WHERE session_id = %s ORDER BY added_at DESC",
        (session_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return [r["blog_id"] for r in rows]
