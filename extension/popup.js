// storage key
const STORAGE_KEY = "naver_linker_state";

let state = {
  blogId: "",
  sessionId: "",
  postCount: 0,
  plan: "free",
  searchCount: 0,
  dailyLimit: 5,
  indexedAt: 0,
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
const dupLimitBar = document.getElementById("dupLimitBar");
const dupUsedCount = document.getElementById("dupUsedCount");
const dupLimitCount = document.getElementById("dupLimitCount");
const copyToast = document.getElementById("copyToast");
const planBar = document.getElementById("planBar");
const planBadge = document.getElementById("planBadge");
const planInfo = document.getElementById("planInfo");
const planSub = document.getElementById("planSub");
const planActions = document.getElementById("planActions");
const upgradeBtn = document.getElementById("upgradeBtn");
const cancelBtn = document.getElementById("cancelBtn");
const usedCount2 = document.getElementById("usedCount2");
const limitCount2 = document.getElementById("limitCount2");
const copySessionBtn = document.getElementById("copySessionBtn");
const blogSwitcher = document.getElementById("blogSwitcher");
const blogSelect = document.getElementById("blogSelect");
const switchBlogBtn = document.getElementById("switchBlogBtn");
const deleteBlogBtn = document.getElementById("deleteBlogBtn");

// 글쓰기 모드: content.js에서 AUTO_SUGGEST 수신
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "AUTO_SUGGEST") {
    showAutoSuggest(msg.keyword, msg.results);
  }
});

function showAutoSuggest(keyword, results) {
  // 기능 탭이 없으면 무시
  if (featureSection.style.display === "none") return;

  // 관련 글 탭으로 자동 전환
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
  document.querySelector('[data-tab="search"]').classList.add("active");
  document.getElementById("tab-search").classList.add("active");

  // 키워드 입력창에 표시
  searchKeyword.value = keyword.length > 30 ? keyword.slice(0, 30) + "…" : keyword;

  // 결과 표시
  if (results.length) {
    renderSearchResults(results);
  } else {
    searchResults.innerHTML = `<div class="empty">관련 글을 찾지 못했습니다.</div>`;
  }

  // 자동 분석 뱃지 표시
  limitBar.style.display = "block";
  usedCount.textContent = state.searchCount;
  limitCount.textContent = state.dailyLimit;
}



// 에디터에 링크 삽입 — URL만 다이얼로그에 입력 (제목 텍스트 삽입 없음)
// 사용자가 에디터의 확인 버튼을 클릭해야 최종 삽입됨
async function insertLinkToEditor(linkUrl) {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tabId = tabs[0]?.id;
  if (!tabId) return;

  try {
    const result = await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: (url) => {
        const btn = document.querySelector('.se-toolbar button[class*="link"]');
        if (!btn) return null;

        return new Promise((resolve) => {
          const observer = new MutationObserver(() => {
            const urlInput = (
              document.querySelector('input[placeholder*="http"]') ||
              document.querySelector('input[placeholder*="URL"]') ||
              document.querySelector('input[placeholder*="url"]')
            );
            if (!urlInput || !urlInput.offsetParent) return;
            observer.disconnect();

            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(urlInput, url);
            urlInput.dispatchEvent(new Event('input',  { bubbles: true }));
            urlInput.dispatchEvent(new Event('change', { bubbles: true }));

            const container = urlInput.closest('div') || urlInput.parentElement;
            const searchBtn = container?.querySelector('button') ||
              [...document.querySelectorAll('button')].find(b =>
                b.offsetParent && !b.textContent.includes('확인') &&
                b !== document.querySelector('.se-toolbar button[class*="link"]')
              );
            if (searchBtn) searchBtn.click();

            resolve('ready');
          });

          observer.observe(document.body, { childList: true, subtree: true });
          btn.click();
          setTimeout(() => { observer.disconnect(); resolve('timeout'); }, 3000);
        });
      },
      args: [linkUrl],
    });

    const r = result?.map(r => r.result).find(v => v !== null) ?? 'no_button';
    if (r === 'ready') {
      showToast("🔗 에디터의 확인 버튼을 눌러주세요");
    } else if (r === 'timeout') {
      showToast("⚠️ 다이얼로그가 열리지 않습니다");
    } else {
      showToast("❌ 링크 버튼을 찾을 수 없습니다");
    }
  } catch (e) {
    showToast("❌ " + (e.message || "삽입 오류"));
  }
}

// 패널 열릴 때마다 새 글 자동 동기화

