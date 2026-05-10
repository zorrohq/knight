/**
 * Knight plan mode pi extension.
 *
 * Loaded via `pi -e ./knight/agents/plan_extension.ts` only when
 * execution_mode == "plan". It:
 *
 * 1. Injects a planning system prompt (before_agent_start).
 * 2. Blocks write/edit calls to non-markdown files (tool_call).
 * 3. Registers the `knight_plan_done` tool — agent calls it after writing
 *    PLAN.md. The tool reads the file and returns terminate: true so pi stops.
 *
 * After pi exits, Knight reads PLAN.md from the worktree path.
 *
 * Imports: node builtins + typebox (bundled with pi) + @earendil-works/pi-coding-agent.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI): void {
  // ---------------------------------------------------------------------------
  // 1. Inject planning system prompt
  // ---------------------------------------------------------------------------
  pi.on("before_agent_start", (_event, ctx) => {
    const existing = ctx.getSystemPrompt();
    const planningOverride = `${existing}

---

## IMPORTANT: You are in PLANNING MODE

Your ONLY job is to analyse the codebase and write a structured plan to PLAN.md.

**Allowed tools:** read, bash (read-only commands only: grep, find, cat, git log, git diff), write (PLAN.md only), edit (PLAN.md only)
**Forbidden:** write or edit any file that is not PLAN.md, bash commands that modify the filesystem.

### Required plan structure (write exactly these sections to PLAN.md)

\`\`\`markdown
## Scope
What will change and what will not change.

## Files to Modify
- path/to/file.py — one-line description of change
- …

## Implementation Approach
Step-by-step description of the implementation.

## Edge Cases and Risks
Non-obvious issues, compatibility concerns, things to watch out for.
\`\`\`

When your plan is complete and written to PLAN.md, call the \`knight_plan_done\` tool with \`filePath\` set to \`PLAN.md\`. Do not call it before you have finished writing the plan.
`;
    return { systemPrompt: planningOverride };
  });

  // ---------------------------------------------------------------------------
  // 2. Block write/edit to non-markdown files
  // ---------------------------------------------------------------------------
  pi.on("tool_call", (event) => {
    if (event.toolName !== "write" && event.toolName !== "edit") return;

    const filePath: string = (event.input as { path?: string }).path ?? "";
    const lower = filePath.toLowerCase();
    const isMd = lower.endsWith(".md") || lower.endsWith(".mdx");

    if (!isMd) {
      return {
        block: true,
        reason:
          "Write/edit is not allowed in planning mode. " +
          "Only PLAN.md may be written. Explore files with read/bash instead.",
      };
    }
  });

  // ---------------------------------------------------------------------------
  // 3. Register knight_plan_done tool
  // ---------------------------------------------------------------------------
  pi.registerTool({
    name: "knight_plan_done",
    label: "Submit plan",
    description:
      "Call this tool when your plan is complete and fully written to PLAN.md. " +
      "Pass the path to the plan file (typically 'PLAN.md'). " +
      "Knight will read the file and post it for user review. " +
      "Calling this tool ends the planning session immediately.",
    parameters: Type.Object({
      filePath: Type.String({
        description: "Path to the completed plan markdown file (e.g. 'PLAN.md').",
      }),
    }),
    execute: async (_toolCallId, params, _signal, _onUpdate, ctx) => {
      const absolutePath = resolve(ctx.cwd, params.filePath);
      let planText: string;
      try {
        planText = readFileSync(absolutePath, "utf-8");
      } catch (err) {
        return {
          content: [
            {
              type: "text" as const,
              text: `Error reading plan file at ${absolutePath}: ${err instanceof Error ? err.message : String(err)}. Write the plan to PLAN.md first, then call this tool.`,
            },
          ],
          details: null,
        };
      }

      if (!planText.trim()) {
        return {
          content: [
            {
              type: "text" as const,
              text: "Plan file is empty. Write the plan content to PLAN.md first, then call this tool.",
            },
          ],
          details: null,
        };
      }

      return {
        content: [
          {
            type: "text" as const,
            text: `Plan captured (${planText.length} chars). Knight will post it for user review.`,
          },
        ],
        details: null,
        terminate: true,
      };
    },
  });
}
