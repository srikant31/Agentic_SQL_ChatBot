from utils import extract_text


def test_plain_string_passthrough():
    """The simple case: if content is already a string, return it unchanged."""
    assert extract_text("hello") == "hello"


def test_list_of_text_blocks():
    """This is the actual shape Gemini returns in practice (confirmed
    during development — see the standalone test that printed this exact
    structure). The function's entire reason for existing is to handle
    this correctly."""
    content = [{"type": "text", "text": "OK", "extras": {"signature": "abc"}}]
    assert extract_text(content) == "OK"


def test_multiple_text_blocks_joined():
    """If a response ever comes back as multiple text blocks, they should
    be joined into one readable string, not just the first one returned."""
    content = [{"type": "text", "text": "Line one"}, {"type": "text", "text": "Line two"}]
    assert extract_text(content) == "Line one\nLine two"


def test_list_of_plain_strings():
    """Defensive case: if a list contains plain strings instead of dicts
    (a shape we haven't seen but can't rule out from an API we don't
    control), it should still extract something sensible rather than crash."""
    assert extract_text(["a", "b"]) == "a\nb"


def test_empty_list_falls_back_to_str():
    """An empty list has nothing to extract — the function should degrade
    gracefully (stringify it) rather than throw an IndexError."""
    assert extract_text([]) == "[]"


def test_non_dict_non_string_block_ignored():
    """A block that's neither a dict with 'type': 'text' nor a plain
    string (e.g. an unexpected int) should be skipped, not crash the
    whole extraction."""
    content = [{"type": "text", "text": "kept"}, 42]
    assert extract_text(content) == "kept"