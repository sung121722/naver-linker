// content.js — 커서 위치 저장 + 에디터 감지 시 내부링크 체크 버튼 주입
// all_frames: true → 에디터 iframe 안에서도 실행됨

(function () {
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
    const candidates = [
      document.querySelector(".se-title-input"),
      document.querySelector("input[placeholder*='제목']"),
      document.querySelector("textarea[placeholder*='제목']"),
      document.querySelector(".se-documentTitle-inputTitle"),
    ];
    for (const el of candidates) {
      if (!el) continue;
      const val = el.value || el.textContent || el.innerText || "";
      if (val.trim()) return val.trim();
    }
    return "";
  }

  function injectFloatingBtn() {
    if (document.getElementById("nlinker-float-btn")) return;

    // 에디터 환경인지 확인 (제목 입력창 존재 여부)
    const isEditor = !!(
      document.querySelector(".se-title-input") ||
      document.querySelector("input[placeholder*='제목']") ||
      document.querySelector(".se-documentTitle-inputTitle")
    );
    if (!isEditor) return;

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
      chrome.runtime.sendMessage({ type: "EDITOR_TITLE", keyword });
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
})();
