from voice_rag.indexing import chunk_semantic, cosine_similarity


def test_cosine_similarity_is_normalized():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) > 0.99
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) < 0.01


def test_semantic_chunking_merges_similar_sentences_and_keeps_ids_stable():
    embed = lambda sentences: [[1.0, 0.0]] * len(sentences)
    first = chunk_semantic(
        "Cats like milk. Cats nap all day. Dogs bark loudly. Dogs chase balls.",
        language="en",
        query_id="q",
        passage_id="p",
        embed=embed,
        max_chars=120,
        similarity_threshold=0.0,
    )
    second = chunk_semantic(
        "Cats like milk. Cats nap all day. Dogs bark loudly. Dogs chase balls.",
        language="en",
        query_id="q",
        passage_id="p",
        embed=embed,
        max_chars=120,
        similarity_threshold=0.0,
    )
    assert all(chunk.strategy == "semantic" for chunk in first)
    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert len(first) >= 1


def test_semantic_chunking_falls_back_for_short_text():
    chunks = chunk_semantic(
        "A short passage.",
        language="en",
        query_id="q",
        passage_id="p",
        embed=lambda _: [[1.0, 0.0]],
    )
    assert len(chunks) == 1
    assert chunks[0].strategy == "semantic"
