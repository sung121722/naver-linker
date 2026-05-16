import requests
import json
import math
import re
import html
from urllib.parse import unquote_plus

API_URL = "https://blog.naver.com/PostTitleListAsync.nhn"
COUNT_PER_PAGE = 30
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def fetch_page(blog_id: str, page: int) -> dict:
    params = {
        "blogId": blog_id,
        "currentPage": page,
        "countPerPage": COUNT_PER_PAGE,
        "totalCount": 0,
    }
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    text = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', resp.text)
    return json.loads(text)


def fetch_all_posts(blog_id: str) -> list:
    first = fetch_page(blog_id, 1)
    total = int(first.get("totalCount", 0))
    if total == 0:
        return []

    pages = math.ceil(total / COUNT_PER_PAGE)
    all_pages = [first] + [fetch_page(blog_id, p) for p in range(2, pages + 1)]

    posts = []
    base_url = f"https://blog.naver.com/{blog_id}"
    for page_data in all_pages:
        for item in page_data.get("postList", []):
            title = html.unescape(unquote_plus(item.get("title", ""))).strip()
            posts.append({
                "title": title,
                "url": f"{base_url}/{item['logNo']}",
                "date": item.get("addDate", ""),
            })
    return posts
