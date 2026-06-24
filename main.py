import uuid
import asyncio
import os
import re
import time
import base64
import httpx
from collections import defaultdict
from datetime import date as date_cls
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path

TOSS_SECRET_KEY    = os.environ.get("TOSS_SECRET_KEY", "")
TOSS_CLIENT_KEY    = os.environ.get("TOSS_CLIENT_KEY", "")
BASE_URL           = os.environ.get("BASE_URL", "https://naver-linker.onrender.com")
DEV_SECRET         = os.environ.get("DEV_SECRET", "")
GMAIL_USER         = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

PLAN_PRICES = {
    "light": 2900,
    "basic": 6900,
    "pro":   11900,
}
PLAN_NAMES = {
    "light": "라이트 (200회/월)",
    "basic": "베이직 (500회/월)",
    "pro":   "프로 (1,000회/월)",
}

_DATE_RE   = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
_YMD_RE    = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})\.?$")   # "2026.5.28"
_KO_MD_RE  = re.compile(r"^(\d{1,2})월\s*(\d{1,2})\.\s*$")       # "5월 28."
_MD_RE     = re.compile(r"^(\d{1,2})\.(\d{1,2})\.\s*$")           # "06.04."
_N_DAY_RE  = re.compile(r"^(\d+)일\s*전$")                        # "3일 전"
_N_WEEK_RE = re.compile(r"^(\d+)주(?:일)?\s*전$")                 # "2주 전" / "2주일 전"

def normalize_date_srv(raw: str) -> str:
    """YYYY.MM.DD 형식이 아닌 날짜를 정규화 (서버사이드 안전망)"""
    if not raw:
        return ""
    s = raw.strip()
    if _DATE_RE.match(s):
        return s
    today = date_cls.today()
    # "2026.5.28" — 제로패딩 없는 전체 날짜
    m = _YMD_RE.match(s)
    if m:
        return f"{m.group(1)}.{int(m.group(2)):02d}.{int(m.group(3)):02d}"
    # "5월 28." — 한국어 월 포맷
    m = _KO_MD_RE.match(s)
    if m:
        return f"{today.year}.{int(m.group(1)):02d}.{int(m.group(2)):02d}"
    # "06.04." — MM.DD. 포맷
    m = _MD_RE.match(s)
    if m:
        return f"{today.year}.{int(m.group(1)):02d}.{int(m.group(2)):02d}"
    # "어제"
    if "어제" in s:
        from datetime import timedelta
        return (today - timedelta(days=1)).strftime("%Y.%m.%d")
    # "그저께" / "그제"
    if "그저께" in s or "그제" in s:
        from datetime import timedelta
        return (today - timedelta(days=2)).strftime("%Y.%m.%d")
    # "N일 전"
    m = _N_DAY_RE.match(s)
    if m:
        from datetime import timedelta
        return (today - timedelta(days=int(m.group(1)))).strftime("%Y.%m.%d")
    # "N주 전" / "N주일 전"
    m = _N_WEEK_RE.match(s)
    if m:
        from datetime import timedelta
        return (today - timedelta(weeks=int(m.group(1)))).strftime("%Y.%m.%d")
    # 나머지 상대시간 (N분 전, N시간 전, 방금 등) → 오늘
    return today.strftime("%Y.%m.%d")

import db
import indexer
import matcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

app = FastAPI()
scheduler = AsyncIOScheduler()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # chrome-extension:// origin 포함 허용
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
db.init_db()

app.mount("/static", StaticFiles(directory="static"), name="static")


async def run_billing():
    """매일 결제일이 된 유료 유저 자동 청구."""
    users = db.get_users_due_for_billing()
    if not users:
        return

    credentials = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
    async with httpx.AsyncClient(timeout=10) as client:
        for user in users:
            session_id = user["session_id"]
            billing_key = user["billing_key"]
            customer_key = user["customer_key"]
            plan = user["plan"]
            amount = PLAN_PRICES.get(plan)
            if not amount:
                continue

            order_id = f"NL-renew-{session_id[:12]}-{int(time.time())}"
            try:
                resp = await client.post(
                    f"https://api.tosspayments.com/v1/billing/{billing_key}",
                    headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
                    json={
                        "customerKey": customer_key,
                        "amount": amount,
                        "orderId": order_id,
                        "orderName": PLAN_NAMES[plan],
                    },
                )
                if resp.status_code == 200:
                    db.update_next_billing_date(session_id)
                else:
                    db.downgrade_to_free(session_id)
                    email = db.get_user_email(session_id)
                    if email:
                        try:
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(
                                None, _send_email, email,
                                "[내부링크 도우미] 구독이 해지되었습니다",
                                "<p>안녕하세요.<br><br>카드 결제에 실패하여 구독이 해지되고 무료 플랜으로 전환되었습니다.<br>"
                                "카드 정보를 확인하신 후 다시 구독해주세요.</p>"
                            )
                        except Exception:
                            pass
            except Exception:
                db.downgrade_to_free(session_id)


