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
    assert schema["properties"]["region"]["enum"] == classify.REGIONS


def test_tool_requires_all_fields():
    schema = cast(dict, classify.CLASSIFY_TOOL["input_schema"])
    assert set(schema["required"]) == {"category", "operational_domain", "region"}


# --- classify() ----------------------------------------------------------


def test_classify_returns_tool_input(tool_client):
    client = tool_client(
        {"category": "procurement", "operational_domain": "air", "region": "global"}
    )
    result = classify.classify(client, "Pentagon awards F-35 contract.")
    assert result == {
        "category": "procurement",
        "operational_domain": "air",
        "region": "global",
    }


def test_classify_skips_non_tool_blocks(tool_client):
    # A leading text block must be ignored; the tool_use block is what counts.
    from conftest import make_text_block

    client = tool_client(
        {"category": "operations", "operational_domain": "sea", "region": "global"},
        extra_blocks=[make_text_block("thinking out loud")],
    )
    result = classify.classify(client, "Carrier group deploys to the strait.")
    assert result["category"] == "operations"


def test_classify_sends_expected_request(tool_client):
    client = tool_client(
        {"category": "policy", "operational_domain": "multi", "region": "global"}
    )
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
    # The effort hint rides along via output_config (the Sonnet 5 lever that
    # replaced the removed manual thinking budget).
    assert kwargs["output_config"] == {"effort": classify.EFFORT}


def test_classify_sends_custom_system_prompt(tool_client):
    # The prompt-optimization loop overrides the system prompt to score a
    # variant against the eval. Prove that override actually reaches the API call.
    client = tool_client(
        {"category": "policy", "operational_domain": "multi", "region": "global"}
    )
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
    client = tool_client(
        {"category": "policy", "operational_domain": "multi", "region": "global"}
    )
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
    payload = {
        "category": "industry",
        "operational_domain": "sea",
        "region": "indo-pacific",
    }
    assert classify._validate(payload) == payload


def test_validate_rejects_out_of_enum_category():
    # "cyber" is a valid domain but not a valid category — the exact id-95 bug
    # that predates strict mode.
    with pytest.raises(classify.InvalidLabelError):
        classify._validate(
            {"category": "cyber", "operational_domain": "cyber", "region": "global"}
        )


def test_validate_rejects_out_of_enum_domain():
    with pytest.raises(classify.InvalidLabelError):
        classify._validate(
            {
                "category": "operations",
                "operational_domain": "naval",
                "region": "global",
            }
        )


def test_validate_rejects_out_of_enum_region():
    # "pacific" is not a label; the axis uses "indo-pacific" (decisions/014).
    with pytest.raises(classify.InvalidLabelError):
        classify._validate(
            {"category": "operations", "operational_domain": "sea", "region": "pacific"}
        )


def test_validate_rejects_missing_region():
    # A v2-shaped payload (two fields) is no longer a valid result.
    with pytest.raises(classify.InvalidLabelError):
        classify._validate({"category": "operations", "operational_domain": "sea"})


def test_classify_raises_immediately_on_invalid_label_no_resample(tool_client_seq):
    # There is no re-sample loop any more (see decisions/008): a single
    # out-of-enum response raises on the first and only call.
    client = tool_client_seq(
        [
            {  # invalid category
                "category": "cyber",
                "operational_domain": "cyber",
                "region": "global",
            },
            {  # would be valid
                "category": "operations",
                "operational_domain": "cyber",
                "region": "global",
            },
        ]
    )
    with pytest.raises(classify.InvalidLabelError):
        classify.classify(client, "Cyber intrusion disrupted.")
    assert client.messages.calls == 1  # no re-sample attempted


# --- refusal handling -----------------------------------------------------
#
# A safety-classifier refusal is a successful HTTP 200 with
# stop_reason == "refusal" and no tool_use block -- not an SDK exception. These
# check classify() raises a clear, distinct ClassificationRefusalError instead
# of the bare StopIteration the tool-block extraction would otherwise throw.


def test_classify_raises_refusal_error_on_refusal(refusal_client):
    client = refusal_client(category="cyber", explanation="declined for safety")
    with pytest.raises(classify.ClassificationRefusalError):
        classify.classify(client, "Some defense-news snippet.")


def test_classify_refusal_error_message_includes_category(refusal_client):
    client = refusal_client(category="cyber", explanation="declined for safety")
    with pytest.raises(classify.ClassificationRefusalError) as exc:
        classify.classify(client, "Some defense-news snippet.")
    # The category/explanation ride along in the message so a refusal is legible.
    assert "cyber" in str(exc.value)
    assert "refusal" in str(exc.value)


def test_classify_raises_refusal_even_without_stop_details(refusal_client):
    # stop_details can be absent/None on a refusal; the guard keys on
    # stop_reason alone and must still raise.
    client = refusal_client()
    with pytest.raises(classify.ClassificationRefusalError):
        classify.classify(client, "Some defense-news snippet.")


