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

function saveRange(win) {
  try {
    const sel = win.getSelection();
    if (sel && sel.rangeCount > 0) {
      savedRange = sel.getRangeAt(0).cloneRange();
    }
  } catch (_) {}
}

function attachSelectionListener(iframe) {
  try {
    const doc = iframe.contentDocument;
    const win = iframe.contentWindow;
    doc.addEventListener("selectionchange", () => saveRange(win));
    doc.addEventListener("mouseup", () => saveRange(win));
    doc.addEventListener("keyup", () => saveRange(win));
  } catch (_) {}
}

function isRangeValid(range) {
  try {
    return range.startContainer.isConnected && range.endContainer.isConnected;
  } catch (_) {
    return false;
  }
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

      editableEl.focus();
      await new Promise((r) => setTimeout(r, 80));

      const sel = iframeWin.getSelection();

      // savedRange 복원 (유효한 경우만)
      if (savedRange && isRangeValid(savedRange)) {
        try {
          sel.removeAllRanges();
          sel.addRange(savedRange);
        } catch (_) {}
      }

      // 커서가 없으면 문서 끝으로 이동
      if (!sel || sel.rangeCount === 0) {
        const fallbackRange = iframeDoc.createRange();
        fallbackRange.selectNodeContents(editableEl);
        fallbackRange.collapse(false);
        sel.removeAllRanges();
        sel.addRange(fallbackRange);
      }

      const linkText = msg.title;
      let success = false;

      // Method 1: execCommand insertHTML (deprecated but still works in most browsers)
      try {
        const html = `<a href="${msg.url}" target="_blank">${linkText}</a>`;
        success = iframeDoc.execCommand("insertHTML", false, html);
      } catch (_) {}

      // Method 2: Range API — 직접 DOM 노드 삽입 (HTML 스트립 우회)
      if (!success) {
        try {
          const range = sel.getRangeAt(0);
          const link = iframeDoc.createElement("a");
          link.href = msg.url;
          link.target = "_blank";
          link.textContent = linkText;

          range.deleteContents();
          range.insertNode(link);

          // 링크 뒤에 공백 추가 후 커서 이동
          const space = iframeDoc.createTextNode(" ");
          link.after(space);
          const newRange = iframeDoc.createRange();
          newRange.setStartAfter(space);
          newRange.collapse(true);
          sel.removeAllRanges();
          sel.addRange(newRange);
          success = true;
        } catch (_) {}
      }

      if (success) {
        // 에디터가 변경 사항을 감지하도록 input 이벤트 발화
        editableEl.dispatchEvent(new Event("input", { bubbles: true }));
        sendResponse({ ok: true });
      } else {
        sendResponse({ ok: false, error: "링크 삽입에 실패했습니다. 에디터를 클릭해 커서를 위치시킨 후 다시 시도하세요." });
      }
    } catch (e) {
      sendResponse({ ok: false, error: e.message });
    }
  })();

  return true;
});
