<div align="center">

<img src="docs/assets/banner.png" alt="Engram" width="100%">

### Your AI coding assistant forgets everything. Now you don't have to.

[![License: MIT](https://img.shields.io/badge/license-MIT-10b981.svg)](LICENSE)
![Platforms](https://img.shields.io/badge/Windows%20%7C%20macOS%20%7C%20Linux-1f2937)
![Local & Offline](https://img.shields.io/badge/100%25-local%20%26%20offline-10b981)
![Built with](https://img.shields.io/badge/Python%20·%20React%20·%20Electron-47848F)

**English** · [한국어](README.ko.md)

</div>

You've solved hundreds of problems with **Claude Code** and **Codex** - that gnarly async bug, the exact
Docker config, the prompt that finally worked. Then the session closes and it's gone. Next time you
need it, you scroll through endless history, or just ask again from scratch.

**Engram is the long-term memory your AI assistant doesn't have.** It keeps every conversation
on your own machine, in the background, and lets you find any of them in a second - by meaning, not just keywords.

<div align="center">
  <img src="docs/assets/search.png" alt="Searching past conversations in Engram - type what you remember and the exact answer comes back" width="880">
</div>

<!-- Want a playable demo video too? Drag an .mp4 into a GitHub issue/release, then paste the
     github.com/user-attachments/... URL on its own line here. (Record on demo data - see docs/assets/README.md.) -->

## What changes for you

| Before Engram | With Engram |
|---|---|
| You know you fixed this before, but that chat is gone. | You **find the exact conversation in seconds.** |
| You re-ask Claude the same question and burn tokens. | You **reuse the answer you already got.** |
| You only find it if you remember the exact words. | You **search by a vague memory** - "that flaky websocket test fix" lands the right message. |
| Your history is scattered across hundreds of sessions. | You **see it all on one 3D map**, clustered by topic. |
| Cloud tools read your conversations. | **Nothing leaves your machine.** No account, no cloud. |

## Features

- 🔍 **Search that reads your mind** - finds by meaning, so half-remembered ideas still land the exact message (semantic + keyword, together).
- ⚡ **Instant recall** - every Claude Code & Codex conversation in one search box. No more scrolling or re-asking.
- 🗺️ **A map of your work** - a 3D view clusters everything you've done into topics you can fly through.
- 🔒 **100% local & offline** - runs entirely on your computer. No account, no telemetry, works on a plane.
- ↔️ **One memory across devices** - your laptop and desktop stay in sync, peer-to-peer (no cloud).
- 🤖 **Give your AI its memory back** - via MCP, Claude can search its own past sessions for you.

## See it in action

**A 3D map of everything you've discussed** - your history clustered into topics you can fly through.

<div align="center">
  <img src="docs/assets/map.gif" alt="Engram's rotating 3D semantic map, with conversations clustered into labeled topics" width="880">
</div>

**Every session, one click away** - grouped, timestamped, and searchable.

<div align="center">
  <img src="docs/assets/sessions.png" alt="Engram's session browser listing past conversations" width="880">
</div>

## Download

> **Platform status:** **Windows** and **macOS** are built and tested on real hardware. **Linux** builds are produced automatically but **haven't been tested on real hardware yet**, so it may not work smoothly. If something breaks, please [open an issue](https://github.com/flyingjoojak/engram/issues) and I'll fix it.

Builds land on the [**Releases**](https://github.com/flyingjoojak/engram/releases) page.

### 🪟 Windows - verified

1. Download `Engram-Setup-<version>.exe` and run it.
2. If Windows shows a "protected your PC" warning, click **More info → Run anyway**. (It's just because the app isn't code-signed yet - it's safe.)

### 🍎 macOS - Homebrew recommended

```bash
brew tap flyingjoojak/engram https://github.com/flyingjoojak/engram
brew install --cask flyingjoojak/engram/engram
```

Homebrew removes the quarantine flag for you, so there's no Gatekeeper warning, and `brew upgrade --cask engram` keeps it up to date.

**Prefer the `.dmg`?** Download it from [Releases](https://github.com/flyingjoojak/engram/releases), drag **Engram** to Applications, then remove the quarantine flag (the app isn't code-signed yet):

```bash
xattr -dr com.apple.quarantine /Applications/Engram.app
```

Then open it normally. (Or right-click the app → **Open** the first time.)

### 🐧 Linux - not tested yet

Download the `.AppImage`, make it executable with `chmod +x`, and run it.

**First launch:** pick an embedding model (a lightweight option is offered for slower machines) and you're set. Engram then indexes your conversations in the background; use the left rail for **Search · Sessions · 3D map · Settings**.

## How it works

Engram watches the logs Claude Code and Codex **already write on your machine**, so there's nothing to set up.

```
Claude Code / Codex logs  →  read incrementally  →  conversations (question + answer + actions)
      →  local embeddings (multilingual e5-large)  →  SQLite archive + vector index
      →  hybrid search: meaning ⊕ keywords
```

Everything Claude Code and Codex log is indexed by default. If you run `claude -p` automation (CI, cron, git
hooks) and want those one-shot sessions kept out, set `ENGRAM_SKIP_SDK_SESSIONS=1` - it drops SDK-driven
prompts. It's off by default because SDK-driven doesn't always mean throwaway (some people work through the SDK).

Your **raw conversations are the source of truth**; the search index is just a regenerable derivative, so
re-indexing or switching models is always lossless. Design notes: [SPEC.md](SPEC.md).

---

<details>
<summary><b>🔐  Privacy - what stays, what can leave</b></summary>

<br>

By default **everything is local** and nothing is sent anywhere. Data leaves your device **only via three features you turn on yourself:**

1. **Cloud summaries** - if you use a cloud AI for optional summaries (`claude` subscription, Anthropic, OpenAI, or Gemini), parts of conversations go to that provider. Only `ollama` (local) and `off` send nothing.
2. **Device sync** - connecting devices syncs logs **peer-to-peer between your own machines**, encrypted, through no third-party server. The bundled Syncthing binary is verified via SHA-256.
3. **MCP** - a tool you register can search/view your local conversations; if it's a cloud model, returned text may reach that model.

No telemetry, no usage stats, no automatic error reports. The “report an issue” feature sends only a masked format fingerprint - never conversation content.

</details>

<details>
<summary><b>⌨️  For developers - CLI &amp; source install</b></summary>

<br>

Engram is built on a Python core with a thin CLI. Install from source:

```bash
git clone https://github.com/flyingjoojak/engram.git && cd engram
pip install ".[web]"          # core + web UI.  Everything: ".[all]"  ·  dev: pip install -e ".[all]"
engram setup                 # folders, config, and a scheduler that auto-indexes every 10 min
```

Or with [pipx](https://pipx.pypa.io):

```bash
pipx install "engram[web] @ git+https://github.com/flyingjoojak/engram.git"
engram setup
```

```bash
mem "how did I write the payroll calc logic"   # search from the terminal
engram web                            # web UI → http://127.0.0.1:8642
engram search "..." -k 10 --since 2026-07-01 --session growth
engram stats | config | progress                 # status · config · progress
```

> Extras: `[web]` web UI · `[enrich]` cloud/local summary backends · `[mcp]` MCP server · `[all]` everything.
> (The command is `engram`, alias `mem`; data lives in `~/engram/data`.)

</details>

<details>
<summary><b>✨  Optional summaries - pluggable backends</b></summary>

<br>

Summaries/tags are **optional** (search runs on the raw text). Pick a backend via `ENGRAM_ENRICH_BACKEND`:

| Backend | Description | Requirements |
|--------|------|-----------|
| `claude` (default) | Claude Code subscription (`claude -p`) | Claude Code installed & logged in |
| `anthropic` / `openai` / `gemini` | Cloud APIs | that SDK + API key |
| `ollama` | Local model (offline, free) | Ollama running |
| `off` | No summaries (raw search only) | none |

`openai`/`gemini`/`ollama` all speak the OpenAI-compatible API (LM Studio, vLLM, Groq, … work too).

> On macOS the app is launched from Finder and doesn't inherit your shell `PATH`, so it may not find the `claude` CLI even when it's installed. Engram looks in the usual spots (`/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin`, …); if yours lives elsewhere, point at it with `ENGRAM_CLAUDE_BIN=/full/path/to/claude`.

```bash
ENGRAM_ENRICH_BACKEND=ollama ENGRAM_OLLAMA_MODEL=llama3.1 engram enrich   # local, zero leakage
```

</details>

<details>
<summary><b>🤖  MCP server - let other AIs search your past conversations</b></summary>

<br>

Registering the MCP server lets Claude Code, Desktop, etc. **search and view** your sessions (local hybrid search → raw text + summary).

> **Easiest:** in the app, **Settings → MCP integration**, use the register buttons per target.

```bash
claude mcp add engram -- engram-mcp
```

```json
{ "mcpServers": { "engram": { "command": "engram-mcp" } } }
```

Tools: `search_memory` · `get_session` · `recent_sessions` · `stats`.

</details>

<details>
<summary><b>🚀  Release &amp; versioning (maintainers)</b></summary>

<br>

Pushing a tag (`vX.Y.Z`) makes GitHub Actions build the Windows/Linux/macOS installers and attach them to the release (with `latest.yml` for auto-update):

1. Bump `version` in `electron/package.json`, summarize changes in `CHANGELOG.md`.
2. `git tag v0.2.0 && git push origin v0.2.0`.
3. **The release body shows in the app's update banner** - split it with `<!--lang:en-->` / `<!--lang:ko-->` markers and the banner shows the section matching the user's language.

macOS: unsigned apps can't auto-update, so install/update via **Homebrew** (no Gatekeeper warning). Windows auto-updates from the banner even while unsigned.

</details>

## Contributing

The most valuable contribution is **teaching Engram to read a new tool's logs** (Aider, Cursor,
Gemini CLI, …). It's a single self-contained adapter file - the search, map, and storage pipeline
stay untouched. See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the four-method contract, a worked
example, and the security rules for adapters.

## License

**MIT** - see [LICENSE](LICENSE). Engram bundles the [Syncthing](https://syncthing.net/) (MPL-2.0) engine for device sync; other third-party licenses are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

<div align="center"><br><sub>Built for people who talk to their AI all day - and want to remember what they said.</sub><br><sub>Built with <a href="https://claude.com/claude-code">Claude Code</a>.</sub></div>