async function silentSync(blogId) {
  try {
    const fetchRes = await sendMsg({ type: "FETCH_POSTS", blogId });
    if (!fetchRes.ok || !fetchRes.posts?.length) return;
    const indexRes = await sendMsg({ type: "INDEX_BLOG", blogId, posts: fetchRes.posts });
    if (!indexRes.ok) return;
    state.postCount = fetchRes.posts.length;
    state.indexedAt = Date.now();
    saveState();
    showStatus(`✅ ${blogId} — 글 ${state.postCount}개 (동기화 완료)`, "success");
  } catch (_) {}
}

// 초기화: 저장된 상태 복원
chrome.storage.local.get(STORAGE_KEY, (data) => {
  if (data[STORAGE_KEY]) {
    Object.assign(state, data[STORAGE_KEY]);
    blogIdInput.value = state.blogId;
    if (state.sessionId) {
      showStatus(`✅ ${state.blogId} — 글 ${state.postCount}개 등록됨`, "success");
      featureSection.style.display = "block";
      updateLimitBar();
      updatePlanBar();
      // 팝업 열 때마다 플랜 서버 동기화 (결제 후 자동 반영)
      fetchPlan();
      silentSync(state.blogId);
    }
  }
});

function saveState() {
  chrome.storage.local.set({ [STORAGE_KEY]: state });
}

// ── 플랜 바 ──────────────────────────────────────────────
const SERVER_URL  = "https://naver-linker.onrender.com";
const DEV_SECRET  = "nlinker-test-2026";

function updatePlanBar() {
  const plan = state.plan || "free";
  const used = state.searchCount || 0;
  const limit = state.dailyLimit || 5;

  planBadge.textContent = plan.toUpperCase();
  planBadge.className = `plan-badge ${plan}`;

  // 사용 횟수 표시
  usedCount2.textContent = used;
  limitCount2.textContent = limit;

  // 서브 텍스트 (잔여 횟수 강조)
  const remaining = Math.max(0, limit - used);
  if (plan === "free") {
    planSub.textContent = ` · 이번 달 ${remaining}회 남음`;
  } else {
    planSub.textContent = ` · ${remaining}회 남음`;
  }

  // 무료: 업그레이드 버튼 / 유료: 해지 버튼
  upgradeBtn.style.display = plan === "free" ? "block" : "none";
  cancelBtn.style.display = plan !== "free" ? "block" : "none";
  planActions.style.display = "flex";

  // Pro 플랜일 때만 계정 전환 드롭다운 표시
  if (plan === "pro") {
    loadBlogSwitcher();
  } else {
    blogSwitcher.style.display = "none";
  }
}

async function fetchPlan() {
  if (!state.sessionId) return;
  try {
    const res = await fetch(`${SERVER_URL}/api/plan/${state.sessionId}`, {
      headers: { "X-Dev-Secret": DEV_SECRET },
    });
    if (!res.ok) return;
    const data = await res.json();
    state.plan = data.plan;
    state.searchCount = data.search_count;
    state.dailyLimit = data.daily_limit;
    saveState();
    updatePlanBar();
  } catch (_) {}
}

upgradeBtn.addEventListener("click", () => {
  chrome.tabs.create({
    url: `${SERVER_URL}/upgrade?session_id=${state.sessionId}`,
  });
});

copySessionBtn.addEventListener("click", () => {
  if (!state.sessionId) return;
  navigator.clipboard.writeText(state.sessionId).then(() => showToast("세션 ID 복사됨!"));
});

