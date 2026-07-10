"""
Bot supervisor — the API owns the trading loop as a managed subprocess.

Start = spawn `python main.py`; stop = send a graceful "stop" through the command
channel (so the bot squares off in its finally block) and only hard-kill as a last
resort. Pause/resume/square-off are one-line commands on the same channel.

The subprocess handle lives in memory; a pidfile lets a restarted API notice a bot
that is still running and keep controlling it via the channel.
"""
import os
import subprocess
import sys
import time
from typing import Optional

from src.command_channel import CommandChannel
from src.logger import get_logger
from src.ops import get_trading_mode

logger = get_logger("supervisor")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PID_FILE = os.path.join(_REPO_ROOT, "logs", "bot.pid")
_PROC_LOG = os.path.join(_REPO_ROOT, "logs", "bot_process.log")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k = ctypes.windll.kernel32
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if k.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return False
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class BotSupervisor:
    def __init__(self, channel: Optional[CommandChannel] = None):
        self._proc: Optional[subprocess.Popen] = None
        self._channel = channel or CommandChannel()

    # ── lifecycle ───────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        pid = self._read_pid()
        return pid is not None and _pid_alive(pid)

    def start(self) -> dict:
        if self.is_running():
            return {"started": False, "reason": "already_running", "pid": self._read_pid()}
        os.makedirs(os.path.join(_REPO_ROOT, "logs"), exist_ok=True)
        log = open(_PROC_LOG, "a", encoding="utf-8")
        self._proc = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=_REPO_ROOT, stdout=log, stderr=subprocess.STDOUT,
        )
        self._write_pid(self._proc.pid)
        logger.warning(f"bot subprocess started (pid {self._proc.pid})")
        return {"started": True, "pid": self._proc.pid}

    def stop(self, timeout: float = 30.0) -> dict:
        if not self.is_running():
            self._clear_pid()
            return {"stopped": False, "reason": "not_running"}
        self._channel.send("stop")                       # graceful: bot squares off
        pid = self._read_pid()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_running():
                self._clear_pid()
                logger.warning("bot stopped gracefully")
                return {"stopped": True, "graceful": True}
            time.sleep(0.5)
        # last resort — should be rare; graceful path handles square-off
        logger.error("graceful stop timed out — terminating subprocess")
        if self._proc is not None:
            self._proc.terminate()
        elif pid:
            self._terminate_pid(pid)
        self._clear_pid()
        return {"stopped": True, "graceful": False}

    # ── one-shot commands ───────────────────────────────────────────────────────

    def pause(self) -> dict:
        return self._command("pause")

    def resume(self) -> dict:
        return self._command("resume")

    def square_off(self) -> dict:
        return self._command("square_off")

    def _command(self, cmd: str) -> dict:
        if not self.is_running():
            return {"ok": False, "reason": "not_running"}
        self._channel.send(cmd)
        return {"ok": True, "command": cmd}

    # ── state ───────────────────────────────────────────────────────────────────

    def state(self) -> dict:
        return {
            "running": self.is_running(),
            "pid": self._read_pid(),
            "mode": get_trading_mode(),
        }

    # ── pidfile ─────────────────────────────────────────────────────────────────

    def _read_pid(self) -> Optional[int]:
        try:
            with open(_PID_FILE, encoding="utf-8") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def _write_pid(self, pid: int) -> None:
        os.makedirs(os.path.dirname(_PID_FILE), exist_ok=True)
        with open(_PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(pid))

    def _clear_pid(self) -> None:
        try:
            if os.path.exists(_PID_FILE):
                os.remove(_PID_FILE)
        except OSError:
            pass

    @staticmethod
    def _terminate_pid(pid: int) -> None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, check=False)
            else:
                os.kill(pid, 15)
        except OSError as exc:
            logger.error(f"failed to terminate pid {pid}: {exc}")


# One supervisor per API process.
_supervisor: Optional[BotSupervisor] = None


def get_supervisor() -> BotSupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = BotSupervisor()
    return _supervisor
