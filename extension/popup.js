// storage key
const STORAGE_KEY = "naver_linker_state";

let state = {
  blogId: "",
  sessionId: "",
  postCount: 0,
  plan: "free",
  searchCount: 0,
  dailyLimit: 5,
};

// DOM
const blogIdInput = document.getElementById("blogIdInput");
const indexBtn = document.getElementById("indexBtn");
const blogStatus = document.getElementById("blogStatus");
const featureSection = document.getElementById("featureSection");
const searchKeyword = document.getElementById("searchKeyword");
const searchBtn = document.getElementById("searchBtn");
const searchResults = document.getElementById("searchResults");
const limitBar = document.getElementById("limitBar");
const usedCount = document.getElementById("usedCount");
const limitCount = document.getElementById("limitCount");
const dupKeyword = document.getElementById("dupKeyword");
const dupBtn = document.getElementById("dupBtn");
const dupResults = document.getElementById("dupResults");
const copyToast = document.getElementById("copyToast");

// 초기화: 저장된 상태 복원
chrome.storage.local.get(STORAGE_KEY, (data) => {
  if (data[STORAGE_KEY]) {
    Object.assign(state, data[STORAGE_KEY]);
    blogIdInput.value = state.blogId;
    if (state.sessionId) {
      showStatus(`✅ ${state.blogId} — 글 ${state.postCount}개 등록됨`, "success");
      featureSection.style.display = "block";
      updateLimitBar();
    }
  }
});

function saveState() {
  chrome.storage.local.set({ [STORAGE_KEY]: state });
}

// ── 블로그 수집 ──────────────────────────────────────────
indexBtn.addEventListener("click", async () => {
  const blogId = blogIdInput.value.trim();
  if (!blogId) return;

  state.blogId = blogId;
  setIndexing(true);
  showStatus("블로그 글 목록을 가져오는 중...", "info");

  try {
    // Step 1: 네이버에서 글 목록 수집 (background.js → 사용자 IP)
    const fetchRes = await sendMsg({ type: "FETCH_POSTS", blogId });
    if (!fetchRes.ok) throw new Error(fetchRes.error);

    showStatus(`글 ${fetchRes.posts.length}개 발견. 서버에 저장 중...`, "info");

    // Step 2: 서버에 저장 + 세션 발급
    const indexRes = await sendMsg({
      type: "INDEX_BLOG",
      blogId,
      posts: fetchRes.posts,
    });
    if (!indexRes.ok) throw new Error(indexRes.error);

    state.sessionId = indexRes.session_id || "";
    state.postCount = fetchRes.posts.length;
    state.plan = indexRes.plan || "free";
    state.searchCount = indexRes.search_count || 0;
    state.dailyLimit = indexRes.daily_limit || 5;
    saveState();

    showStatus(`✅ ${blogId} — 글 ${state.postCount}개 등록 완료`, "success");
    featureSection.style.display = "block";
    updateLimitBar();
  } catch (e) {
    showStatus(`❌ 오류: ${e.message}`, "error");
  } finally {
    setIndexing(false);
  }
});

// ── 관련 글 검색 ─────────────────────────────────────────
searchBtn.addEventListener("click", async () => {
  const keyword = searchKeyword.value.trim();
  if (!keyword || !state.sessionId) return;

  searchResults.innerHTML = loadingHTML("관련 글 찾는 중...");
  searchBtn.disabled = true;

  try {
    const res = await sendMsg({
      type: "SEARCH",
      sessionId: state.sessionId,
      blogId: state.blogId,
      keyword,
    });
    if (!res.ok) throw new Error(res.error);

    state.searchCount = res.search_count || state.searchCount + 1;
    state.dailyLimit = res.daily_limit || state.dailyLimit;
    saveState();
    updateLimitBar();

    renderSearchResults(res.results || []);
  } catch (e) {
    searchResults.innerHTML = `<div class="empty">❌ ${e.message}</div>`;
  } finally {
    searchBtn.disabled = false;
  }
});

