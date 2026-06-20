"""
Tests for src/classify.py.

The single LLM call is mocked — these check the wiring around it: that we
send the right request and correctly pull the structured result back out.
"""

import io
import sys

import pytest

import classify

# --- label sets / tool schema stay in sync -------------------------------


def test_tool_schema_enums_match_label_constants():
    props = classify.CLASSIFY_TOOL["input_schema"]["properties"]
    assert props["category"]["enum"] == classify.CATEGORIES
    assert props["operational_domain"]["enum"] == classify.DOMAINS


def test_tool_requires_both_fields():
    required = classify.CLASSIFY_TOOL["input_schema"]["required"]
    assert set(required) == {"category", "operational_domain"}


# --- classify() ----------------------------------------------------------


def test_classify_returns_tool_input(tool_client):
    client = tool_client({"category": "procurement", "operational_domain": "air"})
    result = classify.classify(client, "Pentagon awards F-35 contract.")
    assert result == {"category": "procurement", "operational_domain": "air"}


def test_classify_skips_non_tool_blocks(tool_client):
    # A leading text block must be ignored; the tool_use block is what counts.
    from conftest import make_text_block

    client = tool_client(
        {"category": "operations", "operational_domain": "sea"},
        extra_blocks=[make_text_block("thinking out loud")],
    )
    result = classify.classify(client, "Carrier group deploys to the strait.")
    assert result["category"] == "operations"


def test_classify_sends_expected_request(tool_client):
    client = tool_client({"category": "policy", "operational_domain": "multi"})
    classify.classify(client, "New defense strategy published.")

    kwargs = client.messages.last_kwargs
    assert kwargs["model"] == classify.MODEL
    assert kwargs["system"] == classify.SYSTEM_PROMPT
    # Tool use is forced so the model can't return free text instead.
    assert kwargs["tool_choice"] == {"type": "tool", "name": "classify_article"}
    assert kwargs["messages"] == [
        {"role": "user", "content": "New defense strategy published."}
    ]


# --- make_client() -------------------------------------------------------


def test_make_client_raises_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(EnvironmentError):
        classify.make_client()


def test_make_client_builds_with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = classify.make_client()
    # Don't assert on SDK internals — just that we got a client object back.
    assert client is not None


# --- main() (CLI entry point) --------------------------------------------


def test_main_classifies_text_from_argv(monkeypatch, capsys):
    monkeypatch.setattr(classify, "make_client", lambda: object())
    monkeypatch.setattr(
        classify,
        "classify",
        lambda _c, _t: {"category": "policy", "operational_domain": "multi"},
    )
    monkeypatch.setattr(sys, "argv", ["classify.py", "New", "defense", "strategy"])

    classify.main()

    out = capsys.readouterr().out
    assert '"category": "policy"' in out
    assert '"operational_domain": "multi"' in out


def test_main_reads_from_stdin_when_no_argv(monkeypatch, capsys):
    monkeypatch.setattr(classify, "make_client", lambda: object())
    monkeypatch.setattr(
        classify,
        "classify",
        lambda _c, _t: {"category": "operations", "operational_domain": "air"},
    )
    monkeypatch.setattr(sys, "argv", ["classify.py"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("Air strikes reported.\n"))

    classify.main()
    assert '"category": "operations"' in capsys.readouterr().out


def test_main_exits_when_no_text_given(monkeypatch):
    monkeypatch.setattr(classify, "make_client", lambda: object())
    monkeypatch.setattr(sys, "argv", ["classify.py"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("   \n"))  # blank after strip

    with pytest.raises(SystemExit) as exc:
        classify.main()
    assert exc.value.code == 1
