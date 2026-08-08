# ThinkStack - First Review Presentation

**Offline Research Intelligence & AI LaTeX Paper Writer**
Aditya Mehta (2440204) · Jitvan Chadha (2440222) · Ritesh K R (2440233)
Department of Computer Science, CHRIST (Deemed to be University) · First Review - 24 June 2026

> ~10 slides following the review format (Abstract Introduction SRS Analysis SRS Specification Modules Requirements).
> The **app's featureset is organized into 3 modules** (see the *Modules* slide). Each `### Slide` below = one slide.

---

### Slide 1 - Title
- **ThinkStack** - Offline Research Intelligence & AI LaTeX Paper Writer
- Team: Aditya Mehta (2440204), Jitvan Chadha (2440222), Ritesh K R (2440233)
- 5th Semester Project · Department of Computer Science, CHRIST University
- First Review - 24 June 2026

### Slide 2 - Abstract
- **ThinkStack** is an **offline, privacy-first** desktop research assistant - everything runs locally, no data leaves the machine.
- Ingests PDF papers into a local vector knowledge base; provides **hybrid semantic + keyword search**, SLM-powered **summarization, claim extraction, theme clustering**, and **research-gap analysis**.
- Adds **AES-256 encryption** for papers and an **AI-assisted LaTeX paper writer** with an offline compiler - powered by a local small language model (llama.cpp / Ollama) with GPU acceleration.

### Slide 3 - Introduction (2–3 points)
- Literature review and academic writing are slow, and current AI research tools are **cloud-based** - raising **privacy, recurring-cost, and connectivity** concerns.
- ThinkStack delivers the whole workflow **locally and offline**: *ingest search analyze find gaps write the paper*.
- Built as a cross-platform **desktop app** (Tauri + Python sidecar) so all documents and computation stay on the user's own hardware.

---

### Slide 4 - SRS Analysis: Existing Works
- **Cloud AI research assistants:** Elicit, Semantic Scholar, SciSpace, Scholarcy, Research Rabbit - search, summarize, map literature.
- **Reference managers:** Zotero, Mendeley - organize PDFs and citations.
- **General LLM chat tools:** ChatGPT / Claude - used ad-hoc for summaries and drafting.
- **Online LaTeX editors:** Overleaf - collaborative, browser-based writing and compilation.

### Slide 5 - SRS Analysis: Limitations of Existing Works
- **Privacy:** unpublished papers, notes, and drafts are uploaded to third-party servers.
- **Connectivity & cost:** require constant internet and recurring subscriptions.
- **Fragmented workflow:** search, analysis, reference management, and writing live in separate tools.
- **No grounded writing:** no offline LaTeX authoring tied to *your own* ingested corpus and gap analysis.

### Slide 6 - SRS Analysis: Proposed Work & Advantages
- **Proposed work:** a single offline desktop app unifying ingestion, semantic search, a spatial literature map (LitGraph) carrying SLM analysis and gap finding, RAG chat, encryption, and an AI LaTeX editor (Scribe) + compiler.
- **Advantages:**
  - **100% offline & private** - nothing leaves the machine.
  - **Zero recurring cost**; GPU-accelerated local SLM (sub-second responses).
  - **Integrated end-to-end** - from PDF to compiled paper in one place.
  - **Encrypted at rest** (AES-256-GCM + Argon2id).

### Slide 7 - Literature Survey

| Approach | Focus | Gap addressed by ThinkStack |
|---|---|---|
| Cloud research AI (Elicit, SciSpace) | Online search & summarization | Offline, private, no subscription |
| Reference managers (Zotero, Mendeley) | PDF & citation organization | Adds semantic search + analysis |
| RAG over documents | Grounded Q&A on a corpus | Runs locally with small models |
| Online LaTeX editors (Overleaf) | Browser-based authoring | Offline AI generation + compile |

- Sample corpus used in testing: Therapeutics Data Commons; SSI-DDI (substructure interactions); GNNs for molecular property prediction; federated clinical NLP.

---

### Slide 8 - SRS Specification: Software & Hardware Requirements
- **Software**
  - Python 3.11–3.13, FastAPI + Uvicorn
  - React (Vite) frontend in a Tauri (Rust) desktop shell
  - llama.cpp / Ollama (GGUF small language model)
  - sentence-transformers; custom numpy vector store
  - `pdflatex` (TeX) for paper compilation; cryptography + argon2-cffi
- **Hardware**
  - x86-64 CPU, 8 GB+ RAM
  - ~5 GB disk for local models
  - Optional NVIDIA GPU (≥6 GB VRAM, CUDA) for acceleration; runs CPU-only as fallback

### Slide 9 - Modules (the app's featureset, in 3 modules)

**Module 1 - Knowledge Management** *(ingest · store · secure)*
- PDF ingestion: parsing, chunking, and metadata extraction.
- Local knowledge base: embeddings + custom numpy vector store.
- Per-paper encryption at rest (AES-256-GCM with Argon2id KDF).

**Module 2 - Research Intelligence** *(search · analyze · assist)*
- Hybrid semantic + keyword search fused with Reciprocal Rank Fusion (RRF).
- Summarization, claim extraction, and theme clustering.
- Research-gap analysis with actionable directions + RAG chat assistant grounded in your papers.

**Module 3 - Scribe, the AI paper writer** *(author · compile)*
- Plain-language / pseudo-code compilable LaTeX via the local SLM.
- Project workspace (create / save / list / delete) with a starter template.
- Offline `pdflatex` compilation and one-click PDF download.

### Slide 10 - Functional & Non-Functional Requirements
- **Functional Requirements**
  - Upload & ingest PDFs; hybrid search across the knowledge base
  - Summarize / extract claims / cluster themes; run gap analysis; RAG chat
  - Encrypt / decrypt papers
  - Create, AI-generate, compile & download LaTeX papers
  - Switch the active SLM model; toggle light/dark theme
- **Non-Functional Requirements**
  - **Privacy** - fully offline, local-only processing
  - **Performance** - GPU-accelerated SLM, sub-second generation
  - **Security** - encryption at rest
  - **Usability** - responsive light/dark UI
  - **Portability** - cross-platform desktop app
  - **Reliability** - graceful CPU/JSON fallbacks