@app.on_event("startup")
async def startup():
    # 매일 오전 9시(KST) = UTC 0시 실행
    scheduler.add_job(run_billing, "cron", hour=0, minute=0)
    scheduler.start()


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


# IP당 분당 60회 슬라이딩 윈도우 레이트 리밋
_rl_store: dict[str, list[float]] = defaultdict(list)
_RL_MAX = 60
_RL_WINDOW = 60.0

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    from fastapi.responses import JSONResponse
    if request.url.path.startswith("/api/"):
        skip_rl = ("/api/admin", "/api/ping", "/api/billing/webhook")
        if not any(request.url.path.startswith(p) for p in skip_rl):
            forwarded = request.headers.get("X-Forwarded-For")
            ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
            now = time.time()
            window_start = now - _RL_WINDOW
            _rl_store[ip] = [t for t in _rl_store[ip] if t > window_start]
            if not _rl_store[ip]:
                del _rl_store[ip]
            if len(_rl_store.get(ip, [])) >= _RL_MAX:
                return JSONResponse({"detail": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."}, status_code=429)
            _rl_store[ip].append(now)
    return await call_next(request)


@app.middleware("http")
async def dev_secret_guard(request, call_next):
    # 어드민 엔드포인트만 DEV_SECRET으로 보호 (서버 환경변수 전용)
    if request.url.path.startswith("/api/admin"):
        if DEV_SECRET and request.headers.get("X-Dev-Secret") != DEV_SECRET:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


# ── Models ──────────────────────────────────────────────

class PostItem(BaseModel):
    title: str
    url: str
    date: str = ""

class IndexRequest(BaseModel):
    blog_id: str
    force: bool = False
    posts: list[PostItem] = []   # extension이 직접 수집해서 보낼 때
    source: str = "web"          # "extension" | "web"
    session_id: str = ""         # 기존 세션 재사용 시 (멀티블로그)
    force_replace: bool = False  # non-pro 블로그 교체 시

class SearchRequest(BaseModel):
    blog_id: str
    keyword: str
    session_id: str
    top_n: int = 5
    sort: str = "relevance"

class DuplicateRequest(BaseModel):
    blog_id: str
    keyword: str
    session_id: str
    top_n: int = 10

class OrderRequest(BaseModel):
    session_id: str
    plan: str


# ── API ─────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def root():
    return Path("static/index.html").read_text(encoding="utf-8")


def parse_blog_id(raw: str) -> str:
    raw = raw.strip().rstrip("/")
    if "blog.naver.com/" in raw:
        raw = raw.split("blog.naver.com/")[-1].split("/")[0]
    return raw.lower()


@app.post("/api/index")
async def index_blog(req: IndexRequest, request: Request):
    blog_id = parse_blog_id(req.blog_id)
    ip = get_client_ip(request)

    # 기존 세션으로 플랜 확인 → 플랜별 IP 한도 결정
    if req.session_id:
        _, pre_plan = db.get_search_count(req.session_id)
    else:
        pre_plan = "free"
    ip_limit = db.MAX_BLOGS_PER_IP if pre_plan == "pro" else db.MAX_BLOGS_PER_IP_DEFAULT

    if not db.check_and_record_ip_registration(ip, blog_id, ip_limit):
        # force_replace: non-pro 유저가 기존 블로그를 새 블로그로 교체
        if req.force_replace and pre_plan != "pro":
            db.remove_ip_registration(ip)          # 기존 IP 슬롯 전체 초기화
            db.clear_user_blogs(req.session_id)    # 기존 user_blogs 초기화
            db.check_and_record_ip_registration(ip, blog_id, ip_limit)  # 새 블로그 등록
        else:
            raise HTTPException(
                status_code=429,
                detail=f"이 플랜은 하나의 IP에서 최대 {ip_limit}개 블로그까지 등록할 수 있습니다."
            )

    if req.source == "extension" and req.posts:
        # Extension 모드: 클라이언트가 수집한 posts를 그대로 저장
        posts = [p.model_dump() for p in req.posts]
        db.save_posts(blog_id, posts)
    else:
        # Web 모드: 서버에서 직접 크롤링 (기존 방식 유지)
        existing = db.get_blog(blog_id)
        if existing and not req.force:
            session_id = str(uuid.uuid4())
            db.ensure_user(session_id, blog_id)
            count, plan = db.get_search_count(session_id)
            return {
                "ok": True,
                "blog_id": blog_id,
                "post_count": existing["post_count"],
                "cached": True,
                "session_id": session_id,
                "plan": plan,
                "search_count": count,
                "daily_limit": db.get_limit(plan),
            }

        loop = asyncio.get_running_loop()
        posts = await loop.run_in_executor(None, indexer.fetch_all_posts, blog_id)
        if not posts:
            raise HTTPException(status_code=404, detail="블로그를 찾을 수 없습니다. ID를 확인해주세요.")
        db.save_posts(blog_id, posts)

    session_id = req.session_id if req.session_id else str(uuid.uuid4())
    db.ensure_user(session_id, blog_id)
    count, plan = db.get_search_count(session_id)
    max_blogs = db.MAX_BLOGS_PRO if plan == "pro" else 0
    if not db.add_user_blog(session_id, blog_id, max_blogs):
        raise HTTPException(status_code=429, detail=f"Pro 플랜은 최대 {db.MAX_BLOGS_PRO}개 블로그까지 등록할 수 있습니다.")
    return {
        "ok": True,
        "blog_id": blog_id,
        "post_count": len(posts),
        "cached": False,
        "session_id": session_id,
        "plan": plan,
        "search_count": count,
        "daily_limit": db.get_limit(plan),
    }


def get_client_ip(request: Request) -> str:
    # Render 등 프록시 환경에서 실제 IP 추출
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host


@app.post("/api/search")
async def search(req: SearchRequest, request: Request):
    blog_id = req.blog_id.strip().lower()
    session_id = req.session_id
    client_ip = get_client_ip(request)

    db.reset_monthly_if_due(session_id)
    count, plan = db.get_search_count(session_id)

    limit = db.get_limit(plan)

    if plan == "free":
        ip_count = db.get_ip_search_count(client_ip)
        if ip_count >= limit:
            raise HTTPException(status_code=402, detail="무료 체험이 끝났습니다.")
    else:
        if count >= limit:
            raise HTTPException(status_code=402, detail="이용 한도를 초과했습니다.")

    top_n = max(1, min(req.top_n, 20))

    if req.sort == "latest":
        results = db.get_latest_by_keyword(blog_id, req.keyword, top_n)
        if not results:
            raise HTTPException(status_code=404, detail="키워드와 일치하는 글이 없습니다.")
    else:
        posts = db.get_posts(blog_id)
        if not posts:
            raise HTTPException(status_code=404, detail="먼저 블로그를 등록해주세요.")
        loop = asyncio.get_running_loop()
        try:
            results = await loop.run_in_executor(None, matcher.find_related, posts, req.keyword, top_n)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"검색 오류: {str(e)}")

    db.increment_search(session_id, blog_id)
    if plan == "free":
        db.increment_ip_search(client_ip)
        remaining = max(0, limit - (ip_count + 1))
    else:
        remaining = max(0, limit - (count + 1))

    # 날짜 정규화 (DB에 남은 상대시간 "N분 전" 등 처리)
    for r in results:
        r["date"] = normalize_date_srv(r.get("date", "") or "")

    new_count = count + 1
    return {
        "ok": True,
        "results": results,
        "remaining": remaining,
        "plan": plan,
        "search_count": new_count,
        "daily_limit": limit,
    }


@app.post("/api/duplicate")
async def duplicate(req: DuplicateRequest, request: Request):
    blog_id = req.blog_id.strip().lower()
    session_id = req.session_id
    client_ip = get_client_ip(request)

    db.reset_monthly_if_due(session_id)
    count, plan = db.get_search_count(session_id)

    limit = db.get_limit(plan)

    if plan == "free":
        ip_count = db.get_ip_search_count(client_ip)
        if ip_count >= limit:
            raise HTTPException(status_code=402, detail="무료 체험이 끝났습니다.")
    else:
        if count >= limit:
            raise HTTPException(status_code=402, detail="이용 한도를 초과했습니다.")

    posts = db.get_posts(blog_id)
    if not posts:
        raise HTTPException(status_code=404, detail="먼저 블로그를 등록해주세요.")

    loop = asyncio.get_running_loop()
    try:
        top_n = max(1, min(req.top_n, 20))
        result = await loop.run_in_executor(
            None, matcher.find_duplicates, posts, req.keyword, top_n
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"분석 오류: {str(e)}")

    db.increment_search(session_id, blog_id)
    if plan == "free":
        db.increment_ip_search(client_ip)
        remaining = max(0, limit - (ip_count + 1))
    else:
        remaining = max(0, limit - (count + 1))

    # 날짜 정규화
    for p in result.get("similar_posts", []):
        p["date"] = normalize_date_srv(p.get("date", "") or "")

    new_count = count + 1
    return {"ok": True, **result, "remaining": remaining, "plan": plan, "search_count": new_count, "daily_limit": limit}


@app.get("/api/admin/set-plan")
def admin_set_plan(session_id: str, plan: str = "pro"):
    """테스트용: 특정 세션의 플랜을 강제 설정."""
    if plan not in ("free", "light", "basic", "pro"):
        raise HTTPException(status_code=400, detail="잘못된 플랜")
    with db.get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET plan = %s, search_count = 0, reset_at = NOW() WHERE session_id = %s",
            (plan, session_id)
        )
        conn.commit()
    return {"ok": True, "session_id": session_id, "plan": plan}


