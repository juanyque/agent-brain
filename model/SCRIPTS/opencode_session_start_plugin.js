import { randomUUID } from "node:crypto"
import { realpathSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const HOOK_SCRIPT = join(
  dirname(realpathSync(fileURLToPath(import.meta.url))),
  "session_start_hook.py",
)
const processedSessions = new Set()

async function resolveBrainContext(directory) {
  try {
    const process = Bun.spawn(
      ["/usr/bin/env", "python3", HOOK_SCRIPT, "--runtime", "opencode"],
      {
        stdin: new Blob([JSON.stringify({ cwd: directory })]),
        stdout: "pipe",
        stderr: "ignore",
      },
    )
    const timeout = setTimeout(() => process.kill(), 5000)
    const [exitCode, stdout] = await Promise.all([
      process.exited,
      new Response(process.stdout).text(),
    ])
    clearTimeout(timeout)
    if (exitCode !== 0) return null

    const payload = JSON.parse(stdout)
    const context = payload?.hookSpecificOutput?.additionalContext
    return typeof context === "string" && context.length > 0 ? context : null
  } catch {
    return null
  }
}

export const BrainSessionStartPlugin = async ({ directory }) => ({
  "chat.message": async (input, output) => {
    if (processedSessions.has(input.sessionID)) return
    processedSessions.add(input.sessionID)

    const context = await resolveBrainContext(directory)
    if (context === null) return
    output.parts.unshift({
      id: `prt_${randomUUID().replaceAll("-", "")}`,
      sessionID: input.sessionID,
      messageID: output.message.id,
      type: "text",
      text: context,
      synthetic: true,
    })
  },
})
