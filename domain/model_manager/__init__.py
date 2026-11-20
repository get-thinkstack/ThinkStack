"""Model management: which models exist, which job each does, and fetching more.

    catalog     models ThinkStack knows how to fetch, judged per machine
    registry    the user's models and task assignments (the only writable source)
    manifest    what this build ships (bundled.json; no LLM today)
    reconcile   brings the registry in line with the manifest after an update
    router      which model answers a task, here, now (dependencies injected)
    discovery   models already on this machine (Ollama, LM Studio, folder)
    downloader  catalog downloads, to .part then renamed
    huggingface search and download from Hugging Face

Bench drives it through api/routes_registry.py, routes_models.py, routes_hf.py;
generation reaches the router through infrastructure/ollama_client.py.
"""
