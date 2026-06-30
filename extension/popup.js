// storage key
const STORAGE_KEY = "naver_linker_state";

// Whale 감지 — 최상단에서 정의 (초기화 시점 분기용)
const _IS_WHALE = /Whale/i.test(navigator.userAgent);
// Whale용 posts 캐시 — init 시점에 eager-load, cross-origin fetch 없이 재사용
let _whalePostsCache = null;

let state = {
  blogId: "",
  sessionId: "",
  postCount: 0,
  plan: "free",
  searchCount: 0,
  dailyLimit: 5,
  indexedAt: 0,
  emailRegistered: false,
  email: "",
  linksCopied: 0,
  autoCollect: true,
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
const emailBanner = document.getElementById("emailBanner");
const emailBannerInput = document.getElementById("emailBannerInput");
const emailBannerBtn = document.getElementById("emailBannerBtn");
const emailBannerMsg = document.getElementById("emailBannerMsg");
const blogSwitcher = document.getElementById("blogSwitcher");
const blogSelect = document.getElementById("blogSelect");
const switchBlogBtn = document.getElementById("switchBlogBtn");
const deleteBlogBtn = document.getElementById("deleteBlogBtn");
const showRecoverBtn = document.getElementById("showRecoverBtn");
const recoverRow = document.getElementById("recoverRow");
const recoverEmailInput = document.getElementById("recoverEmailInput");
const recoverEmailBtn = document.getElementById("recoverEmailBtn");
const recoverMsg = document.getElementById("recoverMsg");
const otpRow = document.getElementById("otpRow");
const otpInput = document.getElementById("otpInput");
const otpVerifyBtn = document.getElementById("otpVerifyBtn");
const closePanelBtn = document.getElementById("closePanelBtn");
const autoCollectToggle = document.getElementById("autoCollectToggle");

closePanelBtn.addEventListener("click", () => window.close());

autoCollectToggle.addEventListener("change", () => {
  state.autoCollect = autoCollectToggle.checked;
  saveState();
});

// 글쓰기 모드: content.js에서 AUTO_SUGGEST 수신
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "AUTO_SUGGEST") {
    showAutoSuggest(msg.keyword, msg.results);
  }
  if (msg.type === "DETECTED_BLOG_ID") {
    const detected = msg.blogId;
    if (!detected || detected === state.blogId || !state.sessionId) return;
    // Pro: 서버 블로그 목록에 있으면 자동 전환
    fetch(`${SERVER_URL}/api/user-blogs/${state.sessionId}`)
      .then((r) => r.json())
      .then((data) => {
        const blogs = data.blogs || [];
        if (blogs.includes(detected)) {
          state.blogId = detected;
          blogIdInput.value = detected;
          saveState();
          loadBlogSwitcher();
          showStatus(`🔄 ${detected} 블로그로 자동 전환됨`, "success");
          silentSync(detected);
        }
      })
      .catch(() => {});
  }
  if (msg.type === "EDITOR_TITLE") {
    if (featureSection.style.display === "none") return;
    // 관련 글 탭으로 전환
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    document.querySelector('[data-tab="search"]').classList.add("active");
    document.getElementById("tab-search").classList.add("active");
    // 제목을 키워드로 자동 입력
    searchKeyword.value = msg.keyword;
    searchKeyword.focus();
    showToast("📝 검색 버튼을 눌러 내부링크를 찾아보세요!");
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
// Whale: posts 캐시도 동시에 eager-load (이후 cross-origin fetch가 context를 kill하기 전에)
const _initKeys = [STORAGE_KEY, "naver_linker_posts_cache"];
chrome.storage.local.get(_initKeys, (data) => {
  // Whale: posts 캐시 즉시 저장 (나중에 storage 접근 불가해질 수 있음)
  if (_IS_WHALE && data["naver_linker_posts_cache"]) {
    _whalePostsCache = data["naver_linker_posts_cache"];
  }
  if (data[STORAGE_KEY]) {
    Object.assign(state, data[STORAGE_KEY]);
    if (state.autoCollect === undefined) state.autoCollect = true;
    autoCollectToggle.checked = state.autoCollect;
    blogIdInput.value = state.blogId;
    if (state.sessionId) {
      showStatus(`✅ ${state.blogId} — 글 ${state.postCount}개 등록됨`, "success");
      featureSection.style.display = "block";
      updateLimitBar();
      updatePlanBar();
      fetchPlan();
      if (!_IS_WHALE) silentSync(state.blogId);
    } else if (state.email) {
      autoRecoverByEmail(state.email);
    }
  }
});

function saveState() {
  chrome.storage.local.set({ [STORAGE_KEY]: state });
}


// ── 플랜 바 ──────────────────────────────────────────────
const SERVER_URL  = "https://naver-linker.onrender.com";

function updatePlanBar() {
  const plan = state.plan || "free";
  const used = state.searchCount || 0;
  const limit = state.dailyLimit || 5;

  planBadge.textContent = plan.toUpperCase();
  planBadge.className = `plan-badge ${plan}`;

  // 사용 횟수 표시
  usedCount2.textContent = used;
  limitCount2.textContent = limit;

  planSub.textContent = "";

  // 무료: 업그레이드 버튼 / 유료: 해지 버튼
  upgradeBtn.style.display = plan === "free" ? "block" : "none";
  cancelBtn.style.display = plan !== "free" ? "block" : "none";
  planActions.style.display = "flex";

  // 유료 플랜 + 이메일 미등록 시 배너
  emailBanner.style.display = (plan !== "free" && !state.emailRegistered) ? "block" : "none";


  // Pro 플랜일 때만 계정 전환 드롭다운 표시
  if (plan === "pro") {
    loadBlogSwitcher();
  } else {
    blogSwitcher.style.display = "none";
  }

  updateDuplicateTabLock(plan);
}

// 라이트 플랜은 중복 감지 기능 잠금
function updateDuplicateTabLock(plan) {
  const dupTab = document.querySelector('[data-tab="duplicate"]');
  const isLocked = plan === "light";
  dupTab.classList.toggle("locked", isLocked);
  dupTab.title = isLocked ? "베이직 이상 플랜에서 사용 가능합니다" : "";

  if (isLocked && dupTab.classList.contains("active")) {
    document.querySelector('[data-tab="search"]').click();
  }
}

async function fetchPlan() {
  if (!state.sessionId) return;
  try {
    const res = await fetch(`${SERVER_URL}/api/plan/${state.sessionId}`);
    if (!res.ok) return;
    const data = await res.json();
    state.plan = data.plan;
    state.searchCount = data.search_count;
    state.dailyLimit = data.daily_limit;
    state.linksCopied = data.links_copied || 0;
    saveState();
    updatePlanBar();
  } catch (_) {}
}

upgradeBtn.addEventListener("click", () => {
  chrome.tabs.create({
    url: `https://sung121722.github.io/naver-linker/upgrade.html?session_id=${state.sessionId}`,
  });
});


emailBannerBtn.addEventListener("click", async () => {
  const email = emailBannerInput.value.trim();
  if (!email || !email.includes("@")) return;
  emailBannerBtn.disabled = true;
  try {
    const res = await fetch(`${SERVER_URL}/api/register-email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, email }),
    });
    emailBannerMsg.style.display = "block";
    if (res.ok) {
      state.emailRegistered = true;
      state.email = email;
      saveState();
      emailBannerMsg.style.color = "#087f3d";
      emailBannerMsg.textContent = "✅ 등록 완료! 분실 시 이 이메일로 복구 가능합니다.";
      setTimeout(() => { emailBanner.style.display = "none"; }, 2000);
    } else {
      emailBannerMsg.style.color = "#c0392b";
      emailBannerMsg.textContent = "등록 실패. 다시 시도해주세요.";
      emailBannerBtn.disabled = false;
    }
  } catch (_) {
    emailBannerMsg.style.display = "block";
    emailBannerMsg.style.color = "#c0392b";
    emailBannerMsg.textContent = "오류가 발생했습니다.";
    emailBannerBtn.disabled = false;
  }
});

cancelBtn.addEventListener("click", async () => {
  if (!confirm(`구독을 해지하면 즉시 무료 플랜으로 전환됩니다.\n결제 후 7일 이내, 검색 기능을 한 번도 사용하지 않은 경우에 한해 전액 환불 가능 (kang020672@gmail.com 문의).\n계속하시겠습니까?`)) return;
  cancelBtn.disabled = true;
  try {
    const res = await fetch(`${SERVER_URL}/api/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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

function autoRecoverByEmail(email) {
  // OTP 방식으로 변경 — 자동 복구 불가, 이메일 pre-fill 후 복구 UI 노출
  recoverEmailInput.value = email;
  recoverRow.style.display = "block";
  showStatus(`📧 ${email} 으로 인증코드를 받아 복구해주세요.`, "info");
}

showRecoverBtn.addEventListener("click", () => {
  recoverRow.style.display = recoverRow.style.display === "none" ? "block" : "none";
});

// Step 1: 이메일 입력 → 인증코드 발송
recoverEmailBtn.addEventListener("click", async () => {
  const email = recoverEmailInput.value.trim();
  if (!email || !email.includes("@")) return;
  recoverEmailBtn.disabled = true;
  recoverMsg.style.display = "none";
  otpRow.style.display = "none";
  try {
    const res = await fetch(`${SERVER_URL}/api/auto-recover?email=${encodeURIComponent(email)}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "등록된 구독 정보를 찾을 수 없습니다.");
    }
    recoverMsg.style.display = "block";
    recoverMsg.style.color = "#1a6fa8";
    recoverMsg.textContent = "📧 인증코드를 이메일로 발송했습니다.";
    otpRow.style.display = "block";
    otpInput.value = "";
    otpInput.focus();
  } catch (e) {
    recoverMsg.style.display = "block";
    recoverMsg.style.color = "#c0392b";
    recoverMsg.textContent = e.message || "발송 실패";
  } finally {
    recoverEmailBtn.disabled = false;
  }
});

// Step 2: 인증코드 입력 → 복구 완료
otpVerifyBtn.addEventListener("click", async () => {
  const email = recoverEmailInput.value.trim();
  const code = otpInput.value.trim();
  if (!code || code.length !== 6) return;
  otpVerifyBtn.disabled = true;
  try {
    const res = await fetch(`${SERVER_URL}/api/verify-recovery`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, code }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "인증 실패");
    }
    const data = await res.json();
    const planRes = await fetch(`${SERVER_URL}/api/plan/${data.session_id}`);
    const planData = await planRes.json();
    state.sessionId = data.session_id;
    state.plan = planData.plan;
    state.searchCount = planData.search_count;
    state.dailyLimit = planData.daily_limit;
    state.email = email;
    state.emailRegistered = true;
    saveState();
    recoverMsg.style.display = "block";
    recoverMsg.style.color = "#087f3d";
    recoverMsg.textContent = `✅ ${planData.plan.toUpperCase()} 플랜 복구 완료. 블로그를 다시 등록해주세요.`;
    otpRow.style.display = "none";
    recoverRow.style.display = "none";
    featureSection.style.display = "block";
    updateLimitBar();
    updatePlanBar();
  } catch (e) {
    recoverMsg.style.display = "block";
    recoverMsg.style.color = "#c0392b";
    recoverMsg.textContent = e.message || "인증 실패";
  } finally {
    otpVerifyBtn.disabled = false;
  }
});


async function loadBlogSwitcher() {
  if (!state.sessionId) return;
  try {
    const res = await fetch(`${SERVER_URL}/api/user-blogs/${state.sessionId}`);
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

let selectedDupTopN = 10;
document.querySelectorAll(".dup-topn-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".dup-topn-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    selectedDupTopN = parseInt(btn.dataset.n);
  });
});

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
    state.searchCount = relRes.search_count ?? (state.dailyLimit - (relRes.remaining ?? 0));
    saveState();
    updateLimitBar();
    updatePlanBar();

    relevanceResults = relRes.results || [];
    latestResults = latRes.ok ? (latRes.results || []) : [];

    saveState();

    currentResults = currentSort === "latest" ? latestResults : relevanceResults;
    sortRow.style.display = currentResults.length ? "flex" : "none";
    renderSearchResults(currentResults);
  } catch (e) {
    const msg = e.message.includes("402")
      ? `이번 달 무료 사용 횟수(${state.dailyLimit}회)를 모두 사용했습니다.<br>다음 달에 초기화됩니다.`
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
    const insertBtn = `<button class="insert-btn insert-btn-full" data-url="${r.url}" data-title="${escapeHtml(r.title)}" title="에디터에 링크를 바로 삽입합니다 (깔끔하게 카드만 표시)">📎 삽입</button>`;
    return `
      <div class="result-item" data-url="${r.url}" data-title="${escapeHtml(r.title)}">
        <div class="title">
          ${escapeHtml(r.title)}
        </div>
        ${insertBtn}
      </div>`;
  }).join("");

  searchResults.querySelectorAll(".insert-btn").forEach((btn) => {
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
    const insertBtn = `<button class="insert-btn insert-btn-full" data-url="${r.url}" data-title="${escapeHtml(r.title)}" title="에디터에 링크를 바로 삽입합니다 (깔끔하게 카드만 표시)">📎 삽입</button>`;
    return `
      <div class="result-item" data-url="${r.url}" data-title="${escapeHtml(r.title)}">
        <div class="title" style="color:${color}">
          ${escapeHtml(r.title)}
          <span class="badge" style="background:#f8f9fa;color:${color};border:1px solid ${color}">
            유사도 ${sim}%
          </span>
        </div>
        ${insertBtn}
      </div>`;
  }).join("");

  dupResults.querySelectorAll(".insert-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      insertLinkToEditor(btn.dataset.url);
    });
  });
}

// ── 탭 전환 ──────────────────────────────────────────────
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    if (tab.classList.contains("locked")) {
      showToast("🔒 베이직 이상 플랜에서 사용 가능합니다");
      return;
    }
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add("active");
  });
});

// ── 유틸 ─────────────────────────────────────────────────

// 서비스 워커 비활성 시 popup.js에서 직접 API 호출 (Whale 등 호환성)
const _NAVER_API = "https://blog.naver.com/PostTitleListAsync.nhn";
const _PER_PAGE  = 30;
const _H         = { "Content-Type": "application/json" };

async function _fetchPage(blogId, page) {
  const url = `${_NAVER_API}?blogId=${encodeURIComponent(blogId)}&currentPage=${page}&countPerPage=${_PER_PAGE}&totalCount=0`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Naver API error: ${r.status}`);
  const text = await r.text();
  return JSON.parse(text.replace(/\\(?!["\\/bfnrtu])/g, "\\\\"));
}

function _decodeTitle(t) {
  let s = t;
  try { s = decodeURIComponent(t.replace(/\+/g, " ")); } catch (_) { s = t.replace(/\+/g, " "); }
  return s.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
          .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
          .replace(/&#(\d+);/g, (_, c) => String.fromCharCode(+c));
}

async function _fetchAllPosts(blogId) {
  const first = await _fetchPage(blogId, 1);
  const total = parseInt(first.totalCount || 0);
  if (!total) return [];
  const pages = Math.ceil(total / _PER_PAGE);
  const rest = await Promise.all(Array.from({ length: pages - 1 }, (_, i) => _fetchPage(blogId, i + 2)));
  const posts = [];
  const base = `https://blog.naver.com/${blogId}`;
  for (const pg of [first, ...rest]) {
    for (const item of pg.postList || []) {
      if (String(item.openType) === "0") continue; // 비공개 제외
      posts.push({ title: _decodeTitle(item.title || ""), url: `${base}/${item.logNo}`, date: item.addDate || "" });
    }
  }
  return posts;
}

async function _directCall(msg) {
  if (msg.type === "FETCH_POSTS") {
    // 1순위: 서버 릴레이 (Whale에서 content.js가 저장 — _IS_WHALE 판별 불필요)
    const relayPosts = await _whaleRelayFetch(msg.blogId);
    if (relayPosts) return { ok: true, posts: relayPosts };

    // 2순위: chrome.storage 캐시 (콜백 방식 — Promise API는 Whale popup에서 undefined)
    const cached = await _storageGet("naver_linker_posts_cache");
    if (cached && cached.blogId === msg.blogId && cached.posts?.length > 0) {
      return { ok: true, posts: cached.posts };
    }

    // 3순위: popup 직접 fetch — Chrome SW 죽었을 때만 여기 도달
    // Whale에서는 _fetchAllPosts가 Extension context invalidated 유발하므로 실행 금지
    // → 이 시점까지 왔다면 content.js가 아직 수집 중이거나 자동 수집이 꺼져있음
    if (state.autoCollect === false) {
      throw new Error("자동 수집이 꺼져 있어 글 목록을 가져올 수 없습니다. 패널 상단에서 자동 수집을 켜주세요.");
    }
    throw new Error("블로그 작성 페이지에서 🔗 버튼이 ✅로 바뀐 후 다시 시도해주세요.");
  }
  if (msg.type === "INDEX_BLOG") {
    const body = { blog_id: msg.blogId, posts: msg.posts, source: "extension" };
    if (msg.sessionId) body.session_id = msg.sessionId;
    if (msg.forceReplace) body.force_replace = true;
    const r = await fetch(`${SERVER_URL}/api/index`, { method: "POST", headers: _H, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`Server error: ${r.status}`);
    return { ok: true, ...await r.json() };
  }
  if (msg.type === "SEARCH") {
    const r = await fetch(`${SERVER_URL}/api/search`, {
      method: "POST", headers: _H,
      body: JSON.stringify({ session_id: msg.sessionId, blog_id: msg.blogId, keyword: msg.keyword, top_n: msg.topN, sort: msg.sort }),
    });
    if (!r.ok) { const b = await r.json().catch(() => ({})); throw new Error(b.detail || `Server error: ${r.status}`); }
    return { ok: true, ...await r.json() };
  }
  if (msg.type === "DUPLICATE") {
    const r = await fetch(`${SERVER_URL}/api/duplicate`, {
      method: "POST", headers: _H,
      body: JSON.stringify({ session_id: msg.sessionId, blog_id: msg.blogId, keyword: msg.keyword, top_n: msg.topN }),
    });
    if (!r.ok) throw new Error(`Server error: ${r.status}`);
    return { ok: true, ...await r.json() };
  }
  if (msg.type === "DELETE_BLOG") {
    const r = await fetch(`${SERVER_URL}/api/user-blog`, {
      method: "DELETE", headers: _H,
      body: JSON.stringify({ session_id: msg.sessionId, blog_id: msg.blogId }),
    });
    if (!r.ok) throw new Error(`Server error: ${r.status}`);
    return { ok: true, ...await r.json() };
  }
  return { ok: false, error: "Unknown message type" };
}

// Whale 릴레이: 서버에서 content.js가 저장한 posts 가져오기
// chrome.* API 완전 불필요 — 일반 fetch로 우리 서버에서 읽기
async function _whaleRelayFetch(blogId) {
  try {
    const r = await fetch(`${SERVER_URL}/api/whale-relay/${encodeURIComponent(blogId)}`);
    if (!r.ok) return null;
    const data = await r.json();
    if (data.ok && Array.isArray(data.posts) && data.posts.length > 0) return data.posts;
  } catch (_) {}
  return null;
}

// Chrome용 콜백 방식 storage 읽기 (Whale에서는 미사용)
function _storageGet(key) {
  return new Promise((resolve) => {
    try {
      chrome.storage.local.get(key, (r) => {
        if (chrome.runtime.lastError) { resolve(null); return; }
        resolve((r && r[key]) || null);
      });
    } catch (_) { resolve(null); }
  });
}

function sendMsg(msg) {
  return new Promise((resolve) => {
    if (_IS_WHALE) {
      // Whale: background.js 우회, 직접 API 호출
      _directCall(msg).then(resolve).catch((e) => resolve({ ok: false, error: e.message }));
      return;
    }
    // Chrome: background.js 서비스 워커 사용
    // lastError 또는 응답 내용에 "invalidated" 포함 시 직접 호출로 폴백
    try {
      chrome.runtime.sendMessage(msg, (resp) => {
        const swDead =
          !!chrome.runtime.lastError ||
          (resp && !resp.ok && typeof resp.error === "string" && resp.error.toLowerCase().includes("invalidated"));
        if (swDead) {
          _directCall(msg).then(resolve).catch((e) => resolve({ ok: false, error: e.message }));
        } else {
          resolve(resp ?? { ok: false, error: "응답 없음" });
        }
      });
    } catch (_) {
      _directCall(msg).then(resolve).catch((e) => resolve({ ok: false, error: e.message }));
    }
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
