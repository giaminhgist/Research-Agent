"""Entry point for Research-Agent hooks: `python dispatch.py <Event>` with the hook JSON on stdin."""

import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("CLAUDE_PLUGIN_ROOT", str(ROOT))


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        from research_agent.hooks import handle

        out = handle(event, payload)
        if out:
            sys.stdout.write(json.dumps(out))
    except Exception:  # a broken hook must never block Claude Code; log and continue
        try:
            from research_agent import paths

            log = paths.ra_home() / "hook-errors.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as fh:
                fh.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {event}\n{traceback.format_exc()}\n")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
