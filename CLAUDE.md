# 네이버 내부링크 어시스턴트 — naver-linker-web

## 서비스 URL
- **앱**: https://naver-linker.onrender.com
- **어드민 통계**: https://naver-linker.onrender.com/api/admin/stats

## 핵심 파일
| 파일 | 역할 |
|------|------|
| `main.py` | FastAPI 앱, API 엔드포인트 |
| `matcher.py` | Claude API Tool Use로 관련 글 추천 |
| `db.py` | PostgreSQL 연동, 사용량 추적 |
| `indexer.py` | 네이버 블로그 글 목록 크롤링 |
| `static/index.html` | 단일 페이지 프론트엔드 |
| `extension/manifest.json` | Chrome Extension MV3 설정 |
| `extension/background.js` | Service Worker — 네이버 API 크롤링 + 서버 통신 라우터 |
| `extension/content.js` | 에디터 감지, 자동검색 트리거, 블로그ID 감지, 플로팅 버튼 주입 |
| `extension/popup.js` | 사이드패널 로직 (상태 관리, 검색, 플랜 UI) |
| `extension/popup.html` | 사이드패널 UI |

## 인프라
- **호스팅**: Render.com (무료, Sleep 있음)
- **DB**: Render PostgreSQL (무료)
- **Sleep 방지**: UptimeRobot → `https://naver-linker.onrender.com/api/session` 5분 핑
- **배포**: GitHub push → Render 자동 배포

## 요금제 (구독 전용)
| 플랜 | 가격 | 횟수/월 |
|------|------|------|
| 라이트 | 2,900원/월 | 200회 |
| 베이직 | 6,900원/월 | 500회 |
| 프로 | 11,900원/월 | 1,000회 |

## DB 플랜 한도
```python
FREE_LIMIT = 30
PLAN_LIMITS = { "free": 30, "light": 200, "basic": 500, "pro": 1000 }
MAX_BLOGS_PRO = 3
MAX_BLOGS_PER_IP_DEFAULT = 1
```
모든 플랜 한도는 **월간**(매월 초기화) 기준 — 일일 제한 아님.

## API 엔드포인트
| 엔드포인트 | 역할 |
|-----------|------|
| `POST /api/index` | 블로그 글 목록 수집 (`force:true`로 강제 재수집) |
| `POST /api/search` | 키워드로 관련 글 추천 |
| `POST /api/duplicate` | 중복 글 감지 |
| `GET /api/session` | 세션 발급 + UptimeRobot 핑 용도 |
| `GET /api/status/{blog_id}` | 블로그 등록 여부 확인 |
| `GET /api/user-blogs/{session_id}` | Pro 전용 블로그 목록 |
| `DELETE /api/user-blog` | Pro 블로그 삭제 |
| `POST /api/cancel` | 구독 해지 |
| `GET /api/plan/{session_id}` | 플랜 정보 |
| `GET /api/admin/stats` | 사용 통계 |
| `GET /api/admin/set-plan` | 테스트용 플랜 변경 |
| `GET /api/config` | Remote Config — CSS 셀렉터 JSON 반환 (CWS 재심사 없이 즉시 반영) |
| `POST /api/register-email` | 유료 유저 이메일 등록 (세션 분실 복구용) |
| `POST /api/track-copy` | 링크 복사 횟수 집계 |
| `GET /api/billing/webhook` | 토스페이먼츠 결제 웹훅 수신 |

## DB 스키마
```sql
blogs(blog_id PK, post_count, indexed_at)
posts(id, blog_id, title, url, date, UNIQUE(blog_id, url))
users(session_id PK, blog_id, plan, search_count, is_paid, created_at, reset_at)
ip_searches(ip PK, search_count, reset_date, created_at)
user_blogs(session_id TEXT, blog_id TEXT, added_at TIMESTAMP, PRIMARY KEY(session_id, blog_id))
```

