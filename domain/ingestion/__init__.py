"""Ingestion: a PDF becomes text, metadata and chunks.

    pdf_parser          text (PyMuPDF, then pdfplumber) and page-1 spans
    layout              spans -> rows of cells; pure geometry
    layout_metadata     title and authors from those rows
    metadata_extractor  layout, then regex, then the model if implausible
    chunker             overlapping chunks that remember their page

Driven by api/routes_documents.py; chunks go to knowledge_base.repository.
"""
