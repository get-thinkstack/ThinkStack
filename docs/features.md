# current features and known issues

## current features

1. **desktop architecture & devops**
   - standalone cross-platform executable via tauri (rust).
   - python fastapi sidecar seamlessly bundled using pyinstaller.
   - one-click automated devops pipeline for setup, development, validation, and building.
   - github actions ci/cd: builds for linux (x64 deb/rpm/AppImage), macOS (universal dmg), and windows (x64 msi/exe) on every version tag.
   - download landing page for github pages with automatic os detection and per-platform install buttons.
   - `lib.rs` prefers the bundled sidecar binary in production, falls back to python venv in development.

2. **document ingestion pipeline**
   - cascading pdf parser: tries pymupdf (fast) first, falls back to `pdfplumber` for scanned or complex layouts.
   - text chunking algorithm with overlap and page-number retention using word-overlap scoring.
   - metadata extraction via regex with slm (small language model) fallback.

3. **offline knowledge base**
   - custom numpy-based local vector store (zero external db dependencies).
   - local embeddings using `sentence-transformers` (`all-minilm-l6-v2`).

4. **hybrid search**
   - semantic search (cosine similarity via embeddings).
   - keyword search (bm25 token matching).
   - reciprocal rank fusion (rrf) to merge and rank results.

5. **analysis & gap finder**
   - single and multi-paper comparative summarization.
   - thematic clustering.
   - gap analysis (contradictions, methodological, missing validation) and actionable research suggestions.

6. **local llm integration**
   - dual-runtime client: supports both ollama and llama.cpp (direct memory loading via gguf).
   - gbnf grammar constraints for strict json and latex output when using llama_cpp.
   - gpu-acceleration fallback logic (tries gpu, falls back to cpu on oom).

7. **ai-assisted paper writer (latex)**
   - interactive monospaced editor integrated directly inside the Tauri desktop app interface.
   - `.ths` (ThinkStack) file format support: users write prompts/ideas directly inside the editor, and the AI translates it in-place to compilable LaTeX.
   - **real-time latex preview**: client-side LaTeX → HTML renderer using KaTeX. sections, math, tables, lists, and formatting render live as the user types — no compilation needed. two-tab preview pane: "Live Preview" (instant) + "Compiled PDF" (pdflatex output).
   - auto-save (saves incrementally after 2 seconds of inactivity) and manual save capabilities.
   - built-in offline compiler pipeline utilizing system `pdflatex` to generate and compile papers.
   - auto-healing compiler: detects missing packages (tikz, pgfplots, booktabs, etc.) and injects them into the preamble. wraps bare snippets into full documents. isolates broken environments with placeholders so the rest still compiles.
   - real-time error log parsing that exposes compiler diagnostics directly within the UI when compilation fails.
   - automated test suite validating the end-to-end writer API and compiler pipeline.

8. **fine-tuning data collection**
   - passively collects prompt → LaTeX training pairs from every AI generation call.
   - stores data as JSONL in `data/training/` for future QLoRA fine-tuning.
   - separate datasets for `latex_generation` and `gap_analysis` tasks.

9. **cpu-only inference (default)**
   - `llm_gpu_layers` defaults to 0 — works on any machine without GPU drivers.
   - model path defaults to the project's `data/models/` directory (no hardcoded paths).
   - GPU acceleration available via `THINKSTACK_LLM_GPU_LAYERS=-1` env var.

## known issues

1. **bm25 search performance**: the bm25 index is built from scratch on every keyword search query. this is acceptable for a small corpus but will become a bottleneck as the document count grows.
2. **analysis route duplication**: `routes_gaps.py` partially duplicates summarization logic found in `summarizer.py`. (intentional for efficiency, but adds maintenance overhead).
3. **llm retry logic**: while gbnf handles `llama_cpp`, there's no extensive retry logic if ollama hallucinates malformed structures.
4. **latex compiler dependency**: the paper writer currently shells out to a system `pdflatex` (a full tex installation must be on `PATH`), rather than the planned bundled `tectonic` sidecar. compilation fails gracefully with a 422 if `pdflatex` is missing.
5. **live preview limitations**: the client-side LaTeX preview handles common academic paper elements but cannot render tikz diagrams, complex tables, or custom macros — those only show in the compiled PDF tab.
