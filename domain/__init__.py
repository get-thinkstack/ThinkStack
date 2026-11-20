"""The application logic, one package per capability. Nothing here imports api/.

    ingestion       PDF -> text, page-1 layout, metadata, chunks
    knowledge_base  embeddings, and the repository (all writes to the store)
    search          semantic search, and grounding for generation
    litgraph        the map: positions, edges, themes, gaps in one payload
    analysis        summaries, claims, themes; precompute queued after ingest
    gap_finder      gaps and research directions in one model call
    paper_writer    Scribe: project files, links, templates, compiler,
                    bibliography, index, synctex
    encryption      Argon2id + AES-256-GCM, the TSENC1 envelope
    model_manager   catalog, registry, router, discovery, downloads
    fine_tuning     passive collection of Scribe prompt -> LaTeX pairs

Domain code stands on infrastructure/ (LLM client, vector store, hardware
facts). The reverse happens only where infrastructure needs model routing
(ollama_client, file_manager import model_manager), always inside functions.
"""
