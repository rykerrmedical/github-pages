"""
Splits a page's extracted text into overlapping word-count-based chunks.

Word-based rather than token-based on purpose: it avoids pulling in a
tokenizer just for chunking, and the overlap/size math is easy to reason
about. It's an approximation of the embedding model's actual token count,
which is fine at this chunk size (bge-small's context window is 512
tokens; ~220 words is comfortably under that even for verbose English).
"""
import config


def chunk_text(text):
    words = text.split()
    if not words:
        return []

    size = config.CHUNK_SIZE_WORDS
    overlap = config.CHUNK_OVERLAP_WORDS
    step = max(size - overlap, 1)

    chunks = []
    start = 0
    while start < len(words):
        piece = words[start : start + size]
        if len(piece) >= config.MIN_CHUNK_WORDS or start == 0:
            chunks.append(" ".join(piece))
        if start + size >= len(words):
            break
        start += step
    return chunks


if __name__ == "__main__":
    sample = "word " * 500
    result = chunk_text(sample.strip())
    print(f"{len(result)} chunks from 500 words")
    for i, c in enumerate(result):
        print(i, len(c.split()), "words")
