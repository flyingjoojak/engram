# Security Policy

Vestige runs entirely on your own machine, but it still has a real attack surface -
a local HTTP server, endpoints that can launch OS processes, an optional peer-to-peer
sync engine, and an auto-update mechanism. We take reports about these seriously.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private vulnerability reporting instead:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe the issue, steps to reproduce, and impact.

This keeps the report private between you and the maintainer until a fix is ready.
This is a small, single-maintainer project, so responses are best-effort - but security
reports are prioritized.

## In scope

- The local API server (`vestige web`) - CSRF / DNS-rebinding, request forgery, auth bypass.
- Command-executing endpoints (e.g. session resume, which spawns a terminal) - injection or path issues.
- The MCP server exposing local conversation data.
- Device sync (bundled Syncthing) and the SHA-256 verification of the downloaded binary.
- The auto-update path (electron-updater) and release-artifact integrity.
- Handling of the local config file that may contain API keys.

## Out of scope

- Attacks requiring an already-compromised machine or physical access.
- Vulnerabilities in third-party dependencies themselves (report those upstream; see
  [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)). We will still update the pinned
  version once a fix is available upstream.
- The absence of code signing on installers (known and documented, not a vulnerability).

## Supported versions

Only the latest released version receives security fixes.
