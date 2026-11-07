"""The sandbox against programs that misbehave. Needs no database, only a POSIX system."""

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

from ma_worker.sandbox import Limits, run

LIMITS = Limits(timeout_s=10, memory_mb=1024)


def program(path: Path, body: str, *, shell: bool = True) -> Path:
    interpreter = "/bin/sh" if shell else sys.executable
    target = path / "program"
    target.write_text(f"#!{interpreter}\n{body}\n", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IEXEC)
    return target


def alive(pid: int) -> bool:
    """A zombie is dead: only its parent's bookkeeping is left."""
    try:
        status = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    return status.rsplit(")", 1)[1].split()[0] != "Z"


def eventually_dead(pid: int) -> bool:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.02)
    return False


def test_a_program_that_works(tmp_path: Path) -> None:
    binary = program(tmp_path, 'echo "$1" > output.txt')
    result = run(binary, ["hello"], tmp_path, LIMITS)
    assert result.exit_code == 0
    assert result.timed_out is False
    assert (tmp_path / "output.txt").read_text(encoding="utf-8") == "hello\n"


def test_its_exit_code_comes_back(tmp_path: Path) -> None:
    assert run(program(tmp_path, "exit 12"), [], tmp_path, LIMITS).exit_code == 12


def test_its_error_output_comes_back(tmp_path: Path) -> None:
    binary = program(tmp_path, 'echo \'{"code":"corrupt"}\' >&2; exit 11')
    result = run(binary, [], tmp_path, LIMITS)
    assert result.stderr == b'{"code":"corrupt"}\n'


def test_its_error_output_cannot_flood_the_worker(tmp_path: Path) -> None:
    binary = program(tmp_path, "head -c 5000000 /dev/zero >&2")
    assert len(run(binary, [], tmp_path, LIMITS).stderr) == 4096


def test_it_leaves_no_file_of_ours_behind(tmp_path: Path) -> None:
    run(program(tmp_path, "exit 0"), [], tmp_path, LIMITS)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["program"]


def test_an_endless_loop_is_killed_on_time(tmp_path: Path) -> None:
    binary = program(tmp_path, "while :; do :; done")
    result = run(binary, [], tmp_path, Limits(timeout_s=1, memory_mb=1024))
    assert result.timed_out is True
    assert result.exit_code is None
    assert 0.9 < result.duration_s < 3


def test_a_program_that_only_waits_is_killed_on_time(tmp_path: Path) -> None:
    """The CPU limit would never catch this one: the deadline has to."""
    binary = program(tmp_path, "sleep 300")
    result = run(binary, [], tmp_path, Limits(timeout_s=1, memory_mb=1024))
    assert result.timed_out is True
    assert result.duration_s < 3


def test_what_it_started_dies_at_the_deadline(tmp_path: Path) -> None:
    binary = program(tmp_path, "sleep 300 &\necho $! > child.pid\nwhile :; do :; done")
    run(binary, [], tmp_path, Limits(timeout_s=1, memory_mb=1024))
    assert eventually_dead(int((tmp_path / "child.pid").read_text(encoding="utf-8")))


def test_what_it_started_does_not_outlive_it(tmp_path: Path) -> None:
    binary = program(tmp_path, "sleep 300 &\necho $! > child.pid\nexit 0")
    result = run(binary, [], tmp_path, LIMITS)
    assert result.exit_code == 0
    assert eventually_dead(int((tmp_path / "child.pid").read_text(encoding="utf-8")))


def test_memory_is_limited(tmp_path: Path) -> None:
    body = "import sys\ntry:\n    bytearray(1024 ** 3)\nexcept MemoryError:\n    sys.exit(42)"
    binary = program(tmp_path, body, shell=False)
    assert run(binary, [], tmp_path, Limits(timeout_s=10, memory_mb=256)).exit_code == 42
    # The same program goes through with more room: the limit is what stopped it.
    assert run(binary, [], tmp_path, Limits(timeout_s=10, memory_mb=4096)).exit_code == 0


def test_the_environment_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
    body = "import json, os\njson.dump(dict(os.environ), open('env.json', 'w'))"
    assert run(program(tmp_path, body, shell=False), [], tmp_path, LIMITS).exit_code == 0
    env = json.loads((tmp_path / "env.json").read_text(encoding="utf-8"))
    assert "secret" not in json.dumps(env)
    # Python sets this one for itself in an empty environment.
    assert set(env) <= {"LC_CTYPE"}


def test_arguments_are_not_interpreted_by_a_shell(tmp_path: Path) -> None:
    binary = program(tmp_path, 'printf "%s" "$1" > output.txt')
    trap = "$(touch pwned); touch pwned2"
    run(binary, [trap], tmp_path, LIMITS)
    assert (tmp_path / "output.txt").read_text(encoding="utf-8") == trap
    assert not (tmp_path / "pwned").exists()
    assert not (tmp_path / "pwned2").exists()


def test_it_cannot_read_stdin(tmp_path: Path) -> None:
    binary = program(tmp_path, 'read -r line; echo "[$line]" > output.txt')
    run(binary, [], tmp_path, LIMITS)
    assert (tmp_path / "output.txt").read_text(encoding="utf-8") == "[]\n"


def test_it_cannot_write_a_huge_file(tmp_path: Path) -> None:
    binary = program(tmp_path, "head -c 3000000 /dev/zero > big.bin")
    result = run(binary, [], tmp_path, Limits(timeout_s=10, memory_mb=1024, output_mb=1))
    assert result.exit_code != 0
    assert (tmp_path / "big.bin").stat().st_size <= 1024 * 1024


def test_core_dumps_are_off(tmp_path: Path) -> None:
    binary = program(tmp_path, "ulimit -c > core.txt")
    run(binary, [], tmp_path, LIMITS)
    assert (tmp_path / "core.txt").read_text(encoding="utf-8").strip() == "0"


def test_a_signal_shows_as_a_negative_code(tmp_path: Path) -> None:
    binary = program(tmp_path, "kill -SEGV $$")
    assert run(binary, [], tmp_path, LIMITS).exit_code == -11


def test_it_runs_in_its_folder(tmp_path: Path) -> None:
    binary = program(tmp_path, "pwd > where.txt")
    run(binary, [], tmp_path, LIMITS)
    assert (tmp_path / "where.txt").read_text(encoding="utf-8").strip() == os.path.realpath(
        tmp_path
    )


def test_a_missing_binary_is_our_fault_not_the_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run(tmp_path / "nothing-here", [], tmp_path, LIMITS)