@app.get("/api/admin/reset-ip")
def reset_ip(request: Request):
    client_ip = get_client_ip(request)
    with db.get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM ip_searches WHERE ip = %s", (client_ip,))
        cur.execute("DELETE FROM ip_registrations WHERE ip = %s", (client_ip,))
        conn.commit()
    return {"ok": True, "reset_ip": client_ip}


@app.get("/api/admin/stats")
def admin_stats():
    with db.get_db() as conn:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) AS cnt FROM users")
        total_sessions = cur.fetchone()["cnt"]

        cur.execute("SELECT COALESCE(SUM(search_count), 0) AS cnt FROM users")
        total_searches = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM blogs")
        total_blogs = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM posts")
        total_posts = cur.fetchone()["cnt"]

        cur.execute("SELECT ip, search_count FROM ip_searches ORDER BY search_count DESC LIMIT 10")
        top_ips = cur.fetchall()

        cur.execute("SELECT blog_id, post_count, indexed_at FROM blogs ORDER BY indexed_at DESC LIMIT 10")
        top_blogs = cur.fetchall()

        cur.execute("SELECT session_id, search_count, plan, created_at FROM users ORDER BY search_count DESC LIMIT 10")
        top_users = cur.fetchall()

        cur.execute("SELECT plan, COUNT(*) AS cnt FROM users GROUP BY plan ORDER BY cnt DESC")
        plan_dist = cur.fetchall()

        cur.execute("""
            SELECT TO_CHAR(DATE_TRUNC('month', created_at), 'YYYY-MM') AS month, COUNT(*) AS cnt
            FROM users
            WHERE created_at IS NOT NULL
            GROUP BY 1 ORDER BY 1 DESC LIMIT 6
        """)
        monthly_new = cur.fetchall()

        cur.execute("""
            SELECT
                CASE
                    WHEN search_count = 0    THEN '0회 (미사용)'
                    WHEN search_count <= 3   THEN '1~3회'
                    WHEN search_count <= 10  THEN '4~10회'
                    WHEN search_count <= 30  THEN '11~30회'
                    ELSE '31회 이상'
                END AS 구간,
                COUNT(*) AS cnt
            FROM users
            GROUP BY 1
            ORDER BY MIN(search_count)
        """)
        retention = cur.fetchall()

    return {
        "summary": {
            "총_세션수": total_sessions,
            "총_검색횟수": total_searches,
            "등록_블로그수": total_blogs,
            "총_포스트수": total_posts,
        },
        "플랜별_유저수": [{"플랜": r["plan"] or "free", "유저수": r["cnt"]} for r in plan_dist],
        "월별_신규유저": [{"월": r["month"], "신규": r["cnt"]} for r in monthly_new],
        "이탈_시점": [{"구간": r["구간"], "유저수": r["cnt"]} for r in retention],
        "top_ip_사용자": [{"ip": r["ip"], "검색수": r["search_count"]} for r in top_ips],
        "최근_블로그": [{"blog_id": r["blog_id"], "글수": r["post_count"], "등록일": r["indexed_at"]} for r in top_blogs],
        "top_유저": [{"session": r["session_id"][:8]+"...", "검색수": r["search_count"], "플랜": r["plan"], "가입일": str(r["created_at"])} for r in top_users],
    }



