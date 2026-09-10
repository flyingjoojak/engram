# 자동화 등록

## 권장: 한 명령으로 (크로스플랫폼)

```bash
vestige scheduler install          # 등록 (Windows schtasks / macOS launchd / Linux cron)
vestige scheduler install --dry-run  # 실행 없이 계획만 확인
vestige scheduler status           # 등록 여부
vestige scheduler uninstall        # 제거
```

- `vestige setup` 이 최초 온보딩 때 자동으로 이걸 호출한다(`--no-scheduler` 로 생략 가능).
- 등록되는 작업: **10분마다 증분 인덱싱** + **매일 04:00 정제**. 각각 `<python> -m vestige index|enrich` 를 실행하며, 절전방지·로그·메모리가드는 명령 내부가 처리한다.
- ⚠️ **현재 로그인 사용자**로 실행되어야 한다 - `claude -p` 구독 인증과 e5 모델 캐시가 사용자 프로필에 있기 때문(SYSTEM 계정 불가). schtasks/launchd/cron 모두 사용자 세션 기준.

## (선택) Stop 훅은 쓰지 않음

턴마다 훅으로 인덱싱하면 e5 모델(로딩 시 약 2GB RAM)을 매번 재로딩해 낭비다.
10분 스케줄로 충분(검색 반영 최대 10분 지연). 초 단위 신선도가 필요해지면
그때 상주 데몬(자동수면)으로 승격한다.
