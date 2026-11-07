"""Runs the parser on a stranger's file, as if it could turn against us (section 10 of CLAUDE.md).

No shell and an empty environment, so it holds no secret. Its own folder, its own process group
killed at the deadline, and limits on memory, CPU, file size and open files. The container adds what
a process cannot do for itself: another user, a read-only root, no capabilities.

Limits are set with `preexec_fn`, which is only safe with no other thread running: the worker
therefore scales with processes, never with threads.
"""

import contextlib
import math
import os
import resource
import signal
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_STDERR_MAX_BYTES = 4096
_STDERR_FILE = ".stderr"
_OPEN_FILES_MAX = 64
_CPU_GRACE_S = 5


@dataclass(frozen=True)
class Limits:
    timeout_s: float
    memory_mb: int
    output_mb: int = 1024


@dataclass(frozen=True)
class Result:
    """`exit_code` is None when it was killed at the deadline, and negative for a signal."""

    exit_code: int | None
    timed_out: bool
    stderr: bytes
    duration_s: float


def _set_limits(limits: Limits) -> None:
    memory = limits.memory_mb * 1024 * 1024
    output = limits.output_mb * 1024 * 1024
    # A backstop for what the deadline would miss: it counts CPU time, not waiting.
    cpu = math.ceil(limits.timeout_s) + _CPU_GRACE_S
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (output, output))
    resource.setrlimit(resource.RLIMIT_NOFILE, (_OPEN_FILES_MAX, _OPEN_FILES_MAX))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run(binary: str | Path, arguments: Sequence[str], workdir: Path, limits: Limits) -> Result:
    """Runs `binary` in `workdir`, which must be its own: paths are relative to it."""
    stderr_path = workdir / _STDERR_FILE
    started = time.monotonic()
    with stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            [str(binary), *arguments],
            env={},
            cwd=workdir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
            close_fds=True,
            start_new_session=True,
            preexec_fn=lambda: _set_limits(limits),
        )
    timed_out = False
    try:
        exit_code: int | None = process.wait(timeout=limits.timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = None
    finally:
        # Also when it ended by itself: nothing it started may outlive it.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    with stderr_path.open("rb") as stderr_file:
        captured = stderr_file.read(_STDERR_MAX_BYTES)
    stderr_path.unlink()
    return Result(exit_code, timed_out, captured, time.monotonic() - started)