cancelBtn.addEventListener("click", async () => {
  if (!confirm(`구독을 해지하면 즉시 무료 플랜으로 전환됩니다.\n남은 기간 환불은 불가합니다. 계속하시겠습니까?`)) return;
  cancelBtn.disabled = true;
  try {
    const res = await fetch(`${SERVER_URL}/api/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Dev-Secret": DEV_SECRET },
      body: JSON.stringify({ session_id: state.sessionId }),
    });
    if (!res.ok) throw new Error("해지 실패");
    state.plan = "free";
    state.searchCount = 0;
    state.dailyLimit = 5;
    saveState();
    updatePlanBar();
    updateLimitBar();
    showStatus("구독이 해지되었습니다. 무료 플랜으로 전환됩니다.", "info");
  } catch (e) {
    showStatus("❌ 해지 실패: " + e.message, "error");
  } finally {
    cancelBtn.disabled = false;
  }
});

async function loadBlogSwitcher() {
  if (!state.sessionId) return;
  try {
    const res = await fetch(`${SERVER_URL}/api/user-blogs/${state.sessionId}`, {
      headers: { "X-Dev-Secret": DEV_SECRET },
    });
    if (!res.ok) return;
    const data = await res.json();
    const blogs = data.blogs || [];
    if (blogs.length < 2) {
      blogSwitcher.style.display = "none";
      return;
    }
    blogSelect.innerHTML = blogs
      .map((id) => `<option value="${id}" ${id === state.blogId ? "selected" : ""}>${id === state.blogId ? `${id} (현재)` : id}</option>`)
      .join("");
    const isActive = blogSelect.value === state.blogId;
    switchBlogBtn.disabled = isActive;
    deleteBlogBtn.disabled = isActive;
    blogSwitcher.style.display = "block";
  } catch (_) {}
}

blogSelect.addEventListener("change", () => {
  const selectedBlogId = blogSelect.value;
  const isActive = selectedBlogId === state.blogId;
  switchBlogBtn.disabled = isActive;
  deleteBlogBtn.disabled = isActive;
});

switchBlogBtn.addEventListener("click", () => {
  const newBlogId = blogSelect.value;
  if (!newBlogId || newBlogId === state.blogId) return;
  state.blogId = newBlogId;
  blogIdInput.value = newBlogId;
  state.postCount = 0;
  saveState();
  showStatus(`✅ ${newBlogId} 로 전환됨`, "success");
  loadBlogSwitcher();
});

deleteBlogBtn.addEventListener("click", async () => {
  const targetBlogId = blogSelect.value;
  if (!targetBlogId || targetBlogId === state.blogId) return;
  if (!confirm(`'${targetBlogId}'를 목록에서 삭제하시겠습니까?`)) return;

  deleteBlogBtn.disabled = true;
  const res = await sendMsg({ type: "DELETE_BLOG", sessionId: state.sessionId, blogId: targetBlogId });
  if (!res.ok) {
    showStatus("❌ 삭제 실패: " + res.error, "error");
    deleteBlogBtn.disabled = false;
    return;
  }
  await loadBlogSwitcher();
  showStatus(`🗑 ${targetBlogId} 삭제됨`, "info");
});


// ── 블로그 수집 ──────────────────────────────────────────
indexBtn.addEventListener("click", async () => {
  const blogId = blogIdInput.value.trim();
  if (!blogId) return;

  // non-pro 유저가 다른 블로그로 변경 시도 → 교체 확인
  let forceReplace = false;
  if (state.blogId && state.blogId !== blogId && state.plan !== "pro" && state.sessionId) {
    const confirmed = confirm(`현재 등록된 '${state.blogId}'가 '${blogId}'로 교체됩니다.\n기존 블로그 슬롯이 초기화됩니다. 계속하시겠습니까?`);
    if (!confirmed) return;
    forceReplace = true;
  }

  state.blogId = blogId;
  setIndexing(true);
  showStatus("블로그 글 목록을 가져오는 중...", "info");

  try {
    // Step 1: 네이버에서 글 목록 수집 (background.js → 사용자 IP)
    const fetchRes = await sendMsg({ type: "FETCH_POSTS", blogId });
    if (!fetchRes.ok) throw new Error(fetchRes.error);

    showStatus(`글 ${fetchRes.posts.length}개 발견. 서버에 저장 중...`, "info");

    // Step 2: 서버에 저장 + 세션 발급 (기존 세션 있으면 재사용)
    const indexRes = await sendMsg({
      type: "INDEX_BLOG",
      blogId,
      posts: fetchRes.posts,
      sessionId: state.sessionId || "",
      forceReplace,
    });
    if (!indexRes.ok) throw new Error(indexRes.error);

    state.sessionId = indexRes.session_id || "";
    state.postCount = fetchRes.posts.length;
    state.plan = indexRes.plan || "free";
    state.searchCount = indexRes.search_count || 0;
    state.dailyLimit = indexRes.daily_limit || 5;
    saveState();

    state.indexedAt = Date.now();
    showStatus(`✅ ${blogId} — 글 ${state.postCount}개 등록 완료`, "success");
    featureSection.style.display = "block";
    updateLimitBar();
    updatePlanBar();
  } catch (e) {
    showStatus(`❌ 오류: ${e.message}`, "error");
  } finally {
    setIndexing(false);
  }
});

// ── top_n 버튼 ───────────────────────────────────────────
let selectedTopN = 5;
document.querySelectorAll(".topn-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".topn-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    selectedTopN = parseInt(btn.dataset.n);
  });
});

const selectedDupTopN = 10;

// ── 정렬 버튼 ────────────────────────────────────────────
let currentResults = [];
let currentSort = "relevance";
const sortRow = document.getElementById("sortRow");
const sortHint = document.getElementById("sortHint");
const sortHintText = document.getElementById("sortHintText");

const SORT_HINTS = {
  relevance: "🤖 AI가 의미적으로 관련된 글 추천 — 키워드가 제목에 없어도 나올 수 있어요",
  latest:    "🕐 제목에 키워드가 포함된 글 중 최신순 — 결과가 적을 수 있어요",
};

function updateSortHint(sort) {
  sortHintText.textContent = SORT_HINTS[sort] || "";
  sortHint.style.display = "block";
}

document.querySelectorAll(".sort-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.sort === currentSort) return;
    document.querySelectorAll(".sort-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentSort = btn.dataset.sort;
    updateSortHint(currentSort);
    const cached = currentSort === "latest" ? latestResults : relevanceResults;
    if (cached.length) {
      currentResults = cached;
      renderSearchResults(currentResults);
    }
  });
});


// ── 관련 글 검색 ─────────────────────────────────────────
let relevanceResults = [];
let latestResults = [];

async function doSearch(keyword) {
  searchResults.innerHTML = loadingHTML("관련 글 찾는 중...");
  searchBtn.disabled = true;
  relevanceResults = [];
  latestResults = [];

  try {
    // 관련순(Claude) + 최신순(DB) 병렬 요청
    const [relRes, latRes] = await Promise.all([
      sendMsg({ type: "SEARCH", sessionId: state.sessionId, blogId: state.blogId, keyword, topN: selectedTopN, sort: "relevance" }),
      sendMsg({ type: "SEARCH", sessionId: state.sessionId, blogId: state.blogId, keyword, topN: selectedTopN, sort: "latest" }),
    ]);

    if (!relRes.ok) throw new Error(relRes.error);

    state.dailyLimit = relRes.daily_limit || state.dailyLimit;
    state.searchCount = state.dailyLimit - (relRes.remaining ?? 0);
    saveState();
    updateLimitBar();

    relevanceResults = relRes.results || [];
    latestResults = latRes.ok ? (latRes.results || []) : [];

    currentResults = currentSort === "latest" ? latestResults : relevanceResults;
    sortRow.style.display = currentResults.length ? "flex" : "none";
    renderSearchResults(currentResults);
  } catch (e) {
    const msg = e.message.includes("402")
      ? "이번 달 무료 사용 횟수(30회)를 모두 사용했습니다.<br>다음 달에 초기화됩니다."
      : e.message;
    searchResults.innerHTML = `<div class="empty">❌ ${msg}</div>`;
  } finally {
    searchBtn.disabled = false;
  }
}

searchBtn.addEventListener("click", () => {
  const keyword = searchKeyword.value.trim();
  if (!keyword || !state.sessionId) return;
  doSearch(keyword);
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
    const insertBtn = `<button class="insert-btn" data-url="${r.url}" data-title="${escapeHtml(r.title)}" title="에디터에 링크를 바로 삽입합니다 (깔끔하게 카드만 표시)">📎 삽입</button>`;
    return `
      <div class="result-item" data-url="${r.url}" data-title="${escapeHtml(r.title)}">
        <div class="title">
          ${escapeHtml(r.title)}
        </div>
        <div class="meta-row">
          <div class="action-btns">
            ${insertBtn}
            <button class="copy-btn" data-url="${r.url}" title="URL을 클립보드에 복사합니다 (붙여넣기 시 URL 텍스트 + 카드가 함께 표시됩니다)">🔗 복사</button>
          </div>
        </div>
      </div>`;
  }).join("");

  document.querySelectorAll(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      copyLink(btn.dataset.url);
    });
  });
  document.querySelectorAll(".insert-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      insertLinkToEditor(btn.dataset.url);
    });
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
      topN: selectedDupTopN,
    });
    if (!res.ok) throw new Error(res.error);

    renderDupResults(res.similar_posts || []);

    // 사용 횟수 업데이트 (검색 탭과 동일한 방식)
    if (res.daily_limit !== undefined) {
      state.dailyLimit = res.daily_limit;
      state.searchCount = res.daily_limit - (res.remaining ?? 0);
      saveState();
      dupUsedCount.textContent = state.searchCount;
      dupLimitCount.textContent = state.dailyLimit;
      dupLimitBar.style.display = "block";
      updateLimitBar();
      updatePlanBar();
    }
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

  dupLimitBar.style.display = "block";
  dupUsedCount.textContent = state.searchCount;
  dupLimitCount.textContent = state.dailyLimit;
}

function copyLink(url) {
  navigator.clipboard.writeText(url).then(() => {
    showToast("링크 복사됨!");
  });
}

function showToast(msg) {
  copyToast.textContent = msg;
  copyToast.classList.add("show");
  setTimeout(() => copyToast.classList.remove("show"), 2000);
}

function loadingHTML(msg) {
  return `<div class="loading"><span class="spinner"></span>${msg}</div>`;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
