// content.js — 커서 위치만 window.__nLinkerRange에 저장
// 삽입 로직은 popup.js의 executeScript가 직접 처리
// all_frames: true → 에디터 iframe 안에서도 실행됨

(function () {
  const el = document.querySelector('[contenteditable="true"]');
  if (!el) return;

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
})();
