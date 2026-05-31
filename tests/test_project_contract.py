import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_described_core_paths_exist():
    expected = [
        "main.py",
        "chat.py",
        "common/llm_client.py",
        "common/tool_registry.py",
        "common/utils.py",
        "common/tools/travel_tools.py",
        "agents/stage1_react.py",
        "agents/stage2_graph.py",
        "agents/stage3_framework.py",
        "agents/stage4_rag.py",
        "agents/stage5_mcp.py",
        "agents/stage6_grpo.py",
        "api/server.py",
        "docs/CHANGELOG.md",
    ]
    missing = [path for path in expected if not (ROOT / path).exists()]
    assert missing == []


def test_main_help_covers_readme_cli_flags():
    proc = subprocess.run(
        [sys.executable, "main.py", "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
    )
    assert proc.returncode == 0
    help_text = proc.stdout
    for flag in [
        "--stage1",
        "--mode",
        "--mock",
        "--serve",
        "--stage3",
        "--stage4",
        "--chat",
        "--memory",
        "--stage5",
        "--stage6",
        "--stage6-train",
    ]:
        assert flag in help_text


def test_agents_package_uses_lazy_imports():
    code = (
        "import sys, agents\n"
        "print('agents.stage4_rag' in sys.modules)\n"
        "from agents import TravelRewardEngine\n"
        "print(TravelRewardEngine.__name__)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stdout
    lines = proc.stdout.strip().splitlines()
    assert lines == ["False", "TravelRewardEngine"]
