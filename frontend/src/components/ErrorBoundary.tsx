import { Component, type ReactNode } from "react"
import i18n from "@/i18n"

interface Props { children: ReactNode }
interface State { error: Error | null }

// 뷰 하나가 크래시해도 앱 전체(사이드바 포함)가 하얘지지 않도록 격리 + 오류 표시.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: unknown) {
    // 콘솔에도 남겨 진단 가능하게.
    console.error("[Vestige] view crashed:", error, info)
  }

  reset = () => this.setState({ error: null })

  render() {
    if (this.state.error) {
      return (
        <div role="alert" className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
          <div className="text-lg font-semibold">{i18n.t("error.viewCrashed")}</div>
          <pre className="max-w-full overflow-auto rounded-lg border bg-muted px-3 py-2 text-left text-xs text-destructive">
            {this.state.error.message}
            {"\n\n"}
            {this.state.error.stack?.split("\n").slice(0, 6).join("\n")}
          </pre>
          <button onClick={this.reset}
            className="rounded-lg border bg-card px-3 py-1.5 text-sm hover:bg-muted">{i18n.t("common.retry")}</button>
        </div>
      )
    }
    return this.props.children
  }
}
