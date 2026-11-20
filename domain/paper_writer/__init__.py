"""Scribe's backend.

    files         a project is a directory; safe_path is its boundary
    links         files used from outside the project, found again by identity
    templates     the starter documents
    compiler      heal, compile (Tectonic), salvage; project CRUD
    bibliography  library papers -> references.bib entries and keys
    indexing      .idx -> .ind, because the bundle has no makeindex
    synctex       source line <-> page position

Routes: api/routes_papers.py, routes_paper_files.py, routes_citations.py.
"""
