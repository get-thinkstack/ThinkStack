"""Knowledge base: embeddings and the chunk repository.

`repository` makes every write to the vector store
(infrastructure/local_vector_store.py); search, grounding and the LitGraph
builder read it directly. `embedding_service` turns text into vectors; `author_codec` keeps author lists intact in scalar metadata.
"""
