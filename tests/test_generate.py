"""
Tests for src/generate.py.

The generator's only non-IO logic is generate_combo(), which forces a tool
call and returns the `articles` list. The API call is mocked.
"""

import generate


def test_generate_combo_returns_articles_list(tool_client):
    payload = {
        "articles": [
            {"text": "snippet one", "category": "industry", "operational_domain": "land"},
            {"text": "snippet two", "category": "industry", "operational_domain": "land"},
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