def test_refusal_error_is_distinct_from_invalid_label_and_batch_item():
    # A refusal is neither a validation failure nor a batch-transport failure --
    # callers must be able to catch it on its own.
    assert not issubclass(
        classify.ClassificationRefusalError, classify.InvalidLabelError
    )
    assert not issubclass(classify.ClassificationRefusalError, classify.BatchItemError)


def test_normal_response_is_not_treated_as_refusal(tool_client):
    # Guard against a false positive: a normal (stop_reason-less) fake response
    # must classify fine, proving the refusal branch doesn't fire on non-refusals.
    client = tool_client(
        {"category": "procurement", "operational_domain": "air", "region": "global"}
    )
    assert (
        classify.classify(client, "Pentagon awards contract.")["category"]
        == "procurement"
    )


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
    # Mirrors the synchronous path's effort hint; temperature is omitted (the
    # API default) -- current models reject a non-default sampling value.
    assert params["output_config"] == {"effort": classify.EFFORT}
    assert "temperature" not in params


def test_build_batch_request_honors_model_and_prompt_overrides():
    req = classify.build_batch_request(
        "row-2",
        "Some article text.",
        model="claude-opus-4-8",
        system_prompt="REVISED prompt",
    )
    params = req["params"]
    assert params["model"] == "claude-opus-4-8"
    assert params["system"][0]["text"] == "REVISED prompt"


def test_parse_batch_result_returns_validated_labels():
    from conftest import make_tool_block

    result = types_namespace(
        custom_id="row-1",
        result=types_namespace(
            type="succeeded",
            message=types_namespace(
                content=[
                    make_tool_block(
                        {
                            "category": "policy",
                            "operational_domain": "multi",
                            "region": "global",
                        }
                    )
                ]
            ),
        ),
    )
    assert classify.parse_batch_result(result) == {
        "category": "policy",
        "operational_domain": "multi",
        "region": "global",
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
                        {
                            "category": "cyber",
                            "operational_domain": "cyber",
                            "region": "global",
                        }
                    )
                ]
            ),
        ),
    )
    with pytest.raises(classify.InvalidLabelError):
        classify.parse_batch_result(result)


def test_parse_batch_result_raises_refusal_error_on_refusal_message():
    # A "succeeded" batch item can still be a refusal (transport worked, model
    # declined): stop_reason=='refusal' with no tool_use block. Must raise the
    # distinct refusal error, not StopIteration from the tool-block extraction.
    result = types_namespace(
        custom_id="row-4",
        result=types_namespace(
            type="succeeded",
            message=types_namespace(
                content=[],
                stop_reason="refusal",
                stop_details=types_namespace(category="cyber", explanation="declined"),
            ),
        ),
    )
    with pytest.raises(classify.ClassificationRefusalError) as exc:
        classify.parse_batch_result(result)
    # The custom_id is threaded through so a bulk-run refusal points at its row.
    assert "row-4" in str(exc.value)


def types_namespace(**kwargs):
    """Tiny stand-in for the SDK's batch result objects (attribute access only)."""
    import types

    return types.SimpleNamespace(**kwargs)


# --- cache diagnostics ----------------------------------------------------
#
# Visibility helpers for WHEN classify()'s prompt cache engages. count_prefix_tokens
# hits the (mocked) count_tokens endpoint; cacheable_prefix_gap is pure arithmetic
# over the documented per-model floors.


def test_count_prefix_tokens_returns_input_tokens(count_tokens_client):
    client = count_tokens_client(850)
    assert classify.count_prefix_tokens(client) == 850


def test_count_prefix_tokens_counts_tool_schema_and_system(count_tokens_client):
    client = count_tokens_client(850)
    classify.count_prefix_tokens(client)
    kwargs = client.messages.last_kwargs
    # The prefix that must clear the floor is tools + system; both are counted.
    assert kwargs["tools"] == [classify.CLASSIFY_TOOL]
    assert kwargs["system"][0]["text"] == classify.SYSTEM_PROMPT
    assert kwargs["model"] == classify.MODEL


def test_count_prefix_tokens_honors_model_and_prompt_overrides(count_tokens_client):
    client = count_tokens_client(1234)
    classify.count_prefix_tokens(
        client, model="claude-opus-4-8", system_prompt="REVISED prompt"
    )
    kwargs = client.messages.last_kwargs
    assert kwargs["model"] == "claude-opus-4-8"
    assert kwargs["system"][0]["text"] == "REVISED prompt"


def test_cacheable_prefix_gap_positive_when_below_floor():
    # 850 tokens against Sonnet 4.6's 2048 floor -> 1198 tokens short (no-op).
    gap = classify.cacheable_prefix_gap(850, model="claude-sonnet-4-6")
    assert gap == 2048 - 850


def test_cacheable_prefix_gap_non_positive_when_clearing_floor():
    gap = classify.cacheable_prefix_gap(3000, model="claude-sonnet-4-6")
    assert gap == 2048 - 3000
    assert gap <= 0


def test_cacheable_prefix_gap_none_for_unknown_model():
    assert classify.cacheable_prefix_gap(850, model="some-unlisted-model") is None


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
