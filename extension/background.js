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

// 날짜 문자열 → YYYY.MM.DD 정규화
// Naver API 반환 형식: "2026.05.28" / "2026.5.28" / "5월 28." / "06.04." / "어제" / "4분 전" 등
function normalizeDate(raw) {
  if (!raw) return "";
  const s = raw.trim();

  // 1. YYYY.MM.DD (완전 정규화됨)
  if (/^\d{4}\.\d{2}\.\d{2}$/.test(s)) return s;

  const today = new Date();
  const year  = today.getFullYear();

  // 2. YYYY.M.D / YYYY.MM.D / YYYY.M.DD (제로패딩 없는 전체 날짜)
  const ymdMatch = s.match(/^(\d{4})\.(\d{1,2})\.(\d{1,2})\.?$/);
  if (ymdMatch) {
    const mm = String(ymdMatch[2]).padStart(2, "0");
    const dd = String(ymdMatch[3]).padStart(2, "0");
    return `${ymdMatch[1]}.${mm}.${dd}`;
  }

  // 3. "5월 28." / "12월 3." (한국어 월 포맷)
  const koMatch = s.match(/^(\d{1,2})월\s*(\d{1,2})\.\s*$/);
  if (koMatch) {
    const mm = String(koMatch[1]).padStart(2, "0");
    const dd = String(koMatch[2]).padStart(2, "0");
    return `${year}.${mm}.${dd}`;
  }

  // 4. "06.04." / "6.4." (MM.DD. 포맷, 같은 해)
  const mdMatch = s.match(/^(\d{1,2})\.(\d{1,2})\.\s*$/);
  if (mdMatch) {
    const mm = String(mdMatch[1]).padStart(2, "0");
    const dd = String(mdMatch[2]).padStart(2, "0");
    return `${year}.${mm}.${dd}`;
  }

  // 5. "어제"
  if (s.includes("어제")) {
    const d = new Date(today);
    d.setDate(d.getDate() - 1);
    return fmt(d);
  }

  // 6. "그저께" / "그제"
  if (s.includes("그저께") || s.includes("그제")) {
    const d = new Date(today);
    d.setDate(d.getDate() - 2);
    return fmt(d);
  }

  // 7. 나머지 상대시간 (N분 전, N시간 전, 방금 등) → 오늘
  return fmt(today);
}

function fmt(d) {
  const yyyy = d.getFullYear();
  const mm   = String(d.getMonth() + 1).padStart(2, "0");
  const dd   = String(d.getDate()).padStart(2, "0");
  return `${yyyy}.${mm}.${dd}`;
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
async function searchRelated(sessionId, blogId, keyword, topN = 5) {
  const resp = await fetch(`${SERVER_API}/api/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, blog_id: blogId, keyword, top_n: topN }),
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

// 아이콘 클릭 → 사이드 패널 열기
chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ tabId: tab.id });
});

// content.js에서 텍스트 선택 이벤트 수신 → 자동 검색 → Side Panel에 전달
async function handleTextSelected(text) {
  const stored = await chrome.storage.local.get("naver_linker_state");
  const state = stored["naver_linker_state"];
  if (!state?.sessionId || !state?.blogId) return; // 블로그 미등록 시 무시

  try {
    const result = await searchRelated(state.sessionId, state.blogId, text);
    // Side Panel에 자동 추천 결과 브로드캐스트
    chrome.runtime.sendMessage({
      type: "AUTO_SUGGEST",
      keyword: text,
      results: result.results || [],
    }).catch(() => {}); // Side Panel 닫혀있으면 무시
  } catch (_) {}
}

// popup.js ↔ background.js 메시지 라우터
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === "TEXT_SELECTED") {
        handleTextSelected(msg.text);
        sendResponse({ ok: true });
      } else if (msg.type === "FETCH_POSTS") {
        const posts = await fetchAllPosts(msg.blogId);
        sendResponse({ ok: true, posts });
      } else if (msg.type === "INDEX_BLOG") {
        const result = await indexBlog(msg.blogId, msg.posts);
        sendResponse({ ok: true, ...result });
      } else if (msg.type === "SEARCH") {
        const result = await searchRelated(msg.sessionId, msg.blogId, msg.keyword, msg.topN);
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
