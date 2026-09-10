# vestige 데스크탑 (Electron)

Electron 셸이 **파이썬 백엔드(FastAPI+fastembed)를 사이드카로 spawn**하고, 준비되면
`http://127.0.0.1:<port>/` 를 창에 로드한다. 백엔드가 React 프론트(`frontend/dist`)를
`/` 에서 서빙하므로 프론트+API가 동일 출처다.

## 개발 실행 (설치본 없이)

사전: 저장소 루트에서 `pip install ".[all]"` (백엔드 실행용), 그리고 프론트 빌드.

```bash
cd frontend && npm run build          # 백엔드가 서빙할 dist 생성(또는 npm run dev 병행)
cd ../electron && npm install
npm start                             # python packaging/backend_entry.py 를 spawn → 창 로드
```

## 배포 설치본 만들기

```bash
# 1) 프론트 빌드
cd frontend && npm run build
# 2) 백엔드 사이드카 exe 번들(프론트 dist 임베드) → dist/vestige-backend/
cd .. && bash packaging/build-backend.sh
# 3) Electron 설치본(백엔드를 resources/backend 로 동봉)
cd electron && npm install && npm run dist   # → electron/dist/ 에 설치본
```

- 산출물: Windows `NSIS(.exe)`, macOS `.dmg`, Linux `AppImage`.
- **크로스플랫폼**: 각 OS에서 그 OS로 빌드해야 함(PyInstaller·Electron 모두 네이티브). CI(GitHub Actions)로 3-OS 매트릭스 빌드 권장.
- 모델(~2.2GB)은 번들 안 함 → 첫 실행 시 다운로드(로딩 화면 표시).

## 자동 업데이트

`electron-updater` + `package.json`의 `build.publish`(GitHub Releases).
`npm run dist` 시 `--publish` 하거나 CI에서 릴리스에 업로드하면, 배포된 앱이 실행 시
새 버전을 확인·다운로드한다. (코드 서명: Win SmartScreen/mac 공증은 배포 막바지 과제)

## 구조

- `main.js` — 사이드카 spawn·빈 포트·준비 대기·창 로드·생명주기(종료 시 백엔드 kill)·자동업데이트
- `loading.html` — 백엔드 준비 중 스플래시
- 백엔드 진입점: `../packaging/backend_entry.py`(개발) / `resources/backend/vestige-backend`(배포)

## 셸이 담당하는 것 (Phase 1)

- **단일 인스턴스**: `requestSingleInstanceLock` — 두 번째 실행은 기존 창을 띄우고 종료(포트 충돌·중복 백엔드 방지).
- **동적 포트**: 빈 포트를 골라 백엔드에 넘김 → 고정 8765 충돌 원천 제거.
- **managed 모드**: 백엔드를 `VESTIGE_MANAGED=1`로 spawn → 백엔드는 뮤텍스·브라우저 자동열기·app.log를 끔(셸이 담당). stdout/stderr는 셸이 `userData/backend.log`로 캡처.
- **크래시 자동 재시작**: 백엔드가 죽으면 최대 5회 자동 재기동(백오프), 초과 시 안내 화면.
- **트레이**: 열기 / 백엔드 재시작 / 완전 종료. 창을 닫으면 **트레이로 숨김**(백그라운드 색인·동기 계속).
- **자동 업데이트**: 패키지 실행 시 GitHub 릴리스 확인(`electron-updater`). 릴리스가 없으면 조용히 무시.

> 백엔드 exe는 **단독 실행도 가능**(managed 아님) — 그 경우 백엔드가 스스로 뮤텍스·브라우저 자동열기·app.log를 처리한다.
