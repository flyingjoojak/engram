import type { SchemaReport } from "./api"

// GitHub 이슈 URL(GET) 전체 쿼리 길이 예산. 넘으면 본문에 JSON 대신 '붙여넣기' 안내.
const MAX_QUERY = 7000
const DEFAULT_REPO = "flyingjoojak/vestige"
const REPO_RE = /^[\w.-]+\/[\w.-]+$/

function safeRepo(repo: string | undefined): string {
  return repo && REPO_RE.test(repo) ? repo : DEFAULT_REPO
}

// 리댁트 스키마 지문 → 프리필된 GitHub 이슈 URL. copied=클립보드 복사 성공 여부(본문 안내가 달라짐).
export function buildIssueUrl(report: SchemaReport, reportJson: string, copied: boolean): string {
  const versions = (report.cli_versions ?? []).join(", ") || "?"
  const title = `[schema] ${report.source} 로그 포맷 확인 (${versions})`
  const head =
    `Vestige이 **${report.source}** 로그에서 ${report.drift_suspected ? "대화를 못 읽었어요(포맷 변경 의심)" : "포맷을 신고합니다"}.\n\n` +
    `- Vestige ${report.vestige_version} · cli_versions: ${versions}\n\n`
  const withJson = head + "아래는 대화 내용이 제거된 구조 지문입니다:\n\n```json\n" + reportJson + "\n```\n"
  const encTitle = encodeURIComponent(title)
  const base = `https://github.com/${safeRepo(report.repo)}/issues/new`
  // 인코딩된 실제 길이로 예산 판단(원문 길이가 아니라).
  const encFull = encodeURIComponent(withJson)
  if (encTitle.length + encFull.length <= MAX_QUERY) {
    return `${base}?title=${encTitle}&body=${encFull}`
  }
  const note = copied
    ? "구조 지문(대화 내용 없음)을 클립보드에 복사했습니다 — 여기에 붙여넣어 주세요.\n\n```json\n(붙여넣기)\n```\n"
    : "설정 > 문제 신고에서 신고서 내용을 복사해 여기에 붙여넣어 주세요(대화 내용 없음).\n\n```json\n(붙여넣기)\n```\n"
  return `${base}?title=${encTitle}&body=${encodeURIComponent(head + note)}`
}

export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* 호출부에서 실패로 처리 */ }
  return false
}
