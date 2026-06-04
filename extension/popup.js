// ── State ────────────────────────────────────────────
const STORAGE_KEY = "naver_linker_state";

let state = {
  blogId:     "",
  sessionId:  "",
  postCount:  0,
  plan:       "free",
  searchCount: 0,
  dailyLimit:  5,
};

// ── DOM refs ─────────────────────────────────────────
const blogIdInput  = document.getElementById("blogIdInput");
const indexBtn     = document.getElementById("indexBtn");
const reindexBtn   = document.getElementById("reindexBtn");
const progressWrap = document.getElementById("progressWrap");
const progressFill = document.getElementById("progressFill");
const progressLabel= document.getElementById("progressLabel");
const blogCard     = document.getElementById("blogCard");
const blogCardId   = document.getElementById("blogCardId");
const blogCardMeta = document.getElementById("blogCardMeta");
const blogStatus   = document.getElementById("blogStatus");
const featureSection = document.getElementById("featureSection");

const planBadge    = document.getElementById("planBadge");
const planUsageText= document.getElementById("planUsageText");
const usedCount    = document.getElementById("usedCount");
const limitCount   = document.getElementById("limitCount");
const gaugeFill    = document.getElementById("gaugeFill");
const gaugeLabel   = document.getElementById("gaugeLabel");
const upgradeBtn   = document.getElementById("upgradeBtn");

const searchKeyword= document.getElementById("searchKeyword");
const searchBtn    = document.getElementById("searchBtn");
const searchResults= document.getElementById("searchResults");
const dupKeyword   = document.getElementById("dupKeyword");
const dupBtn       = document.getElementById("dupBtn");
const dupResults   = document.getElementById("dupResults");
const copyToast    = document.getElementById("copyToast");

const SERVER_URL  = "https://naver-linker.onrender.com";
const DEV_SECRET  = "nlinker-test-2026";
const AUTH_HEADER = { "Content-Type": "application/json", "X-Dev-Secret": DEV_SECRET };

// ── Progress bar ──────────────────────────────────────
let _progressTimer = null;

function startProgress() {
  let pct = 0;
  progressWrap.classList.remove("hidden");
  progressFill.style.width = "0%";
  progressLabel.textContent = "수집 준비 중...";

  _progressTimer = setInterval(() => {
    if (pct < 30)      { pct += 4;   progressLabel.textContent = `글 목록 수집 중... (${pct}%)`; }
    else if (pct < 65) { pct += 1.5; progressLabel.textContent = `서버에 저장 중... (${Math.round(pct)}%)`; }
    else if (pct < 88) { pct += 0.6; progressLabel.textContent = `마무리 중... (${Math.round(pct)}%)`; }
    progressFill.style.width = pct + "%";
  }, 180);
}

function finishProgress(success) {
  clearInterval(_progressTimer);
  progressFill.style.width = "100%";
  progressLabel.textContent = success ? "✅ 수집 완료!" : "❌ 수집 실패";
  setTimeout(() => progressWrap.classList.add("hidden"), 1200);
}

// ── Blog profile card ─────────────────────────────────
function showBlogCard(blogId, postCount) {
  blogCardId.textContent  = blogId;
  blogCardMeta.textContent = `글 ${postCount.toLocaleString()}개 등록됨`;
  blogCard.classList.remove("hidden");
}

function hideBlogCard() {
  blogCard.classList.add("hidden");
}

// ── Status message ────────────────────────────────────
function showStatus(msg, type) {
  blogStatus.textContent = msg;
  blogStatus.className   = `status-msg ${type}`;
  blogStatus.classList.remove("hidden");
}

function hideStatus() {
  blogStatus.classList.add("hidden");
}

// ── Usage gauge ───────────────────────────────────────
function updateGauge(used, limit) {
  const remaining = Math.max(0, limit - used);
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;

  usedCount.textContent  = used;
  limitCount.textContent = limit;
  gaugeFill.style.width  = pct + "%";

  if (remaining <= 1)      gaugeFill.style.backgroundColor = "#e53e3e";
  else if (remaining <= 3) gaugeFill.style.backgroundColor = "#dd6b20";
  else                     gaugeFill.style.backgroundColor = "#03C75A";

  gaugeLabel.textContent = remaining > 0 ? `오늘 ${remaining}회 남음` : "오늘 한도 소진";
}

// ── Plan bar ──────────────────────────────────────────
function updatePlanBar() {
  const plan  = state.plan || "free";
  const used  = state.searchCount || 0;
  const limit = state.dailyLimit  || 5;

  planBadge.textContent  = plan.toUpperCase();
  planBadge.className    = `plan-badge ${plan}`;
  updateGauge(used, limit);

  upgradeBtn.style.display = plan === "free" ? "inline-block" : "none";
}