searchKeyword.addEventListener("keydown", (e) => {
  if (e.key === "Enter") searchBtn.click();
});

function renderSearchResults(results) {
  if (!results.length) {
    searchResults.innerHTML = `<div class="empty">관련 글을 찾지 못했습니다.</div>`;
    return;
  }
  searchResults.innerHTML = results.map((r) => {
    const score = r.score || 0;
    const badgeClass = score >= 70 ? "badge-high" : "badge-med";
    const badgeLabel = score >= 70 ? "연관 높음" : "연관 있음";
    return `
      <div class="result-item" data-url="${r.url}">
        <div class="title">
          ${escapeHtml(r.title)}
          <span class="badge ${badgeClass}">${badgeLabel}</span>
        </div>
        <div class="meta">${r.date || ""} · 클릭하면 링크 복사</div>
      </div>`;
  }).join("");

  document.querySelectorAll(".result-item").forEach((el) => {
    el.addEventListener("click", () => copyLink(el.dataset.url));
  });
}

// ── 중복 감지 ────────────────────────────────────────────
dupBtn.addEventListener("click", async () => {
  const keyword = dupKeyword.value.trim();
  if (!keyword || !state.sessionId) return;

  dupResults.innerHTML = loadingHTML("중복 글 감지 중...");
  dupBtn.disabled = true;

  try {
    const res = await sendMsg({
      type: "DUPLICATE",
      sessionId: state.sessionId,
      blogId: state.blogId,
      keyword,
    });
    if (!res.ok) throw new Error(res.error);

    renderDupResults(res.similar_posts || []);
  } catch (e) {
    dupResults.innerHTML = `<div class="empty">❌ ${e.message}</div>`;
  } finally {
    dupBtn.disabled = false;
  }
});

dupKeyword.addEventListener("keydown", (e) => {
  if (e.key === "Enter") dupBtn.click();
});

function renderDupResults(results) {
  if (!results.length) {
    dupResults.innerHTML = `<div class="empty">✅ 유사한 글 없음 — 새 글 작성 OK!</div>`;
    return;
  }
  dupResults.innerHTML = results.map((r) => {
    const sim = r.similarity || 0;
    const color = sim >= 70 ? "#c0392b" : sim >= 40 ? "#e67e22" : "#2980b9";
    return `
      <div class="result-item" data-url="${r.url}">
        <div class="title" style="color:${color}">
          ${escapeHtml(r.title)}
          <span class="badge" style="background:#f8f9fa;color:${color};border:1px solid ${color}">
            유사도 ${sim}%
          </span>
        </div>
        <div class="meta">${r.date || ""} · 클릭하면 링크 복사</div>
      </div>`;
  }).join("");

  document.querySelectorAll(".result-item").forEach((el) => {
    el.addEventListener("click", () => copyLink(el.dataset.url));
  });
}

// ── 탭 전환 ──────────────────────────────────────────────
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add("active");
  });
});

// ── 유틸 ─────────────────────────────────────────────────
function sendMsg(msg) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, (resp) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
      } else {
        resolve(resp ?? { ok: false, error: "응답 없음" });
      }
    });
  });
}

function showStatus(msg, type) {
  blogStatus.textContent = msg;
  blogStatus.className = `blog-status ${type}`;
  blogStatus.style.display = "block";
}

function setIndexing(loading) {
  indexBtn.disabled = loading;
  indexBtn.textContent = loading ? "수집 중..." : "수집";
}

function updateLimitBar() {
  limitBar.style.display = "block";
  usedCount.textContent = state.searchCount;
  limitCount.textContent = state.dailyLimit;
}

function copyLink(url) {
  navigator.clipboard.writeText(url).then(() => {
    copyToast.classList.add("show");
    setTimeout(() => copyToast.classList.remove("show"), 1800);
  });
}

function loadingHTML(msg) {
  return `<div class="loading"><span class="spinner"></span>${msg}</div>`;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
