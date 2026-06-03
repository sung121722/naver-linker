import uuid
import asyncio
import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path

import db
import indexer
import matcher

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # chrome-extension:// origin 포함 허용
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
db.init_db()

app.mount("/static", StaticFiles(directory="static"), name="static")


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

class SearchRequest(BaseModel):
    blog_id: str
    keyword: str
    session_id: str
    top_n: int = 5

class DuplicateRequest(BaseModel):
    blog_id: str
    keyword: str
    session_id: str
    top_n: int = 10


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
async def index_blog(req: IndexRequest):
    blog_id = parse_blog_id(req.blog_id)

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

    session_id = str(uuid.uuid4())
    db.ensure_user(session_id, blog_id)
    count, plan = db.get_search_count(session_id)
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

    count, plan = db.get_search_count(session_id)
    limit = db.get_limit(plan)

    if plan == "free":
        # 무료 플랜: IP 기반 일일 제한만 체크 (매일 초기화)
        ip_count = db.get_ip_search_count(client_ip)
        if ip_count >= limit:
            raise HTTPException(status_code=402, detail="무료 체험이 끝났습니다.")
    else:
        # 유료 플랜: 세션 기반 누적 횟수 체크
        if count >= limit:
            raise HTTPException(status_code=402, detail="이용 한도를 초과했습니다.")

    posts = db.get_posts(blog_id)
    if not posts:
        raise HTTPException(status_code=404, detail="먼저 블로그를 등록해주세요.")

    loop = asyncio.get_running_loop()
    top_n = max(1, min(req.top_n, 20))
    try:
        results = await loop.run_in_executor(None, matcher.find_related, posts, req.keyword, top_n)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"검색 오류: {str(e)}")

    db.increment_search(session_id, blog_id)
    if plan == "free":
        db.increment_ip_search(client_ip)
        remaining = max(0, limit - (ip_count + 1))  # IP 일일 카운트 기준
    else:
        remaining = max(0, limit - (count + 1))  # 유료: 세션 누적 기준

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

    new_count = count + 1
    return {"ok": True, **result, "remaining": remaining, "plan": plan, "search_count": new_count, "daily_limit": limit}


@app.get("/api/admin/stats")
def admin_stats():
    conn = db.get_conn()
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

    conn.close()

    return {
        "summary": {
            "총_세션수": total_sessions,
            "총_검색횟수": total_searches,
            "등록_블로그수": total_blogs,
            "총_포스트수": total_posts,
        },
        "top_ip_사용자": [{"ip": r["ip"], "검색수": r["search_count"]} for r in top_ips],
        "최근_블로그": [{"blog_id": r["blog_id"], "글수": r["post_count"], "등록일": r["indexed_at"]} for r in top_blogs],
        "top_유저": [{"session": r["session_id"][:8]+"...", "검색수": r["search_count"], "플랜": r["plan"], "가입일": str(r["created_at"])} for r in top_users],
    }


@app.get("/api/debug")
def debug_env():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    masked = (key[:8] + "..." + key[-4:]) if key else "(NOT SET)"
    # 모든 env 키 이름 노출 (값 제외)
    all_keys = sorted(os.environ.keys())
    return {
        "ANTHROPIC_API_KEY": masked,
        "all_env_keys": all_keys,
        "total_vars": len(all_keys),
    }


@app.get("/api/session")
def new_session():
    return {"session_id": str(uuid.uuid4())}


@app.get("/api/status/{blog_id}")
def status(blog_id: str):
    blog = db.get_blog(blog_id)
    if not blog:
        return {"indexed": False}
    return {"indexed": True, "post_count": blog["post_count"], "indexed_at": blog["indexed_at"]}
