"""Tests for src/classify.py.

The single LLM call is mocked — these check the wiring around it: that we
send the right request and correctly pull the structured result back out.
"""

import io
import sys
from typing import cast

import pytest

import classify

# --- label sets / tool schema stay in sync -------------------------------


def test_tool_schema_enums_match_label_constants():
    # input_schema's properties/required are NotRequired in the SDK's TypedDict,
    # so pyright can't narrow chained indexing without this cast.
    schema = cast(dict, classify.CLASSIFY_TOOL["input_schema"])
    assert schema["properties"]["category"]["enum"] == classify.CATEGORIES
    assert schema["properties"]["operational_domain"]["enum"] == classify.DOMAINS


def test_tool_requires_both_fields():
    schema = cast(dict, classify.CLASSIFY_TOOL["input_schema"])
    assert set(schema["required"]) == {"category", "operational_domain"}


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
    # system is a single cacheable text block, not a bare string -- see
    # test_classify_system_prompt_is_cache_marked below for the cache_control
    # assertion; this test is just the plain content check.
    assert len(kwargs["system"]) == 1
    assert kwargs["system"][0]["text"] == classify.SYSTEM_PROMPT
    # Tool use is forced so the model can't return free text instead.
    assert kwargs["tool_choice"] == {"type": "tool", "name": "classify_article"}
    assert kwargs["messages"] == [
        {"role": "user", "content": "New defense strategy published."}
    ]


def test_classify_sends_custom_system_prompt(tool_client):
    # The prompt-optimization loop overrides the system prompt to score a
    # variant against the eval. Prove that override actually reaches the API call.
    client = tool_client({"category": "policy", "operational_domain": "multi"})
    custom_prompt = "REVISED: classify using these new rules."
    classify.classify(
        client, "New defense strategy published.", system_prompt=custom_prompt
    )

    kwargs = client.messages.last_kwargs
    assert kwargs["system"][0]["text"] == custom_prompt
    # Guard: prove the override *displaced* the default, not merely matched it.
    assert kwargs["system"][0]["text"] != classify.SYSTEM_PROMPT


def test_classify_system_prompt_is_cache_marked(tool_client):
    # The optimize.py loop calls classify() ~354 times per iteration with the
    # SAME system_prompt (only the per-row article text varies) -- the
    # textbook repeated-prefix caching case. Prove the cache_control marker
    # is actually on the wire, not just documented as intended.
    client = tool_client({"category": "policy", "operational_domain": "multi"})
    classify.classify(client, "New defense strategy published.")

    kwargs = client.messages.last_kwargs
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


# --- strict tool definition -----------------------------------------------


def test_classify_tool_is_strict():
    # strict:true is what now guarantees schema/enum validity server-side
    # (see decisions/008) -- prove the flag is actually on the wire.
    assert classify.CLASSIFY_TOOL["strict"] is True


def test_classify_tool_schema_forbids_additional_properties():
    # Required by the API alongside strict:true.
    schema = cast(dict, classify.CLASSIFY_TOOL["input_schema"])
    assert schema["additionalProperties"] is False


# --- enum validation guard -----------------------------------------------
#
# strict:true on CLASSIFY_TOOL now makes the API enforce enum membership via
# server-side constrained decoding, so an out-of-enum tool_use.input should no
# longer occur in practice. _validate() remains a defensive backstop in case
# that guarantee is ever violated; these tests exercise the backstop directly
# rather than simulating a live out-of-enum response.


def test_validate_accepts_in_range_labels():
    payload = {"category": "industry", "operational_domain": "sea"}
    assert classify._validate(payload) == payload


def test_validate_rejects_out_of_enum_category():
    # "cyber" is a valid domain but not a valid category — the exact id-95 bug
    # that predates strict mode.
    with pytest.raises(classify.InvalidLabelError):
        classify._validate({"category": "cyber", "operational_domain": "cyber"})


def test_validate_rejects_out_of_enum_domain():
    with pytest.raises(classify.InvalidLabelError):
        classify._validate({"category": "operations", "operational_domain": "naval"})


def test_classify_raises_immediately_on_invalid_label_no_resample(tool_client_seq):
    # There is no re-sample loop any more (see decisions/008): a single
    # out-of-enum response raises on the first and only call.
    client = tool_client_seq(
        [
            {"category": "cyber", "operational_domain": "cyber"},  # invalid
            {"category": "operations", "operational_domain": "cyber"},  # would be valid
        ]
    )
    with pytest.raises(classify.InvalidLabelError):
        classify.classify(client, "Cyber intrusion disrupted.")
    assert client.messages.calls == 1  # no re-sample attempted


# --- Message Batches API path ---------------------------------------------


def test_build_batch_request_matches_classify_call_shape():
    req = classify.build_batch_request("row-1", "Some article text.")
    assert req["custom_id"] == "row-1"
    params = req["params"]
    assert params["model"] == classify.MODEL
    assert params["tools"] == [classify.CLASSIFY_TOOL]
    assert params["tool_choice"] == {"type": "tool", "name": "classify_article"}
    assert params["messages"] == [{"role": "user", "content": "Some article text."}]
    # Reuses the same cache_control marker as the synchronous path.
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["system"][0]["text"] == classify.SYSTEM_PROMPT
    assert "temperature" not in params


def test_build_batch_request_honors_model_prompt_and_temperature_overrides():
    req = classify.build_batch_request(
        "row-2",
        "Some article text.",
        model="claude-opus-4-8",
        system_prompt="REVISED prompt",
        temperature=0.0,
    )
    params = req["params"]
    assert params["model"] == "claude-opus-4-8"
    assert params["system"][0]["text"] == "REVISED prompt"
    assert params["temperature"] == 0.0


def test_parse_batch_result_returns_validated_labels():
    from conftest import make_tool_block

    result = types_namespace(
        custom_id="row-1",
        result=types_namespace(
            type="succeeded",
            message=types_namespace(
                content=[
                    make_tool_block(
                        {"category": "policy", "operational_domain": "multi"}
                    )
                ]
            ),
        ),
    )
    assert classify.parse_batch_result(result) == {
        "category": "policy",
        "operational_domain": "multi",
    }


def test_parse_batch_result_raises_on_non_succeeded_item():
    result = types_namespace(custom_id="row-2", result=types_namespace(type="errored"))
    with pytest.raises(classify.BatchItemError):
        classify.parse_batch_result(result)


def test_parse_batch_result_raises_invalid_label_error_on_bad_labels():
    from conftest import make_tool_block

    result = types_namespace(
        custom_id="row-3",
        result=types_namespace(
            type="succeeded",
            message=types_namespace(
                content=[
                    make_tool_block(
                        {"category": "cyber", "operational_domain": "cyber"}
                    )
                ]
            ),
        ),
    )
    with pytest.raises(classify.InvalidLabelError):
        classify.parse_batch_result(result)


def types_namespace(**kwargs):
    """Tiny stand-in for the SDK's batch result objects (attribute access only)."""
    import types

    return types.SimpleNamespace(**kwargs)


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
