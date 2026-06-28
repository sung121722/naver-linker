// content.js — 커서 위치 저장 + 에디터 감지 시 내부링크 체크 버튼 주입
// all_frames: true → 에디터 iframe 안에서도 실행됨

(function () {
  const SERVER_API = "https://naver-linker.onrender.com";

  // ── 원격 셀렉터 설정 (네이버 HTML 구조 변경 시 CWS 재심사 없이 즉시 반영) ──
  let CONFIG = {
    titleSelectors: [
      ".se-title-input",
      ".se-documentTitle-inputTitle",
      "input[placeholder*='제목']",
      "textarea[placeholder*='제목']",
    ],
    editorDetectSelectors: [
      ".se-title-input",
      ".se-documentTitle-inputTitle",
      "input[placeholder*='제목']",
    ],
  };

  fetch(`${SERVER_API}/api/config`, { cache: "no-store" })
    .then((r) => r.json())
    .then((data) => { Object.assign(CONFIG, data); })
    .catch(() => {}); // 실패 시 기본값 유지

  // ── 커서 위치 저장 (all frames) ──────────────────────────
  const el = document.querySelector('[contenteditable="true"]');
  if (el) {
    function saveRange() {
      try {
        const sel = window.getSelection();
        if (sel && sel.rangeCount > 0) {
          window.__nLinkerRange = sel.getRangeAt(0).cloneRange();
        }
      } catch (_) {}
    }
    document.addEventListener("selectionchange", saveRange);
    document.addEventListener("mouseup",         saveRange);
    document.addEventListener("keyup",           saveRange);
  }

  // ── 에디터 판별 함수 (all frames에서 사용) ───────────────
  function isEditorPage() {
    const url = window.location.href;
    if (url.includes("blog.naver.com") && (
      url.includes("PostWrite") ||
      url.includes("Redirect=Write")
    )) return true;
    return CONFIG.editorDetectSelectors.some((s) => !!document.querySelector(s));
  }

  function getTitleFromEditor() {
    // 1. 알려진 셀렉터 먼저 시도
    for (const selector of CONFIG.titleSelectors) {
      const el = document.querySelector(selector);
      if (!el) continue;
      const val = el.value || el.textContent || el.innerText || "";
      if (val.trim()) return val.trim();
    }
    // 2. fallback: contenteditable 중 짧은 텍스트 (제목은 본문보다 짧음)
    const editables = document.querySelectorAll('[contenteditable="true"]');
    for (const el of editables) {
      const text = (el.textContent || el.innerText || "").trim();
      if (text && text.length < 100) return text;
    }
    return "";
  }

  // ── 자동검색 트리거 (all frames — 제목이 있는 iframe에서도 동작) ──
  // 네이버 SmartEditor ONE은 제목·본문이 외부 페이지 안의 iframe 안에 있음
  // → if (window !== window.top) return 이후에 두면 iframe에서 keyup을 못 잡음
  let _autoTimer = null;
  let _lastAutoKeyword = "";

  document.addEventListener("keyup", () => {
    if (!isEditorPage()) return;
    clearTimeout(_autoTimer);
    _autoTimer = setTimeout(() => {
      const keyword = getTitleFromEditor().slice(0, 50);
      if (!keyword || keyword === _lastAutoKeyword) return;
      _lastAutoKeyword = keyword;
      try { chrome.runtime.sendMessage({ type: "EDITOR_TITLE", keyword }).catch(() => {}); } catch (_) {}
    }, 2000);
  });

  // ── 이하 top frame 전용 ───────────────────────────────────
  if (window !== window.top) return;

  // ── FETCH_POSTS_PROXY: popup.js 요청 → 페이지 컨텍스트에서 Naver API 호출 ──
  // SW(서비스 워커)가 죽어도 동작 — 페이지 fetch는 SW와 무관
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type !== "FETCH_POSTS_PROXY") return;
    (async () => {
      try {
        const posts = await _proxyFetchAll(msg.blogId);
        sendResponse({ ok: true, posts });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  });

  async function _proxyFetchAll(blogId) {
    const PER = 30;
    const API = "https://blog.naver.com/PostTitleListAsync.nhn";
    const fetchPage = async (page) => {
      const url = `${API}?blogId=${encodeURIComponent(blogId)}&currentPage=${page}&countPerPage=${PER}&totalCount=0`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`Naver API ${r.status}`);
      return JSON.parse((await r.text()).replace(/\\(?!["\\/bfnrtu])/g, "\\\\"));
    };
    const first = await fetchPage(1);
    const total = parseInt(first.totalCount || 0);
    if (!total) return [];
    const rest = await Promise.all(
      Array.from({ length: Math.ceil(total / PER) - 1 }, (_, i) => fetchPage(i + 2))
    );
    const posts = [];
    const base = `https://blog.naver.com/${blogId}`;
    for (const pg of [first, ...rest]) {
      for (const item of pg.postList || []) {
        if (String(item.openType) === "0") continue;
        let t = item.title || "";
        try { t = decodeURIComponent(t.replace(/\+/g, " ")); } catch (_) { t = t.replace(/\+/g, " "); }
        t = t.replace(/&amp;/g,"&").replace(/&lt;/g,"<").replace(/&gt;/g,">")
             .replace(/&quot;/g,'"').replace(/&#39;/g,"'")
             .replace(/&#(\d+);/g, (_, c) => String.fromCharCode(+c));
        posts.push({ title: t, url: `${base}/${item.logNo}`, date: item.addDate || "" });
      }
    }
    return posts;
  }

  function injectFloatingBtn() {
    if (document.getElementById("nlinker-float-btn")) return;
    if (!isEditorPage()) return;

    const btn = document.createElement("button");
    btn.id = "nlinker-float-btn";
    btn.textContent = "🔗 내부링크 체크";
    btn.style.cssText = [
      "position:fixed", "bottom:28px", "right:28px", "z-index:2147483647",
      "background:#03C75A", "color:white", "border:none", "border-radius:24px",
      "padding:10px 18px", "font-size:13px", "font-weight:700", "cursor:pointer",
      "box-shadow:0 4px 16px rgba(3,199,90,0.35)",
      "font-family:-apple-system,'Apple SD Gothic Neo',sans-serif",
      "transition:background 0.15s",
    ].join(";");

    btn.addEventListener("mouseenter", () => { btn.style.background = "#02a84c"; });
    btn.addEventListener("mouseleave", () => { btn.style.background = "#03C75A"; });

    btn.addEventListener("click", () => {
      const keyword = getTitleFromEditor().slice(0, 50);
      if (keyword) {
        // 제목 감지 성공 시 키워드도 전송
        try { chrome.runtime.sendMessage({ type: "EDITOR_TITLE", keyword }).catch(() => {}); } catch (_) {}
      } else {
        // 제목 감지 실패해도 사이드패널 열기
        try { chrome.runtime.sendMessage({ type: "OPEN_SIDE_PANEL" }).catch(() => {}); } catch (_) {}
      }
      btn.textContent = "✅ 사이드 패널에서 확인";
      setTimeout(() => { btn.textContent = "🔗 내부링크 체크"; }, 2500);
    });

    document.body.appendChild(btn);
  }

  // 에디터는 동적으로 로딩되므로 주기적으로 확인
  const check = setInterval(() => {
    injectFloatingBtn();
    if (document.getElementById("nlinker-float-btn")) clearInterval(check);
  }, 1500);

  // ── 현재 페이지 블로그 ID 감지 → popup으로 전송 ──────────
  function detectBlogId() {
    try {
      const url = new URL(window.location.href);
      if (url.hostname !== "blog.naver.com") return;
      const param = url.searchParams.get("blogId");
      if (param) return param;
      const parts = url.pathname.split("/").filter(Boolean);
      if (parts.length >= 1 && !parts[0].includes(".")) return parts[0];
    } catch (_) {}
    return null;
  }

  const detectedBlogId = detectBlogId();
  if (detectedBlogId) {
    try { chrome.runtime.sendMessage({ type: "DETECTED_BLOG_ID", blogId: detectedBlogId }).catch(() => {}); } catch (_) {}
    // Whale 대비: 페이지 컨텍스트에서 글 목록 프리패치 → storage 캐시
    // popup.js가 SW 없이도 캐시에서 바로 읽을 수 있음
    _prefetchToStorage(detectedBlogId);
  }

  async function _prefetchToStorage(blogId) {
    const btn = document.getElementById("nlinker-float-btn");
    try {
      const posts = await _proxyFetchAll(blogId);
      if (btn) btn.textContent = `🔗 저장 중... (${posts.length}개)`;

      // 방법 1: 서버 릴레이 (Whale 전용 — chrome.storage 불필요)
      try {
        const r = await fetch(`${SERVER_API}/api/whale-relay`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ blogId, posts }),
        });
        if (r.ok) {
          if (btn) btn.textContent = `🔗 내부링크 체크 ✅ (${posts.length}개)`;
        }
      } catch (_) {}

      // 방법 2: chrome.storage 병행 저장 (Chrome 호환성 유지)
      try {
        chrome.storage.local.set({ naver_linker_posts_cache: { blogId, posts, cachedAt: Date.now() } });
      } catch (_) {}

    } catch (e) {
      if (btn) btn.textContent = `⚠️ 글 목록 로드 실패`;
    }
  }
})();
