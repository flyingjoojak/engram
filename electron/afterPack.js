// electron-builder afterPack 훅: mac 앱 번들을 ad-hoc 서명한다(#157).
//
// 배경: electron-builder 는 `mac.identity: null` 을 '서명 건너뜀'으로 처리한다. 그러면 링커가
// 남긴 adhoc 서명(실행 바이너리 한정)만 남는데, Apple Silicon 은 그것만으로는 번들 리소스가
// 봉인(CodeResources)되지 않아 Gatekeeper 가 '손상됨'으로 막는다(실기 확인됨).
//
// 여기서 pack 직후(서명·dmg 생성 전) 번들 전체를 `codesign --force --deep --sign -` 로 ad-hoc
// 서명해 리소스를 봉인하면 '손상됨'이 사라진다. README 의 수동 워크어라운드를 빌드 시점에 대신
// 수행하는 것이라, 사용자는 설치 후 아무 명령도 실행할 필요가 없다.
//
// (identity:null 이라 electron-builder 자체 서명 단계는 no-op → 이 afterPack 서명이 최종본으로
//  dmg 에 들어간다. 여전히 Apple 인증서 서명은 아니므로 최초 실행 우클릭→열기 1회는 남는다.)

const { execFileSync } = require("node:child_process");
const path = require("node:path");

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== "darwin") return;
  const appName = context.packager.appInfo.productFilename; // "Vestige"
  const appPath = path.join(context.appOutDir, `${appName}.app`);
  console.log(`[afterPack] mac 번들 ad-hoc 서명: ${appPath}`);
  // --deep: 내부 프레임워크/헬퍼까지, --sign -: ad-hoc, --timestamp=none: 타임스탬프 서버 미접속.
  execFileSync(
    "codesign",
    ["--force", "--deep", "--sign", "-", "--timestamp=none", appPath],
    { stdio: "inherit" },
  );
  // 봉인 검증(실패 시 빌드 중단) — 리소스가 실제로 봉인됐는지 strict 확인.
  execFileSync(
    "codesign",
    ["--verify", "--deep", "--strict", "--verbose=2", appPath],
    { stdio: "inherit" },
  );
  console.log("[afterPack] ad-hoc 서명 + strict 검증 완료");
};
