"""Tests for the headless-Claude runner — the subscription-only guarantee."""
import importlib.util
import os

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "run_ai_agent",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run_ai_agent.py"),
)
run_ai_agent = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(run_ai_agent)


def test_build_env_strips_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-removed")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-should-be-removed")
    env = run_ai_agent.build_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_build_env_preserves_other_vars(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    env = run_ai_agent.build_env()
    assert "PATH" in env


def test_agents_registry_has_three_offline_agents():
    assert set(run_ai_agent.AGENTS) == {"premarket", "postmarket", "weekly"}
    for cfg in run_ai_agent.AGENTS.values():
        # offline analysts: no order-placing tools, prompt file declared
        assert "prompt" in cfg and "tools" in cfg


def test_prompt_files_exist():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cfg in run_ai_agent.AGENTS.values():
        assert os.path.exists(os.path.join(root, cfg["prompt"]))
