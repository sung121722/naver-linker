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

  // ── 커서 위치 저장 ────────────────────────────────────
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

  // ── 에디터 감지 + 플로팅 버튼 주입 ──────────────────
  // top frame에서만 실행 (iframe 안에서는 중복 주입 방지)
  if (window !== window.top) return;

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

  function isEditorPage() {
    // URL 기반 판단 (셀렉터보다 안정적)
    const url = window.location.href;
    if (url.includes("blog.naver.com") && (url.includes("PostWrite") || url.includes("blogId"))) return true;
    // 셀렉터 fallback
    return CONFIG.editorDetectSelectors.some((s) => !!document.querySelector(s));
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
      if (!keyword) {
        btn.textContent = "✏️ 제목을 먼저 입력하세요";
        setTimeout(() => { btn.textContent = "🔗 내부링크 체크"; }, 2000);
        return;
      }
      chrome.runtime.sendMessage({ type: "EDITOR_TITLE", keyword }).catch(() => {});
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

  // ── 제목 자동 감지: document 전체 keyup → getTitleFromEditor() → 2초 debounce ──
  let _autoTimer = null;
  let _lastAutoKeyword = "";

  document.addEventListener("keyup", () => {
    if (!isEditorPage()) return;
    clearTimeout(_autoTimer);
    _autoTimer = setTimeout(() => {
      const keyword = getTitleFromEditor().slice(0, 50);
      if (!keyword || keyword === _lastAutoKeyword) return;
      _lastAutoKeyword = keyword;
      chrome.runtime.sendMessage({ type: "EDITOR_TITLE", keyword }).catch(() => {});
    }, 2000);
  });

  // ── 현재 페이지 블로그 ID 감지 → popup으로 전송 ──────
  function detectBlogId() {
    try {
      const url = new URL(window.location.href);
      if (url.hostname !== "blog.naver.com") return;
      // 글쓰기 에디터: ?blogId=xxx
      const param = url.searchParams.get("blogId");
      if (param) return param;
      // 블로그 페이지: /BLOGID/postNo
      const parts = url.pathname.split("/").filter(Boolean);
      if (parts.length >= 1 && !parts[0].includes(".")) return parts[0];
    } catch (_) {}
    return null;
  }

  const detectedBlogId = detectBlogId();
  if (detectedBlogId) {
    chrome.runtime.sendMessage({ type: "DETECTED_BLOG_ID", blogId: detectedBlogId }).catch(() => {});
  }
})();
