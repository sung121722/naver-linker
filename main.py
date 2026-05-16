import uuid
import asyncio
import os
# force redeploy
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path

import db
import indexer
import matcher

app = FastAPI()
db.init_db()

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Models ──────────────────────────────────────────────

class IndexRequest(BaseModel):
    blog_id: str

class SearchRequest(BaseModel):
    blog_id: str
    keyword: str
    session_id: str
    top_n: int = 5


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
    existing = db.get_blog(blog_id)
    if existing:
        return {
            "ok": True,
            "blog_id": blog_id,
            "post_count": existing["post_count"],
            "cached": True,
        }

    loop = asyncio.get_running_loop()
    posts = await loop.run_in_executor(None, indexer.fetch_all_posts, blog_id)
    if not posts:
        raise HTTPException(status_code=404, detail="블로그를 찾을 수 없습니다. ID를 확인해주세요.")

    db.save_posts(blog_id, posts)
    return {"ok": True, "blog_id": blog_id, "post_count": len(posts), "cached": False}


@app.post("/api/search")
async def search(req: SearchRequest):
    blog_id = req.blog_id.strip().lower()
    session_id = req.session_id

    count, is_paid = db.get_search_count(session_id)
    if not is_paid and count >= db.FREE_LIMIT:
        raise HTTPException(
            status_code=402,
            detail=f"무료 검색 {db.FREE_LIMIT}회를 모두 사용했습니다. 구독 후 무제한 사용 가능합니다."
        )

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

    count_after = count + 1
    remaining = max(0, db.FREE_LIMIT - count_after) if not is_paid else None

    return {
        "ok": True,
        "results": results,
        "remaining": remaining,
        "is_paid": is_paid,
    }


@app.get("/api/debug")
def debug_env():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        masked = key[:8] + "..." + key[-4:]
    else:
        masked = "(NOT SET)"
    return {"ANTHROPIC_API_KEY": masked, "all_env_keys": [k for k in os.environ if "ANTHROPIC" in k.upper()]}


@app.get("/api/session")
def new_session():
    return {"session_id": str(uuid.uuid4())}


@app.get("/api/status/{blog_id}")
def status(blog_id: str):
    blog = db.get_blog(blog_id)
    if not blog:
        return {"indexed": False}
    return {"indexed": True, "post_count": blog["post_count"], "indexed_at": blog["indexed_at"]}
