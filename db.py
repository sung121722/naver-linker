import os
from contextlib import contextmanager
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


@contextmanager
def get_db():
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS otp_store (
                email      TEXT PRIMARY KEY,
                code       TEXT NOT NULL,
                expires_at DOUBLE PRECISION NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS whale_relay (
                blog_id    TEXT PRIMARY KEY,
                posts_json TEXT NOT NULL,
                cached_at  DOUBLE PRECISION NOT NULL
            )
        """)
        for alter in [
            "ALTER TABLE ip_searches ADD COLUMN IF NOT EXISTS reset_date TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT DEFAULT 'free'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS billing_key TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS customer_key TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS next_billing_date DATE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS links_copied INTEGER DEFAULT 0",
        ]:
            try:
                cur.execute(alter)
            except Exception:
                conn.rollback()
        conn.commit()


MAX_BLOGS_PER_IP = 3
MAX_BLOGS_PER_IP_DEFAULT = 1

def check_and_record_ip_registration(ip: str, blog_id: str, max_blogs: int = MAX_BLOGS_PER_IP_DEFAULT) -> bool:
    """IP당 등록 가능한 blogId 수를 확인하고 기록. 초과 시 False 반환."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT blog_id FROM ip_registrations WHERE ip = %s", (ip,))
        registered = {r["blog_id"] for r in cur.fetchall()}

        if blog_id in registered:
            return True

        if len(registered) >= max_blogs:
            return False

        cur.execute(
            "INSERT INTO ip_registrations (ip, blog_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (ip, blog_id)
        )
        conn.commit()
        return True


def remove_ip_registration(ip: str, blog_id: str = ""):
    """ip_registrations에서 제거. blog_id 없으면 해당 IP 전체 제거."""
    with get_db() as conn:
        cur = conn.cursor()
        if blog_id:
            cur.execute("DELETE FROM ip_registrations WHERE ip = %s AND blog_id = %s", (ip, blog_id))
        else:
            cur.execute("DELETE FROM ip_registrations WHERE ip = %s", (ip,))
        conn.commit()


def remove_user_blog(session_id: str, blog_id: str):
    """user_blogs에서 특정 블로그 제거 (Pro ✕ 버튼용)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_blogs WHERE session_id = %s AND blog_id = %s", (session_id, blog_id))
        conn.commit()


def clear_user_blogs(session_id: str):
    """세션의 모든 user_blogs 제거 (non-pro 교체 시)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_blogs WHERE session_id = %s", (session_id,))
        conn.commit()


def ensure_user(session_id: str, blog_id: str):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (session_id, blog_id, plan, search_count)
            VALUES (%s, %s, 'free', 0)
            ON CONFLICT (session_id) DO NOTHING
        """, (session_id, blog_id))
        conn.commit()


def get_search_count(session_id: str):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT search_count, plan, is_paid FROM users WHERE session_id = %s",
            (session_id,)
        )
        row = cur.fetchone()
    if not row:
        return 0, "free"
    plan = row["plan"] or "free"
    return row["search_count"], plan


def get_limit(plan: str) -> int:
    return PLAN_LIMITS.get(plan, FREE_LIMIT)


def get_ip_search_count(ip: str) -> int:
    this_month = date.today().strftime("%Y-%m")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT search_count, reset_date FROM ip_searches WHERE ip = %s", (ip,))
        row = cur.fetchone()
    if not row:
        return 0
    if (row["reset_date"] or "")[:7] != this_month:
        return 0
    return row["search_count"]


def increment_ip_search(ip: str):
    today = date.today().isoformat()
    this_month = date.today().strftime("%Y-%m")
    with get_db() as conn:
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


def increment_search(session_id: str, blog_id: str):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (session_id, blog_id, search_count)
            VALUES (%s, %s, 1)
            ON CONFLICT (session_id) DO UPDATE SET search_count = users.search_count + 1
        """, (session_id, blog_id))
        conn.commit()


def save_posts(blog_id: str, posts: list):
    with get_db() as conn:
        cur = conn.cursor()
        cur.executemany("""
            INSERT INTO posts (blog_id, title, url, date)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (blog_id, url) DO UPDATE SET
                title = EXCLUDED.title,
                date  = EXCLUDED.date
        """, [(blog_id, p["title"], p["url"], p.get("date", "")) for p in posts])
        # 유저가 삭제한 글은 DB에서도 제거 (추천 정확도 유지)
        if posts:
            urls = [p["url"] for p in posts]
            cur.execute(
                "DELETE FROM posts WHERE blog_id = %s AND url != ALL(%s)",
                (blog_id, urls)
            )
        cur.execute("""
            INSERT INTO blogs (blog_id, post_count, indexed_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (blog_id) DO UPDATE SET
                post_count = EXCLUDED.post_count,
                indexed_at = EXCLUDED.indexed_at
        """, (blog_id, len(posts)))
        conn.commit()


