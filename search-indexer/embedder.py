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


def _release_accelerator_memory():
    """Give MPS/CUDA cache back between slices so a 1,000+ chunk PDF can't
    exhaust it (a 1,241-page textbook hit 'MPS backend out of memory')."""
    try:
        import torch
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        elif torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def embed_documents(texts, slice_size=128):
    """Embeds a batch of document chunks (no instruction prefix — bge
    models expect the prefix only on the query side, not the corpus).
    Encodes in slices so memory stays flat however many chunks one source has;
    the vectors are identical to encoding everything in one call."""
    model = get_model()
    parts = []
    for i in range(0, len(texts), slice_size):
        parts.append(
            model.encode(
                texts[i:i + slice_size],
                normalize_embeddings=True,  # so cosine similarity == dot product
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        )
        _release_accelerator_memory()
    if not parts:
        return np.zeros((0, model.get_sentence_embedding_dimension()), dtype=np.float32)
    return np.vstack(parts).astype(np.float32)


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
