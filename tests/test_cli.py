import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args, timeout=30, stdin_text=None):
    return subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=ROOT,
        input=stdin_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


@pytest.mark.parametrize(
    "args, expected",
    [
        (("--mock", "--stage1", "--mode", "react"), "阶段一"),
        (("--stage6",), "阶段六"),
        (("--stage5",), "阶段五"),
    ],
)
def test_cli_offline_smoke(args, expected):
    proc = run_cli(*args, timeout=40)
    assert proc.returncode == 0, proc.stdout
    assert expected in proc.stdout
    assert "Traceback" not in proc.stdout


def test_cli_chat_memory_local_accepts_readme_command():
    proc = run_cli("--chat", "--mock", "--memory", "local", timeout=20, stdin_text="/exit\n")
    assert proc.returncode == 0, proc.stdout
    assert "本地内存" in proc.stdout
    assert "Traceback" not in proc.stdout


def test_cli_stage4_should_not_require_redis_for_basic_demo():
    proc = run_cli("--stage4", "--query", "我不吃辣，想去成都", timeout=30)
    assert proc.returncode == 0, proc.stdout
    assert "阶段四" in proc.stdout
    assert "Traceback" not in proc.stdout


def test_cli_stage4_memory_local_explicit_mode():
    proc = run_cli("--stage4", "--memory", "local", "--query", "北京三天轻松游", timeout=30)
    assert proc.returncode == 0, proc.stdout
    assert "本地内存" in proc.stdout
    assert "Traceback" not in proc.stdout


def test_cli_stage3_smoke():
    proc = run_cli("--stage3", "--query", "2人北京3天", timeout=35)
    assert proc.returncode == 0, proc.stdout
    assert "阶段三" in proc.stdout
    assert "Traceback" not in proc.stdout
