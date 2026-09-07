# Changelog

이 파일은 사용자에게 보이는 변경을 기록합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/),
버전은 [유의적 버전](https://semver.org/lang/ko/)을 따릅니다.

릴리스 방법은 [README의 릴리스 섹션](README.md)을 참고하세요. 새 버전을 태그하면 GitHub 릴리스가
만들어지고, **그 릴리스 본문이 앱의 업데이트 배너에 그대로 표시**됩니다. 아래처럼
`<!--lang:ko-->` / `<!--lang:en-->` 마커로 나눠 두면, 배너가 사용자 언어에 맞는 섹션만 보여줍니다.

## [0.1.0] - 2026-09-04

<!--lang:ko-->

### Added
- **Claude Code와 Codex 로그를 함께 색인** - 두 도구가 기기에 남기는 대화 로그를 자동으로 읽어 소스별로 분류.
- **첫 실행 언어 선택** - 온보딩에서 언어(한국어/영어)를 먼저 고르면 이어지는 화면이 그 언어로 표시.
- **첫 색인 진행 안내** - 처음 대화를 색인하는 동안 상단 배너로 진행 상황(색인된 개수)을 보여줌.
- **자동화(SDK·claude -p) 세션 제외 토글** - 스크립트·헤드리스로 돌린 세션을 색인에서 뺄 수 있음(기본은 전부 색인).
- **로그 폴더 경로 직접 지정** - 자동 탐색에 더해 색인 소스에서 경로를 직접 바꿀 수 있음.
- **Claude CLI 경로 설정(요약용)** - 자동 탐색 + 직접 지정(macOS에서 앱이 셸 PATH를 못 볼 때 대비).
- **백그라운드(서브에이전트) 대화 색인** - 오래 운전한 배경 에이전트와의 대화를 **별도 세션**으로 검색·조회(일회성 도구 봇은 자동 제외).
- **소스별 세션 재개** - claude → `claude --resume`, codex → `codex resume`. 원문 로그가 없으면 열 수 없음으로 처리.
- **검색 소스 필터·결과 소스 배지**, 색인 소스 켜기/끄기.
- **로그 형식 변화 자동 감지** + 원클릭 GitHub 이슈 신고(대화 내용은 안 보내고 형식 지문만).
- **자동 업데이트 알림 배너**(선택) - 새 버전과 릴리스 노트를 표시.
- **3-OS(Windows·Linux·macOS) 릴리스 빌드 CI** + 테스트 CI(GitHub Actions).
- **macOS Homebrew cask** - 서명 없이도 `brew install/upgrade --cask`로 설치·업데이트(격리 해제로 Gatekeeper 경고 없음).
- **미서명 macOS 안내형 업데이트** - 새 버전 감지 시 배너로 알리고 다운로드 페이지를 열어줌(자동 교체는 서명 필요).
- **다국어(한국어·영어)** - OS 로케일 자동 감지, 설정 → 모양에서 전환·저장. 모든 UI 문자열을 번역 리소스로 전환.
- **자동 색인 모드 선택** - 끄기 / 주기(기본) / 실시간 / 특정 시각.

### Changed
- Electron 32 → 43(최신 Chromium으로 창 리사이즈 매끄러움 개선).
- 리사이즈 성능 - 하단바 뷰포트 고정, 3D 지도 리사이즈 디바운스, 긴 목록/채팅에 `content-visibility`.
- 설정 '일반' 탭 정리 - 로그 폴더를 접이식 한 줄로, 개발 용어를 평이한 문구로.
- 임베딩 모델을 int8 e5-large(기본)·MiniLM(저사양) 2종으로 정리, RAM 표기를 실측값으로 정정(int8 약 2.0GB).
- 앱 아이콘을 1024px 고해상도로 교체.

### Fixed
- 마우스 뒤로가기(4번 버튼)로 시작 화면("엔진 불러오는 중")에 갇히던 문제.
- Syncthing 고아 프로세스가 폴더 락을 쥐어 기기 동기화가 안 켜지던 문제.
- MCP 의존성 `mcp` 2.x 비호환(FastMCP 분리) → `<2` 고정.

### Security
- 서빙 화면에 Content-Security-Policy 및 보안 헤더 추가.
- 설정 저장 시 키까지 검증하여 환경변수 주입 차단.
- Syncthing 바이너리를 공식 SHA-256으로 무결성 검증.
- 자동업데이트 산출물 파일명을 고정하여 업데이트 404 방지.

<!--lang:en-->

### Added
- **Indexes both Claude Code and Codex logs** - automatically reads the conversation logs both tools leave on your machine, tagged by source.
- **First-run language pick** - onboarding asks for your language (Korean/English) first, then shows the rest in that language.
- **First-index progress banner** - while your conversations are indexed for the first time, a top banner shows progress (how many indexed).
- **Exclude automation (SDK · claude -p) toggle** - keep script/headless-driven sessions out of the index (everything is indexed by default).
- **Editable log-folder paths** - set a source's log folder directly, on top of auto-detection.
- **Claude CLI path setting (for summaries)** - auto-detect plus manual override (for macOS where the app can't see your shell PATH).
- **Background (sub-agent) conversation indexing** - long-running background-agent chats become their own **searchable sessions** (one-off tool bots are excluded automatically).
- **Source-aware session resume** - claude → `claude --resume`, codex → `codex resume`; sessions whose source log is gone are marked as non-openable.
- **Search source filter & result source badges**, plus per-source indexing on/off.
- **Automatic log-format drift detection** + one-click GitHub issue report (sends only a masked format fingerprint, never conversation content).
- **Update notification banner** (optional) - shows the new version and release notes.
- **3-OS (Windows/Linux/macOS) release-build CI** + test CI (GitHub Actions).
- **macOS Homebrew cask** - install/update via `brew install/upgrade --cask` even unsigned (quarantine removed, no Gatekeeper warning).
- **Assisted update for unsigned macOS** - on a new version, the banner opens the download page (auto-replace needs signing).
- **Localization (Korean & English)** - auto-detects OS locale, switch/persist in Settings → Appearance. All UI strings moved to translation resources.
- **Auto-index mode** - off / interval (default) / realtime / scheduled.

### Changed
- Electron 32 → 43 (smoother window resize on the latest Chromium).
- Resize performance - pinned status bar, debounced 3D-map resize, `content-visibility` on long lists/chats.
- Tidied Settings "General" - log folders collapsed to one line, developer jargon rewritten in plain words.
- Consolidated embedding models to int8 e5-large (default) & MiniLM (low-spec); corrected RAM figures to measured values (int8 ≈ 2.0GB).
- Replaced the app icon with a 1024px high-resolution version.

### Fixed
- Getting stuck on the loading screen ("loading engine") after a mouse back-button (button 4) press.
- Device sync failing to start because an orphaned Syncthing process held the folder lock.
- MCP dependency `mcp` 2.x incompatibility (FastMCP split out) → pinned to `<2`.

### Security
- Added Content-Security-Policy and hardening headers to served pages.
- Validate keys on settings save to block environment-variable injection.
- Verify the Syncthing binary against the official SHA-256.
- Fixed auto-update artifact filenames to prevent update 404s.

[0.1.0]: https://github.com/flyingjoojak/engram/releases/tag/v0.1.0
