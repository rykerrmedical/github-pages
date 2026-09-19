"""
Wraps the local embedding model. Loaded once and reused across the whole
indexing run (loading it per-call would dominate runtime).
"""
import numpy as np
from sentence_transformers import SentenceTransformer

import config

_model = None


def get_model():
    global _model
    if _model is None:
        print(f"loading embedding model {config.EMBEDDING_MODEL_NAME} (first run downloads it, ~130MB)...")
        _model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
    return _model


def embed_documents(texts):
    """Embeds a batch of document chunks (no instruction prefix — bge
    models expect the prefix only on the query side, not the corpus)."""
    model = get_model()
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,  # so cosine similarity == dot product
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return embeddings.astype(np.float32)


def embed_query(query_text):
    """Embeds a single search query. Applies the bge query instruction
    prefix — the VPS query service must do the same thing for retrieval
    quality to match what was tested here."""
    model = get_model()
    prefixed = config.QUERY_INSTRUCTION_PREFIX + query_text
    embedding = model.encode(
        [prefixed],
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return embedding.astype(np.float32)[0]
