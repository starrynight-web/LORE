import type { Metadata } from "next"
import Link from "next/link"

import { DocShell } from "@/components/doc-shell"

export const metadata: Metadata = {
  title: "IDE MCP Setup — LORE",
  description: "Connect Lore Solo or LORE Enterprise to Cursor, VS Code, Claude, JetBrains, Zed, and more.",
}

export default function IdeMcpPage() {
  return (
    <DocShell
      eyebrow="Documentation"
      title="IDE MCP Setup"
      description="Lore runs as a local MCP server over stdio. Always register distinct server keys so IDE schema caches never collide: lore-solo vs lore-enterprise-mcp."
      githubHref="https://github.com/starrynight-web/LORE/blob/main/docs/ide/README.md"
    >
      <div className="doc-meta">
        <span className="icon-box lime">stdio</span>
        <span className="icon-box">9+ IDEs</span>
        <span className="icon-box lime">Distinct keys</span>
      </div>
      <h2>Lore Solo</h2>
      <ul>
        <li>
          Install: <code>uvx --managed-python --python 3.12 --no-build lore-solo==0.2.9 install</code>
        </li>
        <li>
          Auto-connect: <code>lore-solo connect</code>
        </li>
        <li>
          Manual key: <code>lore-solo</code> → <code>uvx lore-solo mcp</code>
        </li>
      </ul>
      <h2>LORE Enterprise</h2>
      <ul>
        <li>
          Clone the <Link href="/branches/enterprise">enterprise</Link> branch and install backend requirements
        </li>
        <li>
          Verify with <code>python mcp_server.py --list-tools</code>
        </li>
        <li>
          Register key <code>lore-enterprise-mcp</code> pointing at <code>mcp_server.py</code>
        </li>
      </ul>
      <h2>Supported harnesses</h2>
      <p>
        Cursor, VS Code Copilot, Google Antigravity, Claude Desktop, Claude Code, OpenAI Codex, Devin Desktop,
        JetBrains, and Zed — each with a guide under <code>docs/ide/</code> on main.
      </p>
      <p>
        Guide index:{" "}
        <a href="https://github.com/starrynight-web/LORE/blob/main/docs/ide/README.md" target="_blank" rel="noreferrer">
          docs/ide/README.md
        </a>
      </p>
    </DocShell>
  )
}
