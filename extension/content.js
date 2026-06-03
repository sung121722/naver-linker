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

  (async () => {
    try {
      const iframe = editorIframe || findEditorIframe();
      if (!iframe) {
        sendResponse({ ok: false, error: "에디터를 찾을 수 없습니다" });
        return;
      }

      const iframeDoc = iframe.contentDocument;
      const iframeWin = iframe.contentWindow;
      const editableEl = iframeDoc.querySelector("[contenteditable='true']") || iframeDoc.body;

      // 포커스 복원 후 타이밍 대기
      editableEl.focus();
      await new Promise(r => setTimeout(r, 80));

      const sel = iframeWin.getSelection();

      // 커서 위치 복원
      if (savedRange) {
        sel.removeAllRanges();
        sel.addRange(savedRange);
      }

      if (!sel || sel.rangeCount === 0) {
        sendResponse({ ok: false, error: "에디터를 클릭해 커서를 위치시킨 후 다시 시도하세요" });
        return;
      }

      const linkText = msg.selectedText || msg.title;
      const html = `<a href="${msg.url}" target="_blank">${linkText}</a>`;

      // execCommand 우선 시도
      const inserted = iframeDoc.execCommand("insertHTML", false, html);

      if (!inserted) {
        // 폴백: paste 이벤트 (text/html만)
        const clipboardData = new DataTransfer();
        clipboardData.setData("text/html", html);
        editableEl.dispatchEvent(new ClipboardEvent("paste", {
          clipboardData,
          bubbles: true,
          cancelable: true,
        }));
      }

      sendResponse({ ok: true });
    } catch (e) {
      sendResponse({ ok: false, error: e.message });
    }
  })();

  return true;
});
