import type { ReactNode } from "react"

import Claude from "@thesvg/react/claude"
import ClaudeCode from "@thesvg/react/claude-code"
import CodexOpenai from "@thesvg/react/codex-openai"
import Cursor from "@thesvg/react/cursor"
import GithubCopilot from "@thesvg/react/github-copilot"
import GoogleAntigravity from "@thesvg/react/google-antigravity"
import Jetbrains from "@thesvg/react/jetbrains"
import Zed from "@thesvg/react/zed"

const iconProps = {
  className: "ide-chip-icon",
  width: 16,
  height: 16,
  "aria-hidden": true as const,
}

export const IDES: { name: string; icon: ReactNode }[] = [
  { name: "Cursor", icon: <Cursor {...iconProps} variant="mono" /> },
  { name: "VS Code Copilot", icon: <GithubCopilot {...iconProps} variant="mono" /> },
  { name: "Google Antigravity", icon: <GoogleAntigravity {...iconProps} /> },
  { name: "Claude Desktop", icon: <Claude {...iconProps} variant="mono" /> },
  { name: "Claude Code", icon: <ClaudeCode {...iconProps} variant="mono" /> },
  { name: "OpenAI Codex", icon: <CodexOpenai {...iconProps} variant="mono" /> },
  {
    name: "Devin Desktop",
    icon: (
      // Official Devin symbol from https://devin.ai/brand
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src="/logos/devin-symbol.svg"
        alt=""
        width={16}
        height={16}
        className="ide-chip-icon"
        aria-hidden="true"
      />
    ),
  },
  { name: "JetBrains", icon: <Jetbrains {...iconProps} variant="mono" /> },
  { name: "Zed", icon: <Zed {...iconProps} variant="light" /> },
]