// ── fetchPlan (서버 동기화) ───────────────────────────
async function fetchPlan() {
  if (!state.sessionId) return;
  try {
    const res = await fetch(`${SERVER_URL}/api/plan/${state.sessionId}`, {
      headers: { "X-Dev-Secret": DEV_SECRET },
    });
    if (!res.ok) return;
    const data = await res.json();
    state.plan        = data.plan;
    state.searchCount = data.search_count;
    state.dailyLimit  = data.daily_limit;
    saveState();
    updatePlanBar();
  } catch (_) {}
}

// ── Storage ───────────────────────────────────────────
function saveState() {
  chrome.storage.local.set({ [STORAGE_KEY]: state });
}

// ── Init: 저장 상태 복원 ──────────────────────────────
chrome.storage.local.get(STORAGE_KEY, (data) => {
  if (data[STORAGE_KEY]) {
    Object.assign(state, data[STORAGE_KEY]);
    blogIdInput.value = state.blogId;
    if (state.sessionId) {
      showBlogCard(state.blogId, state.postCount);
      featureSection.style.display = "block";
      updatePlanBar();
      fetchPlan();
    }
  }
});

// ── 블로그 수집 ───────────────────────────────────────
async function doIndex(blogId) {
  hideStatus();
  hideBlogCard();
  startProgress();
  indexBtn.disabled = true;
  indexBtn.textContent = "수집 중...";

  try {
    // Step 1: 네이버에서 글 목록 수집
    const fetchRes = await sendMsg({ type: "FETCH_POSTS", blogId });
    if (!fetchRes.ok) throw new Error(fetchRes.error);

    // Step 2: 서버에 저장 + 세션 발급
    const indexRes = await sendMsg({
      type:   "INDEX_BLOG",
      blogId,
      posts:  fetchRes.posts,
    });
    if (!indexRes.ok) throw new Error(indexRes.error);

    state.sessionId  = indexRes.session_id || "";
    state.postCount  = fetchRes.posts.length;
    state.plan       = indexRes.plan        || "free";
    state.searchCount= indexRes.search_count|| 0;
    state.dailyLimit = indexRes.daily_limit || 5;
    state.blogId     = blogId;
    saveState();

    finishProgress(true);
    showBlogCard(blogId, state.postCount);
    featureSection.style.display = "block";
    updatePlanBar();
  } catch (e) {
    finishProgress(false);
    showStatus(`❌ ${e.message}`, "error");
  } finally {
    indexBtn.disabled = false;
    indexBtn.textContent = "수집";
  }
}

indexBtn.addEventListener("click", () => {
  const blogId = blogIdInput.value.trim();
  if (!blogId) return;
  doIndex(blogId);
});

blogIdInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") indexBtn.click();
});

reindexBtn.addEventListener("click", () => {
  if (state.blogId) doIndex(state.blogId);
});

// ── 업그레이드 버튼 ───────────────────────────────────
upgradeBtn.addEventListener("click", () => {
  chrome.tabs.create({ url: `${SERVER_URL}/upgrade?session_id=${state.sessionId}` });
});

// ── Top-N 선택 (관련 글) ──────────────────────────────
let selectedTopN = 5;
document.querySelectorAll(".topn-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".topn-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    selectedTopN = parseInt(btn.dataset.n);
  });
});

// ── Top-N 선택 (중복 감지) ────────────────────────────
let selectedDupTopN = 5;
document.querySelectorAll(".dup-topn-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".dup-topn-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    selectedDupTopN = parseInt(btn.dataset.n);
  });
});

// ── 관련 글 검색 ──────────────────────────────────────
searchBtn.addEventListener("click", async () => {
  const keyword = searchKeyword.value.trim();
  if (!keyword || !state.sessionId) return;

  searchResults.innerHTML = loadingHTML("관련 글 찾는 중...");
  searchBtn.disabled = true;

  try {
    const res = await sendMsg({
      type:     "SEARCH",
      sessionId: state.sessionId,
      blogId:    state.blogId,
      keyword,
      topN:      selectedTopN,
    });
    if (!res.ok) throw new Error(res.error);

    state.dailyLimit  = res.daily_limit || state.dailyLimit;
    state.searchCount = state.dailyLimit - (res.remaining ?? 0);
    saveState();
    updatePlanBar();

    renderSearchResults(res.results || []);
  } catch (e) {
    const msg = e.message.includes("402")
      ? "오늘 무료 사용 횟수(5회)를 모두 사용했습니다. 내일 자정에 초기화됩니다."
      : e.message;
    searchResults.innerHTML = emptyHTML("⚠️", msg);
  } finally {
    searchBtn.disabled = false;
  }
});

