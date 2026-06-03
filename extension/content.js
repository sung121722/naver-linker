// 에디터 iframe 찾기 + 링크 자동 삽입
let editorIframe = null;
let savedRange = null;

function findEditorIframe() {
  const iframes = document.querySelectorAll("iframe");
  for (const iframe of iframes) {
    try {
      const doc = iframe.contentDocument;
      if (doc?.querySelector('[contenteditable="true"]')) {
        return iframe;
      }
    } catch (_) {}
  }
  return null;
}

function attachSelectionListener(iframe) {
  try {
    iframe.contentDocument.addEventListener("selectionchange", () => {
      try {
        const sel = iframe.contentWindow.getSelection();
        if (sel && sel.rangeCount > 0) {
          savedRange = sel.getRangeAt(0).cloneRange();
        }
      } catch (_) {}
    });
  } catch (_) {}
}

// 에디터가 로드될 때까지 대기
function waitForEditor(attempt = 0) {
  const iframe = findEditorIframe();
  if (iframe) {
    editorIframe = iframe;
    attachSelectionListener(iframe);
    return;
  }
  if (attempt < 20) setTimeout(() => waitForEditor(attempt + 1), 500);
}

waitForEditor();

// popup.js → content.js: 링크 삽입 요청
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type !== "INSERT_LINK") return;

  try {
    const iframe = editorIframe || findEditorIframe();
    if (!iframe) {
      sendResponse({ ok: false, error: "에디터를 찾을 수 없습니다" });
      return true;
    }

    const iframeDoc = iframe.contentDocument;
    const iframeWin = iframe.contentWindow;

    // 에디터 포커스 복원
    iframeWin.focus();

    const sel = iframeWin.getSelection();

    // 저장된 커서 위치 복원
    if (savedRange) {
      sel.removeAllRanges();
      sel.addRange(savedRange);
    }

    if (!sel || sel.rangeCount === 0) {
      sendResponse({ ok: false, error: "에디터 커서 위치를 찾을 수 없습니다\n에디터를 한 번 클릭 후 다시 시도하세요" });
      return true;
    }

    // execCommand 방식 — Smart Editor 내부 상태와 호환
    const linkText = msg.selectedText || msg.title;
    const html = `<a href="${msg.url}" target="_blank">${linkText}</a>`;
    const inserted = iframeDoc.execCommand("insertHTML", false, html);

    if (inserted) {
      sendResponse({ ok: true });
    } else {
      sendResponse({ ok: false, error: "execCommand 실패 — 에디터를 클릭 후 다시 시도하세요" });
    }
  } catch (e) {
    sendResponse({ ok: false, error: e.message });
  }

  return true;
});