def get_latest_by_keyword(blog_id: str, keyword: str, n: int) -> list:
    # LIKE 와일드카드 이스케이프 (%, _ 를 리터럴로 처리)
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT title, url, date FROM posts WHERE blog_id = %s AND LOWER(title) LIKE LOWER(%s) ESCAPE '\\'",
            (blog_id, f"%{escaped}%")
        )
        rows = cur.fetchall()
    result = [{"title": r["title"], "url": r["url"], "date": r["date"] or "", "score": 80} for r in rows]
    def logno(p):
        part = p["url"].rsplit("/", 1)[-1]
        return int(part) if part.isdigit() else 0
    result.sort(key=logno, reverse=True)
    return result[:n]


def get_posts(blog_id: str) -> list:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT title, url, date FROM posts WHERE blog_id = %s ORDER BY id DESC", (blog_id,))
        rows = cur.fetchall()
    return [{"title": r["title"], "url": r["url"], "date": r["date"] or ""} for r in rows]


def create_order(order_id: str, session_id: str, plan: str, amount: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO payments (order_id, session_id, plan, amount)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (order_id) DO NOTHING
        """, (order_id, session_id, plan, amount))
        conn.commit()


def confirm_payment(order_id: str, payment_key: str):
    """결제 승인 처리: payments 업데이트 + 해당 유저 plan 업그레이드 & search_count 리셋"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM payments WHERE order_id = %s", (order_id,))
        row = cur.fetchone()
        if not row:
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
        return dict(row)


def get_plan_info(session_id: str):
    """현재 플랜 + 사용량 조회"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT plan, search_count, links_copied FROM users WHERE session_id = %s", (session_id,))
        row = cur.fetchone()
    if not row:
        return {"plan": "free", "search_count": 0, "daily_limit": FREE_LIMIT, "links_copied": 0}
    plan = row["plan"] or "free"
    limit = get_limit(plan)
    return {"plan": plan, "search_count": row["search_count"], "daily_limit": limit, "links_copied": row["links_copied"] or 0}


def increment_links_copied(session_id: str):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET links_copied = COALESCE(links_copied, 0) + 1 WHERE session_id = %s",
            (session_id,)
        )
        conn.commit()


def get_blog(blog_id: str):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM blogs WHERE blog_id = %s", (blog_id,))
        return cur.fetchone()


def reset_monthly_if_due(session_id: str):
    """유료 플랜 30일 주기 검색 횟수 자동 리셋 (lazy 방식)."""
    from datetime import datetime, timedelta
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT plan, reset_at FROM users WHERE session_id = %s", (session_id,))
        row = cur.fetchone()
        if not row or row["plan"] == "free" or not row["reset_at"]:
            return
        if datetime.now() >= row["reset_at"] + timedelta(days=30):
            cur.execute(
                "UPDATE users SET search_count = 0, reset_at = NOW() WHERE session_id = %s",
                (session_id,)
            )
            conn.commit()


def cancel_subscription(session_id: str):
    """구독 해지: 플랜을 free로 즉시 전환 + 빌링키 삭제 (재청구 방지)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE users
               SET plan = 'free', search_count = 0,
                   billing_key = NULL, customer_key = NULL, next_billing_date = NULL
               WHERE session_id = %s""",
            (session_id,)
        )
        conn.commit()


MAX_BLOGS_PRO = 3

def add_user_blog(session_id: str, blog_id: str, max_blogs: int = 0) -> bool:
    """블로그 목록에 추가. max_blogs > 0이면 한도 초과 시 False 반환."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM user_blogs WHERE session_id = %s AND blog_id = %s", (session_id, blog_id))
        if cur.fetchone():
            return True
        if max_blogs > 0:
            cur.execute("SELECT COUNT(*) AS cnt FROM user_blogs WHERE session_id = %s", (session_id,))
            if cur.fetchone()["cnt"] >= max_blogs:
                return False
        cur.execute(
            "INSERT INTO user_blogs (session_id, blog_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (session_id, blog_id)
        )
        conn.commit()
        return True


def save_billing_key(session_id: str, billing_key: str, customer_key: str, plan: str, amount: int):
    """빌링키 저장 + 플랜 활성화 + 다음 결제일 설정."""
    from datetime import datetime, timedelta
    with get_db() as conn:
        cur = conn.cursor()
        next_date = (datetime.now() + timedelta(days=30)).date()
        cur.execute("""
            UPDATE users
            SET billing_key = %s, customer_key = %s, plan = %s,
                search_count = 0, reset_at = NOW(), next_billing_date = %s
            WHERE session_id = %s
        """, (billing_key, customer_key, plan, next_date, session_id))
        conn.commit()


