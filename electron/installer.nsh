; electron-builder NSIS custom include.
; 설치 시작 시 실행 중인 앱/백엔드를 확실히 종료해 파일 잠금("가끔 설치 오류 → 다시 시도하면 됨")을 방지.
; Vestige은 트레이 상주 + 별도 이름의 백엔드 자식(vestige-backend.exe)을 띄우므로,
; 기본 "앱 닫기"만으로는 백엔드가 남아 resources\backend\vestige-backend.exe 를 물고 있을 수 있다.
; nsExec::Exec 는 창 없이(hidden) 실행된다.

!macro customInit
  nsExec::Exec 'taskkill /F /IM vestige-backend.exe /T'
  nsExec::Exec 'taskkill /F /IM Vestige.exe /T'
!macroend

!macro customUnInit
  nsExec::Exec 'taskkill /F /IM vestige-backend.exe /T'
  nsExec::Exec 'taskkill /F /IM Vestige.exe /T'
!macroend
