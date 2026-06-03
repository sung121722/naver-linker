const NAVER_API = "https://blog.naver.com/PostTitleListAsync.nhn";
const SERVER_API = "https://naver-linker.onrender.com";
const COUNT_PER_PAGE = 30;

// 네이버 블로그 전체 글 목록 수집 (indexer.py 로직 → JS 포팅)
async function fetchAllPosts(blogId) {
  const firstPage = await fetchPage(blogId, 1);
  const total = parseInt(firstPage.totalCount || 0);
  if (total === 0) return [];

  const pages = Math.ceil(total / COUNT_PER_PAGE);
  const requests = [];
  for (let p = 2; p <= pages; p++) {
    requests.push(fetchPage(blogId, p));
  }
  const rest = await Promise.all(requests);
  const allPages = [firstPage, ...rest];

  const posts = [];
  const baseUrl = `https://blog.naver.com/${blogId}`;
  for (const pageData of allPages) {
    for (const item of pageData.postList || []) {
      posts.push({
        title: decodeTitle(item.title || ""),
        url: `${baseUrl}/${item.logNo}`,
        date: normalizeDate(item.addDate || ""),
      });
    }
  }
  return posts;
}

async function fetchPage(blogId, page) {
  const url = `${NAVER_API}?blogId=${encodeURIComponent(blogId)}&currentPage=${page}&countPerPage=${COUNT_PER_PAGE}&totalCount=0`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Naver API error: ${resp.status}`);
  const text = await resp.text();
  // 잘못된 이스케이프 시퀀스 정규화 (indexer.py의 re.sub 동일 처리)
  const fixed = text.replace(/\\(?!["\\/bfnrtu])/g, "\\\\");
  return JSON.parse(fixed);
}

function decodeTitle(title) {
  // Service Worker에는 document가 없으므로 직접 디코딩 (indexer.py: unquote_plus → html.unescape)
  let decoded = title;
  try {
    decoded = decodeURIComponent(title.replace(/\+/g, " "));
  } catch (_) {
    decoded = title.replace(/\+/g, " ");
  }
  return decoded
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)));
}

// "8분전", "어제" 같은 상대시간 → "최근" 변환, 절대 날짜는 그대로
function normalizeDate(raw) {
  if (!raw) return "";
  // YYYY.MM.DD 형식이면 그대로 반환
  if (/^\d{4}\.\d{2}\.\d{2}$/.test(raw)) return raw;
  // 상대시간(분전, 시간전, 어제 등)은 오늘 날짜로 대체
  const today = new Date().toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" })
    .replace(/\. /g, ".").replace(/\.$/, "");
  return today;
}

// 서버에 posts 저장 후 세션 발급
async function indexBlog(blogId, posts) {
  const resp = await fetch(`${SERVER_API}/api/index`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ blog_id: blogId, posts, source: "extension" }),
  });
  if (!resp.ok) throw new Error(`Server error: ${resp.status}`);
  return resp.json();
}

// 관련 글 검색
async function searchRelated(sessionId, blogId, keyword) {
  const resp = await fetch(`${SERVER_API}/api/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, blog_id: blogId, keyword }),
  });
  if (!resp.ok) throw new Error(`Server error: ${resp.status}`);
  return resp.json();
}

// 중복 글 감지
async function detectDuplicate(sessionId, blogId, keyword) {
  const resp = await fetch(`${SERVER_API}/api/duplicate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, blog_id: blogId, keyword }),
  });
  if (!resp.ok) throw new Error(`Server error: ${resp.status}`);
  return resp.json();
}

// popup.js ↔ background.js 메시지 라우터
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === "FETCH_POSTS") {
        const posts = await fetchAllPosts(msg.blogId);
        sendResponse({ ok: true, posts });
      } else if (msg.type === "INDEX_BLOG") {
        const result = await indexBlog(msg.blogId, msg.posts);
        sendResponse({ ok: true, ...result });
      } else if (msg.type === "SEARCH") {
        const result = await searchRelated(msg.sessionId, msg.blogId, msg.keyword);
        sendResponse({ ok: true, ...result });
      } else if (msg.type === "DUPLICATE") {
        const result = await detectDuplicate(msg.sessionId, msg.blogId, msg.keyword);
        sendResponse({ ok: true, ...result });
      } else {
        sendResponse({ ok: false, error: "Unknown message type" });
      }
    } catch (e) {
      sendResponse({ ok: false, error: e.message });
    }
  })();
  return true; // 비동기 응답 유지
});