@app.get("/api/session")
def new_session():
    return {"session_id": str(uuid.uuid4())}


@app.get("/api/ping")
def ping():
    """UptimeRobot 헬스체크 — DB 쿼리 포함하여 Supabase 비활성 정지 방지."""
    with db.get_db() as conn:
        conn.cursor().execute("SELECT 1")
    return {"ok": True}


def _send_email(to: str, subject: str, body: str):
    import smtplib
    from email.mime.text import MIMEText
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        return
    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = to
    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls()
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.sendmail(GMAIL_USER, to, msg.as_string())


class EmailRegisterRequest(BaseModel):
    session_id: str
    email: str

@app.post("/api/register-email")
def register_email(req: EmailRegisterRequest):
    """유료 플랜 세션에 이메일 등록 (세션 복구용)."""
    if not req.email or "@" not in req.email:
        raise HTTPException(status_code=400, detail="유효한 이메일을 입력해주세요.")
    db.save_email(req.session_id, req.email)
    return {"ok": True}


class RecoverRequest(BaseModel):
    email: str

@app.post("/api/recover-session")
def recover_session(req: RecoverRequest):
    """이메일로 세션 ID 복구 — 등록된 이메일로 발송."""
    user = db.get_session_by_email(req.email)
    if not user:
        raise HTTPException(status_code=404, detail="등록된 이메일을 찾을 수 없습니다.")
    session_id = user["session_id"]
    plan = user["plan"]
    plan_names = {"light": "라이트", "basic": "베이직", "pro": "프로"}
    plan_label = plan_names.get(plan, plan)
    body = f"""
    <div style="font-family:-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:32px 16px">
      <h2 style="color:#03C75A">🔗 네이버 내부링크 도우미</h2>
      <p>세션 ID 복구를 요청하셨습니다.</p>
      <div style="background:#f8f9fa;border-radius:8px;padding:16px;margin:20px 0">
        <p style="margin:0;font-size:13px;color:#868e96">현재 플랜: <strong>{plan_label}</strong></p>
        <p style="margin:8px 0 0;font-size:13px;color:#868e96">세션 ID:</p>
        <p style="margin:4px 0 0;font-size:15px;font-weight:700;word-break:break-all">{session_id}</p>
      </div>
      <p style="font-size:13px;color:#868e96">
        Chrome 익스텐션을 열고 블로그 등록 화면 하단의 <strong>세션 ID로 복구</strong> 버튼을 클릭한 뒤, 위 세션 ID를 붙여넣으세요.
      </p>
    </div>
    """
    try:
        _send_email(req.email, "[내부링크 도우미] 세션 ID 복구", body)
    except Exception:
        raise HTTPException(status_code=500, detail="이메일 발송에 실패했습니다. 관리자에게 문의해주세요.")
    return {"ok": True}