## 주요 아키텍처 결정
- **모델**: claude-haiku-4-5 (Sonnet 대비 ~20배 비용 절감)
- **Claude Tool Use 방식**: JSON 파싱 오류 방지, 구조화 응답 보장
- **프롬프트 캐싱**: post_list ephemeral (반복 검색 비용 절감)
- **관련순**: Claude Haiku + 프롬프트 캐싱
- **최신순**: PostgreSQL WHERE title LIKE + logNo 정렬 (무료)
- **IP 기반 월간 제한**: 무료 플랜 IP 카운트만 사용, 월 30회 (매월 초기화 — `reset_date` 연-월 비교)
- **구독 월별 리셋**: lazy 방식 — `reset_monthly_if_due()` (API 호출 시 reset_at + 30일 비교)
- **DB lazy loading**: `get_conn()` 안에서 `DATABASE_URL` 읽음 (모듈 레벨 금지)
- **콜드스타트 UX**: 서버 응답 전까지 "서버 시작 중..." 오버레이 표시
- **크롤링**: 유저 브라우저에서 직접 (IP 차단 구조적 불가 — 핵심 해자)

## 환경변수
| 변수 | 용도 |
|------|------|
| `DATABASE_URL` | Render PostgreSQL 연결 문자열 |
| `TOSS_SECRET_KEY` | 토스페이먼츠 시크릿 키 (현재 테스트 키) |
| `TOSS_CLIENT_KEY` | 토스페이먼츠 클라이언트 키 (현재 테스트 키) |
| `DEV_SECRET` | `/api/admin/*` 보호용 헤더 값 |
| `BREVO_API_KEY` | 이메일 발송(OTP 인증코드 등) API 키 — Render가 아웃바운드 SMTP를 막아 Gmail SMTP 직접 발송 불가, Brevo HTTP API 사용 |
| `BASE_URL` | 서버 기본 URL (기본값: https://naver-linker.onrender.com) |

## 결제 시스템
- **PG사**: 토스페이먼츠
- **현재 상태**: 심사 중 (테스트 키 사용 중)
- **웹훅 URL**: `https://naver-linker.onrender.com/api/billing/webhook`
- **심사 완료 후 할 일**: 라이브 키 교체 → 웹훅 등록 → upgrade.html 배너 제거 → E2E 테스트

## Extension 아키텍처
- **방식**: Chrome MV3, Side Panel (popup 아님)
- **스토리지 키**: `naver_linker_state` (chrome.storage.local)
- **메시지 플로우**: `content.js` → `background.js` → `popup.js`
- **content.js `all_frames: true`**: iframe 안 커서 위치 저장용. 버튼 주입/자동검색은 top frame만 (`if (window !== window.top) return`)
- **자동검색 트리거**: `document` keyup → 2초 debounce → `getTitleFromEditor()` → `EDITOR_TITLE` 메시지
- **블로그ID 자동 감지**: URL에서 `?blogId=` 파라미터 또는 pathname 첫 세그먼트 추출 → Pro 목록 매칭 시 자동 전환
- **Remote Config**: `/api/config`로 CSS 셀렉터 원격 업데이트 — 네이버 DOM 변경 시 CWS 재심사 없이 즉시 대응

## 네이버 크롤링 핵심
- **API**: `https://blog.naver.com/PostTitleListAsync.nhn?blogId=&currentPage=&countPerPage=30`
- **필터**: `openType !== "0"` (비공개 제외 — 전체공개="2", 이웃공개="1")
- **실행 위치**: 유저 브라우저 (background.js Service Worker) → 서버 IP 차단 구조적 불가
- **날짜 정규화**: `normalizeDate()` — "5월 28." / "3일 전" / "어제" 등 모두 `YYYY.MM.DD` 변환

## 보안
- `/api/admin/*` 요청만 `X-Dev-Secret` 헤더 필수 (서버 환경변수 `DEV_SECRET`와 일치해야 함)
- 일반 `/api/*` 엔드포인트는 헤더 불필요

## 기능 목록
1. **블로그 등록**: 네이버 블로그 ID로 전체 글 목록 수집 + 캐시
2. **관련 글 찾기**: 새 글 키워드 → 내부링크용 관련 글 추천 (관련순 / 최신순)
3. **중복 글 감지**: 쓰려는 키워드와 유사한 기존 글 탐지 (유사도 0~100%)
4. **Pro 멀티블로그**: 최대 3개 계정 전환 (대행사 killer feature)
