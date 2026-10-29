"""Headless Research-Agent runs through the Claude Agent SDK (`ra run`).

In headless mode nobody can answer an approval prompt, so every guard "ask" becomes a deny and is written to
.research-agent/approvals/pending.md for the user to review afterwards.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from . import config, guard
from .approvals import ApprovalStore

HEADLESS_RULES = """You are running headless (no human present). Rules:
- Any action that needs approval will be denied and logged to .research-agent/approvals/pending.md. Do not retry
  variants of a denied action; record it as an open issue and continue with what you can do.
- Do not ask the user questions; make the conservative choice, record it with `ra memory decide`, and continue.
- Do not promote knowledge to the global knowledge base; leave the queue for the user.
- Stop when the loop reports a stop reason or the budget is reached, and write a final report."""


def build_options(goal: str, loop: str, budget_usd: float, max_turns: int, project: Path) -> dict:
    cfg = config.load(project)
    cap = float(config.get(cfg, "budget.max_usd_per_session", budget_usd))
    return {
        "prompt": f"/research-agent:ra {goal} --loop {loop}",
        "system_prompt": {"type": "preset", "preset": "claude_code", "append": HEADLESS_RULES},
        "max_budget_usd": min(float(budget_usd), cap),
        "max_turns": int(max_turns),
        "permission_mode": "default",
        "cwd": str(project),
        "setting_sources": ["user", "project", "local"],
    }


def permission_callback(project: Path, cfg: dict | None):
    project = Path(project)
    cfg = cfg if cfg is not None else config.load(project)
    store = ApprovalStore(project)

    def decide(tool_name: str, tool_input: dict, agent: str | None = None) -> tuple[str, str]:
        d = guard.evaluate(tool_name, tool_input, project, cfg, project, agent=agent, approvals=store)
        if d.action == "allow":
            return "allow", ""
        if d.action == "ask":
            target = str(tool_input.get("command") or tool_input.get("file_path") or tool_name)
            store.request(d.rule, target, d.reason, headless=True)
            return "deny", f"[research-agent:{d.rule}] needs human approval (logged to approvals/pending.md): {d.reason}"
        return "deny", f"[research-agent:{d.rule}] {d.reason}"

    return decide


def run(goal: str, loop: str, budget_usd: float, max_turns: int, project: Path, dry_run: bool = False) -> int:
    opts = build_options(goal, loop, budget_usd, max_turns, project)
    if dry_run:
        print(json.dumps(opts, indent=2))
        return 0
    try:
        from claude_agent_sdk import (ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,  # noqa: PLC0415
                                      PermissionResultDeny)
    except ImportError:
        print("claude-agent-sdk is not installed. Install it with: pip install claude-agent-sdk "
              "(or `pip install research-agent[sdk]`).")
        return 2
    decide = permission_callback(project, None)

    async def can_use_tool(tool_name, tool_input, context):
        action, msg = decide(tool_name, tool_input)
        return PermissionResultAllow() if action == "allow" else PermissionResultDeny(message=msg)

    prompt = opts.pop("prompt")
    options = ClaudeAgentOptions(**opts, can_use_tool=can_use_tool)

    async def main() -> int:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                for block in getattr(msg, "content", []) or []:
                    text = getattr(block, "text", None)
                    if text:
                        print(text, flush=True)
                if type(msg).__name__ == "ResultMessage":
                    cost = getattr(msg, "total_cost_usd", None)
                    print(f"\n[research-agent] finished: {getattr(msg, 'subtype', '')}, cost ${cost or 0:.2f}")
        return 0

    return asyncio.run(main())