def get_users_due_for_billing():
    """오늘 결제일이 된 유료 유저 목록 반환."""
    from datetime import date as date_type
    with get_db() as conn:
        cur = conn.cursor()
        today = date_type.today()
        cur.execute("""
            SELECT session_id, billing_key, customer_key, plan
            FROM users
            WHERE plan != 'free'
              AND billing_key IS NOT NULL
              AND next_billing_date <= %s
        """, (today,))
        return [dict(r) for r in cur.fetchall()]


def update_next_billing_date(session_id: str):
    """결제 성공 후 다음 결제일 30일 연장 + 횟수 리셋."""
    from datetime import datetime, timedelta
    with get_db() as conn:
        cur = conn.cursor()
        next_date = (datetime.now() + timedelta(days=30)).date()
        cur.execute("""
            UPDATE users
            SET next_billing_date = %s, search_count = 0, reset_at = NOW()
            WHERE session_id = %s
        """, (next_date, session_id))
        conn.commit()


def downgrade_to_free(session_id: str):
    """결제 실패 시 free 플랜으로 다운그레이드."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users
            SET plan = 'free', billing_key = NULL, customer_key = NULL,
                next_billing_date = NULL
            WHERE session_id = %s
        """, (session_id,))
        conn.commit()


def save_email(session_id: str, email: str):
    """세션에 이메일 등록 (세션 복구용)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET email = %s WHERE session_id = %s", (email, session_id))
        conn.commit()


def get_session_by_email(email: str):
    """이메일로 유저 조회 (세션 복구용)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT session_id, plan FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
    return dict(row) if row else None


def activate_plan_by_customer_key(customer_key: str, plan: str):
    """웹훅 수신 시 customerKey로 유저 조회 후 플랜 활성화 (브라우저 닫힘 안전장치)."""
    from datetime import datetime, timedelta
    with get_db() as conn:
        cur = conn.cursor()
        next_date = (datetime.now() + timedelta(days=30)).date()
        cur.execute("""
            UPDATE users
            SET plan = %s, search_count = 0, reset_at = NOW(), next_billing_date = %s
            WHERE customer_key = %s AND plan = 'free'
        """, (plan, next_date, customer_key))
        conn.commit()


def save_customer_key_pending(session_id: str, customer_key: str):
    """빌링 주문 생성 시 customer_key 선저장 (브라우저 닫힘 시 웹훅 복구용)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET customer_key = %s WHERE session_id = %s", (customer_key, session_id))
        conn.commit()


def get_user_email(session_id: str) -> str | None:
    """유저 이메일 조회 (구독 갱신 실패 알림용)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT email FROM users WHERE session_id = %s", (session_id,))
        row = cur.fetchone()
    return row["email"] if row else None


def get_user_blogs(session_id: str) -> list:
    """세션이 등록한 블로그 목록 반환 (최신 등록 순)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT blog_id FROM user_blogs WHERE session_id = %s ORDER BY added_at DESC",
            (session_id,)
        )
        return [r["blog_id"] for r in cur.fetchall()]


def save_otp(email: str, code: str, expires_at: float):
    import time as _time
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM otp_store WHERE expires_at < %s", (_time.time(),))
        cur.execute("""
            INSERT INTO otp_store (email, code, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (email) DO UPDATE SET code = EXCLUDED.code, expires_at = EXCLUDED.expires_at
        """, (email, code, expires_at))
        conn.commit()


def get_otp(email: str) -> dict | None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT code, expires_at FROM otp_store WHERE email = %s", (email,))
        row = cur.fetchone()
    return dict(row) if row else None


def delete_otp(email: str):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM otp_store WHERE email = %s", (email,))
        conn.commit()


def session_exists(session_id: str) -> bool:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE session_id = %s", (session_id,))
        return cur.fetchone() is not None


def save_whale_relay(blog_id: str, posts: list):
    import json, time as _time
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO whale_relay (blog_id, posts_json, cached_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (blog_id) DO UPDATE SET posts_json = EXCLUDED.posts_json, cached_at = EXCLUDED.cached_at
        """, (blog_id, json.dumps(posts, ensure_ascii=False), _time.time()))
        conn.commit()


def get_whale_relay(blog_id: str, ttl: float = 3600.0) -> list | None:
    import json, time as _time
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT posts_json, cached_at FROM whale_relay WHERE blog_id = %s", (blog_id,))
        row = cur.fetchone()
    if not row or _time.time() - row["cached_at"] > ttl:
        return None
    return json.loads(row["posts_json"])