# ── Payment ──────────────────────────────────────────────

@app.get("/upgrade", response_class=HTMLResponse)
def upgrade_page():
    return Path("static/upgrade.html").read_text(encoding="utf-8")


@app.get("/api/plan/{session_id}")
def get_plan(session_id: str, request: Request):
    db.reset_monthly_if_due(session_id)
    info = db.get_plan_info(session_id)
    if info["plan"] == "free":
        client_ip = get_client_ip(request)
        info["search_count"] = db.get_ip_search_count(client_ip)
    return info


@app.get("/api/user-blogs/{session_id}")
def get_user_blogs(session_id: str):
    """Pro 드롭다운용: 이 세션이 등록한 블로그 목록 반환."""
    info = db.get_plan_info(session_id)
    if info["plan"] != "pro":
        raise HTTPException(status_code=403, detail="Pro 플랜 전용 기능입니다.")
    blogs = db.get_user_blogs(session_id)
    return {"blogs": blogs}


class UnregisterRequest(BaseModel):
    session_id: str
    blog_id: str

@app.delete("/api/user-blog")
def unregister_blog(req: UnregisterRequest, request: Request):
    """Pro 드롭다운 ✕ 버튼: user_blogs + ip_registrations에서 제거."""
    info = db.get_plan_info(req.session_id)
    if info["plan"] != "pro":
        raise HTTPException(status_code=403, detail="Pro 플랜 전용 기능입니다.")
    ip = get_client_ip(request)
    db.remove_user_blog(req.session_id, req.blog_id)
    db.remove_ip_registration(ip, req.blog_id)
    return {"ok": True}


class CancelRequest(BaseModel):
    session_id: str

@app.post("/api/cancel")
def cancel_plan(req: CancelRequest):
    """구독 해지: 플랜을 즉시 free로 전환."""
    info = db.get_plan_info(req.session_id)
    if info["plan"] == "free":
        raise HTTPException(status_code=400, detail="이미 무료 플랜입니다.")
    db.cancel_subscription(req.session_id)
    return {"ok": True, "plan": "free"}