searchKeyword.addEventListener("keydown", e => { if (e.key === "Enter") searchBtn.click(); });

// ── 검색 결과 카드 렌더링 ─────────────────────────────
function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,"0")}.${String(d.getDate()).padStart(2,"0")}`;
}

function renderSearchResults(results) {
  if (!results.length) {
    searchResults.innerHTML = emptyHTML("🔍", "관련 글을 찾지 못했습니다.");
    return;
  }
  const today = todayStr();
  searchResults.innerHTML = results.map((r, i) => {
    const score      = r.score || 0;
    const badgeClass = score >= 70 ? "badge-high" : "badge-med";
    const badgeLabel = score >= 70 ? "연관 높음" : "연관 있음";
    const isToday    = r.date === today;
    const dateStr    = isToday ? "🆕 오늘" : (r.date ? `📅 ${r.date}` : "");
    return `
    <div class="result-card" style="animation-delay:${i * 0.04}s">
      <div class="result-card-title">${escHtml(r.title)}</div>
      <div class="result-card-footer">
        <span class="result-date">${dateStr}</span>
        <span class="badge ${badgeClass}">${badgeLabel}</span>
        <div class="result-actions">
          <button class="btn-sm btn-sm-green insert-btn"
            data-url="${escHtml(r.url)}" data-title="${escHtml(r.title)}">📎 삽입</button>
          <button class="btn-sm btn-sm-ghost copy-btn"
            data-url="${escHtml(r.url)}">🔗 복사</button>
        </div>
      </div>
    </div>`;
  }).join("");

  searchResults.querySelectorAll(".insert-btn").forEach(btn =>
    btn.addEventListener("click", e => {
      e.stopPropagation();
      insertLinkToEditor(btn.dataset.url, btn.dataset.title);
    })
  );
  searchResults.querySelectorAll(".copy-btn").forEach(btn =>
    btn.addEventListener("click", e => {
      e.stopPropagation();
      copyToClipboard(btn.dataset.url);
    })
  );
}

// ── 중복 감지 ─────────────────────────────────────────
dupBtn.addEventListener("click", async () => {
  const keyword = dupKeyword.value.trim();
  if (!keyword || !state.sessionId) return;

  dupResults.innerHTML = loadingHTML("중복 글 감지 중...");
  dupBtn.disabled = true;

  try {
    const res = await sendMsg({
      type:     "DUPLICATE",
      sessionId: state.sessionId,
      blogId:    state.blogId,
      keyword,
      topN:      selectedDupTopN,
    });
    if (!res.ok) throw new Error(res.error);
    renderDupResults(res.similar_posts || []);
  } catch (e) {
    dupResults.innerHTML = emptyHTML("⚠️", e.message);
  } finally {
    dupBtn.disabled = false;
  }
});

dupKeyword.addEventListener("keydown", e => { if (e.key === "Enter") dupBtn.click(); });

// ── 중복 결과 카드 렌더링 ────────────────────────────
function renderDupResults(results) {
  if (!results.length) {
    dupResults.innerHTML = emptyHTML("✅", "유사한 글 없음 — 새 글 작성 OK!");
    return;
  }
  dupResults.innerHTML = results.map((r, i) => {
    const sim = r.similarity || 0;
    let badgeClass, badgeLabel;
    if (sim >= 70)      { badgeClass = "badge-danger"; badgeLabel = `중복 위험 ${sim}%`; }
    else if (sim >= 40) { badgeClass = "badge-warn";   badgeLabel = `유사도 ${sim}%`; }
    else                { badgeClass = "badge-low";    badgeLabel = `유사도 ${sim}%`; }

    return `
    <div class="result-card" style="animation-delay:${i * 0.04}s">
      <div class="result-card-title">${escHtml(r.title)}</div>
      <div class="result-card-footer">
        <span class="result-date">${r.date ? `📅 ${r.date}` : ""}</span>
        <span class="badge ${badgeClass}">${badgeLabel}</span>
        <div class="result-actions">
          <button class="btn-sm btn-sm-ghost copy-btn"
            data-url="${escHtml(r.url)}">🔗 복사</button>
        </div>
      </div>
    </div>`;
  }).join("");

  dupResults.querySelectorAll(".copy-btn").forEach(btn =>
    btn.addEventListener("click", e => {
      e.stopPropagation();
      copyToClipboard(btn.dataset.url);
    })
  );
}

// ── 탭 전환 ──────────────────────────────────────────
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add("active");
  });
});

// ── 에디터 링크 삽입 ─────────────────────────────────
async function insertLinkToEditor(linkUrl, linkTitle) {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tabId = tabs[0]?.id;
  if (!tabId) return;

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: (u, t) => {
        const el = document.querySelector('[contenteditable="true"]');
        if (!el) return null;
        el.focus();

        const saved = window.__nLinkerRange;
        if (saved) {
          try {
            const sel = window.getSelection();
            if (saved.startContainer.isConnected) {
              sel.removeAllRanges();
              sel.addRange(saved);
            }
          } catch (_) {}
        }

        const sel = window.getSelection();
        if (!sel || sel.rangeCount === 0) {
          const r = document.createRange();
          r.selectNodeContents(el);
          r.collapse(false);
          sel.removeAllRanges();
          sel.addRange(r);
        }

        const preSel      = window.getSelection();
        const preRange    = preSel.getRangeAt(0).cloneRange();
        preRange.collapse(true);
        const preContainer = preRange.startContainer;
        const preOffset    = preRange.startOffset;

        const textInserted = document.execCommand("insertText", false, t);
        if (!textInserted) return "fail";

        try {
          const postSel   = window.getSelection();
          const postRange = postSel.getRangeAt(0);
          const selectRange = document.createRange();
          if (preContainer.nodeType === Node.TEXT_NODE &&
              preContainer === postRange.endContainer) {
            selectRange.setStart(preContainer, preOffset);
            selectRange.setEnd(postRange.endContainer, postRange.endOffset);
          } else {
            const node = postRange.endContainer;
            const off  = postRange.endOffset;
            selectRange.setStart(node, Math.max(0, off - t.length));
            selectRange.setEnd(node, off);
          }
          postSel.removeAllRanges();
          postSel.addRange(selectRange);
        } catch (_) {
          return "ok_text_only";
        }

        const linked = document.execCommand("createLink", false, u);
        if (!linked) return "ok_text_only";

        try {
          const currentSel = window.getSelection();
          const ancestor   = currentSel.getRangeAt(0)?.commonAncestorContainer;
          const aNode = (ancestor?.nodeType === 1 ? ancestor : ancestor?.parentElement)?.closest("a");
          if (aNode) {
            aNode.target = "_blank";
            const after = document.createRange();
            after.setStartAfter(aNode);
            after.collapse(true);
            currentSel.removeAllRanges();
            currentSel.addRange(after);
          }
        } catch (_) {}

        el.dispatchEvent(new Event("input", { bubbles: true }));
        return "ok";
      },
      args: [linkUrl, linkTitle],
    });

    const vals = results?.map(r => r.result) ?? [];
    if (vals.includes("ok"))          showToast("✅ 링크 삽입 완료!");
    else if (vals.includes("ok_text_only")) showToast("⚠️ 제목만 삽입됨 — 에디터에서 링크 버튼을 눌러주세요");
    else                              showToast("❌ 에디터를 찾을 수 없습니다");
  } catch (e) {
    showToast("❌ " + (e.message || "삽입 오류"));
  }
}

// ── AUTO_SUGGEST (content.js → 자동 추천) ────────────
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== "AUTO_SUGGEST") return;
  if (featureSection.style.display === "none") return;

  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  document.querySelector('[data-tab="search"]').classList.add("active");
  document.getElementById("tab-search").classList.add("active");

  searchKeyword.value = msg.keyword.length > 30
    ? msg.keyword.slice(0, 30) + "…" : msg.keyword;

  if (msg.results.length) renderSearchResults(msg.results);
  else searchResults.innerHTML = emptyHTML("🔍", "관련 글을 찾지 못했습니다.");
});

// ── Utils ─────────────────────────────────────────────
function sendMsg(msg) {
  return new Promise(resolve => {
    chrome.runtime.sendMessage(msg, resp => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
      } else {
        resolve(resp ?? { ok: false, error: "응답 없음" });
      }
    });
  });
}

function copyToClipboard(url) {
  navigator.clipboard.writeText(url).then(() => showToast("✅ 복사 완료!"));
}

let _toastTimer = null;
function showToast(msg) {
  copyToast.textContent = msg;
  copyToast.classList.add("show");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => copyToast.classList.remove("show"), 2200);
}

function loadingHTML(msg) {
  return `<div class="loading"><span class="spinner"></span>${msg}</div>`;
}
function emptyHTML(icon, msg) {
  return `<div class="empty"><div class="empty-icon">${icon}</div>${msg}</div>`;
}
function escHtml(str = "") {
  return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
            .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}
