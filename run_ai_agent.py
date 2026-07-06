"""
Headless Claude runner — the ONLY way the AI touches this project.

Design guarantees (per the V2 plan):
- Uses Claude Code headless mode (`claude -p`), which is covered by your Claude
  Pro/Max subscription — NOT the pay-as-you-go Anthropic API.
- CRITICAL: strips ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN from the child
  environment so a stray key in .env can never silently switch the run to
  per-token API billing.
- Runs OFFLINE, on a schedule (Task Scheduler). Never in the live order path —
  it only reads logs and writes bounded proposal files that the bot validates.

Usage:
    python run_ai_agent.py {premarket|postmarket|weekly}
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

AGENTS = {
    "premarket":  {"prompt": "ai/prompts/premarket_strategist.md", "tools": "Read,Write,Bash"},
    "postmarket": {"prompt": "ai/prompts/postmarket_analyst.md",   "tools": "Read,Write,Bash"},
    "weekly":     {"prompt": "ai/prompts/weekly_researcher.md",    "tools": "Read,Write,Bash"},
    "backtest":   {"prompt": "ai/prompts/backtest_analyst.md",     "tools": "Read,Write,Bash"},
    "tune":       {"prompt": "ai/prompts/tuning_reviewer.md",      "tools": "Read,Write,Bash"},
}


def build_env() -> dict:
    """Child env that forces subscription billing, never API billing."""
    env = os.environ.copy()
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        if env.pop(key, None) is not None:
            print(f"[run_ai_agent] removed {key} from child env — using subscription")
    return env


def find_claude() -> str:
    for name in ("claude", "claude.cmd", "claude.exe"):
        path = shutil.which(name)
        if path:
            return path
    # PATH may not be refreshed after install — check the managed install location.
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, ".local", "bin", "claude.exe"),
                 os.path.join(home, ".local", "bin", "claude")):
        if os.path.exists(cand):
            return cand
    print("ERROR: 'claude' CLI not found on PATH. Install Claude Code and sign in "
          "with your subscription (claude login).")
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in AGENTS:
        print("usage: python run_ai_agent.py {premarket|postmarket|weekly}")
        sys.exit(1)

    agent = AGENTS[sys.argv[1]]
    prompt_path = os.path.join(ROOT, agent["prompt"])
    with open(prompt_path, encoding="utf-8") as f:
        prompt = f.read()

    claude = find_claude()
    cmd = [claude, "-p", prompt, "--allowedTools", agent["tools"]]
    print(f"[run_ai_agent] launching '{sys.argv[1]}' agent (tools: {agent['tools']})")
    result = subprocess.run(cmd, env=build_env(), cwd=ROOT)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