@app.post("/api/payment/order")
def create_order(req: OrderRequest):
    if req.plan not in PLAN_PRICES:
        raise HTTPException(status_code=400, detail="잘못된 플랜")
    if not req.session_id:
        raise HTTPException(status_code=400, detail="session_id가 필요합니다")
    amount   = PLAN_PRICES[req.plan]
    order_id = f"NL-{req.plan}-{req.session_id[:12]}-{int(time.time())}"
    db.create_order(order_id, req.session_id, req.plan, amount)
    return {
        "order_id":   order_id,
        "amount":     amount,
        "client_key": TOSS_CLIENT_KEY,
        "order_name": PLAN_NAMES[req.plan],
    }


@app.get("/api/payment/success", response_class=HTMLResponse)
async def payment_success(paymentKey: str, orderId: str, amount: int):
    # 1. Toss API 승인
    credentials = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://api.tosspayments.com/v1/payments/confirm",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
            },
            json={"paymentKey": paymentKey, "orderId": orderId, "amount": amount},
        )
    if resp.status_code != 200:
        err = resp.json().get("message", "결제 승인 실패")
        raise HTTPException(status_code=400, detail=err)

    # 2. DB 업데이트
    result = db.confirm_payment(orderId, paymentKey)
    if not result:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")

    plan_name = PLAN_NAMES.get(result["plan"], result["plan"])
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>결제 완료</title>
<style>
  body{{font-family:-apple-system,'Noto Sans KR',sans-serif;display:flex;align-items:center;
        justify-content:center;min-height:100vh;margin:0;background:#f8f9fa}}
  .card{{background:white;border-radius:16px;padding:40px 32px;text-align:center;
         box-shadow:0 4px 20px rgba(0,0,0,0.1);max-width:360px;width:90%}}
  .icon{{font-size:48px;margin-bottom:16px}}
  h2{{color:#212529;margin-bottom:8px}}
  p{{color:#868e96;font-size:14px;line-height:1.6;margin:0 0 24px}}
  .plan-badge{{display:inline-block;background:#e6f9ee;color:#087f3d;
               font-weight:700;padding:6px 16px;border-radius:20px;margin-bottom:20px}}
  .guide{{background:#f8f9fa;border-radius:10px;padding:14px;font-size:13px;
          color:#495057;text-align:left;margin-bottom:20px}}
  .guide li{{margin-bottom:4px}}
  button{{background:#03C75A;color:white;border:none;border-radius:8px;
          padding:12px 28px;font-size:14px;font-weight:700;cursor:pointer;width:100%}}
</style></head><body>
<div class="card">
  <div class="icon">🎉</div>
  <h2>결제 완료!</h2>
  <div class="plan-badge">{plan_name} 플랜</div>
  <p>결제가 성공적으로 처리되었습니다.<br>Extension을 새로고침하면 바로 사용할 수 있어요.</p>
  <div class="guide">
    <ol>
      <li>Chrome 주소창에 <b>chrome://extensions</b> 입력</li>
      <li>네이버 내부링크 도우미 → <b>↺ 새로고침</b></li>
      <li>Extension 아이콘 클릭 → 업그레이드된 플랜 확인</li>
    </ol>
  </div>
  <button onclick="window.close()">탭 닫기</button>
</div></body></html>"""


@app.get("/api/payment/fail", response_class=HTMLResponse)
def payment_fail(code: str = "", message: str = ""):
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>결제 실패</title>
<style>
  body{{font-family:-apple-system,'Noto Sans KR',sans-serif;display:flex;align-items:center;
        justify-content:center;min-height:100vh;margin:0;background:#f8f9fa}}
  .card{{background:white;border-radius:16px;padding:40px 32px;text-align:center;
         box-shadow:0 4px 20px rgba(0,0,0,0.1);max-width:360px;width:90%}}
  .icon{{font-size:48px;margin-bottom:16px}}
  h2{{color:#c0392b;margin-bottom:8px}}
  p{{color:#868e96;font-size:14px;margin:0 0 24px}}
  .err{{background:#fff0f0;border-radius:8px;padding:10px 14px;
        font-size:13px;color:#c0392b;margin-bottom:20px}}
  button{{background:#6c757d;color:white;border:none;border-radius:8px;
          padding:12px 28px;font-size:14px;font-weight:700;cursor:pointer;width:100%}}
</style></head><body>
<div class="card">
  <div class="icon">😢</div>
  <h2>결제 실패</h2>
  <div class="err">{message or "결제가 취소되었거나 오류가 발생했습니다."}</div>
  <p>다시 시도하거나 다른 카드를 사용해보세요.</p>
  <button onclick="history.back()">뒤로 가기</button>
</div></body></html>"""


class BillingOrderRequest(BaseModel):
    session_id: str
    plan: str

@app.post("/api/billing/order")
def create_billing_order(req: BillingOrderRequest):
    """빌링키 발급용 주문 생성 — customer_key 반환."""
    if req.plan not in PLAN_PRICES:
        raise HTTPException(status_code=400, detail="잘못된 플랜")
    if not req.session_id:
        raise HTTPException(status_code=400, detail="session_id가 필요합니다")
    customer_key = str(uuid.uuid4())
    db.save_customer_key_pending(req.session_id, customer_key)
    return {
        "customer_key": customer_key,
        "client_key": TOSS_CLIENT_KEY,
    }


@app.get("/api/billing/success", response_class=HTMLResponse)
async def billing_success(authKey: str, customerKey: str, session_id: str = "", plan: str = ""):
    """토스 빌링키 발급 콜백 → billingKey 저장 + 첫 결제 실행."""
    if not session_id or plan not in PLAN_PRICES:
        raise HTTPException(status_code=400, detail="잘못된 요청입니다")

    amount = PLAN_PRICES[plan]
    credentials = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()

    async with httpx.AsyncClient(timeout=10) as client:
        # 1단계: authKey → billingKey 발급
        auth_resp = await client.post(
            f"https://api.tosspayments.com/v1/billing/authorizations/{authKey}",
            headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
            json={"customerKey": customerKey},
        )
    if auth_resp.status_code != 200:
        err = auth_resp.json().get("message", "빌링키 발급 실패")
        raise HTTPException(status_code=400, detail=err)

    billing_key = auth_resp.json()["billingKey"]

    # 2단계: 첫 결제 실행
    order_id = f"NL-sub-{session_id[:12]}-{int(time.time())}"
    async with httpx.AsyncClient(timeout=10) as client:
        charge_resp = await client.post(
            f"https://api.tosspayments.com/v1/billing/{billing_key}",
            headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
            json={
                "customerKey": customerKey,
                "amount": amount,
                "orderId": order_id,
                "orderName": PLAN_NAMES[plan],
            },
        )
    if charge_resp.status_code != 200:
        err = charge_resp.json().get("message", "첫 결제 실패")
        raise HTTPException(status_code=400, detail=err)

    # 3단계: DB 저장 (빌링키 + 플랜 활성화 + 다음 결제일)
    db.save_billing_key(session_id, billing_key, customerKey, plan, amount)

    plan_name = PLAN_NAMES[plan]
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>결제 완료</title>
<style>
  body{{font-family:-apple-system,'Noto Sans KR',sans-serif;display:flex;align-items:center;
        justify-content:center;min-height:100vh;margin:0;background:#f8f9fa}}
  .card{{background:white;border-radius:16px;padding:40px 32px;text-align:center;
         box-shadow:0 4px 20px rgba(0,0,0,0.1);max-width:360px;width:90%}}
  .icon{{font-size:48px;margin-bottom:16px}}
  h2{{color:#212529;margin-bottom:8px}}
  p{{color:#868e96;font-size:14px;line-height:1.6;margin:0 0 24px}}
  .plan-badge{{display:inline-block;background:#e6f9ee;color:#087f3d;
               font-weight:700;padding:6px 16px;border-radius:20px;margin-bottom:20px}}
  .guide{{background:#f8f9fa;border-radius:10px;padding:14px;font-size:13px;
          color:#495057;text-align:left;margin-bottom:20px}}
  .guide li{{margin-bottom:4px}}
  button{{background:#03C75A;color:white;border:none;border-radius:8px;
          padding:12px 28px;font-size:14px;font-weight:700;cursor:pointer;width:100%}}
  .email-box{{margin-top:16px;background:#f0faf5;border-radius:10px;padding:14px;text-align:left}}
  .email-box p{{font-size:12px;color:#495057;margin:0 0 8px}}
  .email-row{{display:flex;gap:6px}}
  .email-row input{{flex:1;border:1px solid #dee2e6;border-radius:6px;padding:8px 10px;font-size:13px}}
  .email-row button{{background:#03C75A;color:white;border:none;border-radius:6px;
                     padding:8px 12px;font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap;width:auto}}
  .email-msg{{font-size:12px;margin-top:6px;display:none}}
</style></head><body>
<div class="card">
  <div class="icon">🎉</div>
  <h2>구독 시작!</h2>
  <div class="plan-badge">{plan_name}</div>
  <p>결제가 완료되었습니다.<br>매월 자동으로 갱신됩니다.</p>
  <div class="guide">
    <ol>
      <li>Chrome 주소창에 <b>chrome://extensions</b> 입력</li>
      <li>네이버 내부링크 도우미 → <b>↺ 새로고침</b></li>
      <li>Extension 아이콘 클릭 → 업그레이드된 플랜 확인</li>
    </ol>
  </div>
  <div class="email-box">
    <p>⚠️ 브라우저 초기화 시 세션이 분실될 수 있습니다.<br>이메일을 등록하면 언제든 복구할 수 있습니다.</p>
    <div class="email-row">
      <input type="email" id="emailInput" placeholder="이메일 주소 입력" />
      <button onclick="registerEmail()">등록</button>
    </div>
    <div class="email-msg" id="emailMsg"></div>
  </div>
  <button onclick="window.close()" style="margin-top:16px">탭 닫기</button>
</div>
<script>
async function registerEmail() {{
  const email = document.getElementById('emailInput').value.trim();
  const msg = document.getElementById('emailMsg');
  if (!email) return;
  try {{
    const res = await fetch('/api/register-email', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{session_id: '{session_id}', email}})
    }});
    msg.style.display = 'block';
    if (res.ok) {{
      msg.style.color = '#087f3d';
      msg.textContent = '✅ 이메일이 등록되었습니다.';
    }} else {{
      msg.style.color = '#c0392b';
      msg.textContent = '등록에 실패했습니다. 다시 시도해주세요.';
    }}
  }} catch(e) {{
    msg.style.display = 'block';
    msg.style.color = '#c0392b';
    msg.textContent = '오류가 발생했습니다.';
  }}
}}
</script>
</body></html>"""


@app.get("/api/billing/fail", response_class=HTMLResponse)
def billing_fail(code: str = "", message: str = ""):
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>결제 실패</title>
<style>
  body{{font-family:-apple-system,'Noto Sans KR',sans-serif;display:flex;align-items:center;
        justify-content:center;min-height:100vh;margin:0;background:#f8f9fa}}
  .card{{background:white;border-radius:16px;padding:40px 32px;text-align:center;
         box-shadow:0 4px 20px rgba(0,0,0,0.1);max-width:360px;width:90%}}
  .icon{{font-size:48px;margin-bottom:16px}}
  h2{{color:#c0392b;margin-bottom:8px}}
  p{{color:#868e96;font-size:14px;margin:0 0 24px}}
  .err{{background:#fff0f0;border-radius:8px;padding:10px 14px;
        font-size:13px;color:#c0392b;margin-bottom:20px}}
  button{{background:#6c757d;color:white;border:none;border-radius:8px;
          padding:12px 28px;font-size:14px;font-weight:700;cursor:pointer;width:100%}}
</style></head><body>
<div class="card">
  <div class="icon">😢</div>
  <h2>결제 실패</h2>
  <div class="err">{message or "결제가 취소되었거나 오류가 발생했습니다."}</div>
  <p>다시 시도하거나 다른 카드를 사용해보세요.</p>
  <button onclick="history.back()">뒤로 가기</button>
</div></body></html>"""


@app.post("/api/billing/webhook")
async def billing_webhook(request: Request):
    """토스페이먼츠 웹훅 — 결제 완료 시 플랜 활성화 안전장치."""
    auth_header = request.headers.get("Authorization", "")
    expected = "Basic " + base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
    if auth_header != expected:
        return {"ok": True}
    payload = await request.json()
    event_type = payload.get("eventType", "")

    if event_type == "PAYMENT_STATUS_CHANGED":
        data = payload.get("data", {})
        if data.get("status") == "DONE":
            customer_key = data.get("customerKey", "")
            order_name = data.get("orderName", "")
            plan_map = {v: k for k, v in PLAN_NAMES.items()}
            resolved_plan = plan_map.get(order_name)
            if customer_key and resolved_plan:
                db.activate_plan_by_customer_key(customer_key, resolved_plan)

    return {"ok": True}


class TrackCopyRequest(BaseModel):
    session_id: str

@app.post("/api/track-copy")
def track_copy(req: TrackCopyRequest):
    if req.session_id:
        db.increment_links_copied(req.session_id)
    return {"ok": True}


@app.get("/api/status/{blog_id}")
def status(blog_id: str):
    blog = db.get_blog(blog_id)
    if not blog:
        return {"indexed": False}
    return {"indexed": True, "post_count": blog["post_count"], "indexed_at": blog["indexed_at"]}
