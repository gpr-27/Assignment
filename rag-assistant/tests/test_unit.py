"""Pure logic tests, no database needed."""

from app.security import hash_password, verify_password
from app.services.chat import used_citations
from app.services.ingestion import split_text
from app.services.retrieval import Source


def test_split_text_respects_size_and_overlap():
    text = " ".join(f"Sentence number {i} is here." for i in range(200))
    chunks = split_text(text, size=200, overlap=50)
    assert len(chunks) > 5
    assert all(len(c) <= 200 for c in chunks)
    # consecutive chunks share some text (the overlap)
    assert chunks[0][-20:].split()[-1] in chunks[1]


def test_split_text_short_and_empty():
    assert split_text("hello world", 1000, 100) == ["hello world"]
    assert split_text("   \n\n  ", 1000, 100) == []


def test_password_hashing():
    hashed = hash_password("secret-pass")
    assert hashed != "secret-pass"
    assert verify_password("secret-pass", hashed)
    assert not verify_password("wrong", hashed)


def test_only_cited_sources_are_returned():
    sources = [Source(n, n, f"f{n}.txt", None, "text", 0.9) for n in (1, 2, 3)]
    citations = used_citations("Fact one [1]. Fact three [3].", sources)
    assert [c["number"] for c in citations] == [1, 3]
    assert [c["number"] for c in used_citations("Fact two【2】.", sources)] == [2]
