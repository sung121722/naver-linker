// content.js — all_frames: true 로 에디터 iframe 내부에서 직접 실행됨
// top-level 페이지(외부 프레임)는 무시, editor iframe에서만 활성화

// iframe 내부가 아니면 종료 (top-level 페이지에서 실행 방지)
if (window === window.top) {
  // 아무것도 하지 않음
} else {
  let editableEl = null;
  let savedRange = null;
  let initialized = false;

  function saveRange() {
    try {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        savedRange = sel.getRangeAt(0).cloneRange();
      }
    } catch (_) {}
  }

  function isRangeValid(range) {
    try {
      return range.startContainer.isConnected && range.endContainer.isConnected;
    } catch (_) {
      return false;
    }
  }

  function setup(el) {
    if (initialized) return;
    initialized = true;
    editableEl = el;

    document.addEventListener("selectionchange", saveRange);
    document.addEventListener("mouseup", saveRange);
    document.addEventListener("keyup", saveRange);
  }

  function findAndSetup(attempt = 0) {
    const el = document.querySelector('[contenteditable="true"]');
    if (el) {
      setup(el);
      return;
    }
    if (attempt < 30) {
      setTimeout(() => findAndSetup(attempt + 1), 300);
    }
  }

  findAndSetup();

  // INSERT_LINK 메시지 수신 — popup.js → chrome.tabs.sendMessage → 여기서 처리
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type !== "INSERT_LINK") return;

    (async () => {
      try {
        const el = editableEl || document.querySelector('[contenteditable="true"]');
        if (!el) {
          sendResponse({ ok: false, error: "에디터를 찾을 수 없습니다. 글쓰기 페이지를 새로고침 해주세요." });
          return;
        }

        el.focus();
        await new Promise((r) => setTimeout(r, 60));

        const sel = window.getSelection();

        // 저장된 커서 위치 복원
        if (savedRange && isRangeValid(savedRange)) {
          try {
            sel.removeAllRanges();
            sel.addRange(savedRange);
          } catch (_) {}
        }

        // 커서가 아예 없으면 문서 끝으로 이동
        if (!sel || sel.rangeCount === 0) {
          const r = document.createRange();
          r.selectNodeContents(el);
          r.collapse(false);
          sel.removeAllRanges();
          sel.addRange(r);
        }

        const linkText = msg.title;
        let success = false;

        // Method 1: execCommand insertHTML (빠르고 안전)
        try {
          const html = `<a href="${msg.url}" target="_blank">${linkText}</a>`;
          success = document.execCommand("insertHTML", false, html);
        } catch (_) {}

        // Method 2: Range API 직접 삽입 (HTML 스트립 우회)
        if (!success) {
          try {
            const range = sel.getRangeAt(0);
            const link = document.createElement("a");
            link.href = msg.url;
            link.target = "_blank";
            link.textContent = linkText;

            range.deleteContents();
            range.insertNode(link);

            // 링크 뒤 공백 추가 후 커서 이동
            const space = document.createTextNode(" ");
            link.after(space);
            const newRange = document.createRange();
            newRange.setStartAfter(space);
            newRange.collapse(true);
            sel.removeAllRanges();
            sel.addRange(newRange);
            success = true;
          } catch (_) {}
        }

        if (success) {
          // 에디터가 변경을 감지하도록 이벤트 발화
          el.dispatchEvent(new Event("input", { bubbles: true }));
          sendResponse({ ok: true });
        } else {
          sendResponse({ ok: false, error: "삽입 실패. 에디터를 클릭해 커서를 먼저 위치시켜 주세요." });
        }
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();

    return true; // 비동기 응답 유지
  });
}
