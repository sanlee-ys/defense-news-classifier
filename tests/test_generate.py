"""
Tests for src/generate.py.

The generator's only non-IO logic is generate_combo(), which forces a tool
call and returns the `articles` list. The API call is mocked.
"""

import pandas as pd
import pytest

import generate


def test_generate_combo_returns_articles_list(tool_client):
    payload = {
        "articles": [
            {
                "text": "snippet one",
                "category": "industry",
                "operational_domain": "land",
            },
            {
                "text": "snippet two",
                "category": "industry",
                "operational_domain": "land",
            },
        ]
    }
    client = tool_client(payload)
    articles = generate.generate_combo(client, "industry", "land")

    assert len(articles) == 2
    assert articles[0]["text"] == "snippet one"


def test_generate_combo_forces_tool_use(tool_client):
    client = tool_client({"articles": []})
    generate.generate_combo(client, "technology", "cyber")

    kwargs = client.messages.last_kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "generate_articles"}
    # The category and domain should both reach the prompt.
    prompt = kwargs["messages"][0]["content"]
    assert "technology" in prompt
    assert "cyber" in prompt


def test_generate_tool_schema_enums_match_constants():
    items = generate.GENERATE_TOOL["input_schema"]["properties"]["articles"]["items"]
    assert items["properties"]["category"]["enum"] == generate.CATEGORIES
    assert items["properties"]["operational_domain"]["enum"] == generate.DOMAINS


# --- main() --------------------------------------------------------------


def test_main_writes_one_csv_row_per_generated_article(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(generate.time, "sleep", lambda *_: None)  # no real waiting

    # One article per (category, domain) combo; echo the requested labels back.
    monkeypatch.setattr(
        generate,
        "generate_combo",
        lambda _c, cat, dom: [
            {"text": f"{cat}-{dom}", "category": cat, "operational_domain": dom}
        ],
    )

    out = tmp_path / "articles.csv"
    monkeypatch.setattr(generate, "OUTPUT_PATH", str(out))

    generate.main()

    df = pd.read_csv(out)
    n_combos = len(generate.CATEGORIES) * len(generate.DOMAINS)
    assert len(df) == n_combos  # 30 combos × 1 article each
    assert list(df["id"]) == list(range(n_combos))  # ids are sequential
    assert set(df["category"]) == set(generate.CATEGORIES)


def test_main_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(EnvironmentError):
        generate.main()
