from voice_rag.core import chunk_text, content_hash, detect_language, normalize_text


def test_normalization_is_unicode_aware_and_stable():
    assert normalize_text("  नमस्ते\n दुनिया  ") == "नमस्ते दुनिया"
    assert content_hash("a", "b") == content_hash(" a ", "b")


def test_language_detection_supports_indic_script():
    assert detect_language("नमस्ते दुनिया") == "hi"
    assert detect_language("hello world") == "en"


def test_chunking_has_stable_ids_and_overlap():
    chunks = chunk_text(
        "First sentence. Second sentence. Third sentence.",
        language="en",
        query_id="q",
        passage_id="p",
        max_chars=25,
        overlap=5,
    )
    assert len(chunks) >= 2
    assert len({chunk.id for chunk in chunks}) == len(chunks)
    assert all(chunk.strategy == "sentence_overlap" for chunk in chunks)


def test_fixed_overlap_chunking_keeps_window_and_tail():
    text = "word " * 60
    chunks = chunk_text(
        text,
        language="en",
        query_id="q",
        passage_id="p",
        max_chars=100,
        overlap=20,
        strategy="fixed_overlap",
    )
    assert len(chunks) >= 2
    assert all(chunk.strategy == "fixed_overlap" for chunk in chunks)
    assert all(len(chunk.text) <= 100 for chunk in chunks)
    assert chunks[-1].text.strip().endswith("word")


def test_chunk_text_rejects_unknown_strategy():
    import pytest

    with pytest.raises(ValueError):
        chunk_text(
            "some text",
            language="en",
            query_id="q",
            passage_id="p",
            strategy="bogus",
        )
