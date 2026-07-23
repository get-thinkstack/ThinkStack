# future scope and planned features

## high priority / architecture goals

### 1. feature-specific slms on cpu
- deployment of highly specialized, quantized small language models (slms) running natively on cpu/ram.
- dynamic model selection mechanism: models will be selected and downloaded based on the user machine's hardware specifications.

### 2. federated cloud fine-tuning
- outsourcing heavy model training (qlora) to cloud gpu instances.
- local federated sync client that periodically downloads tiny fine-tuned adapters (.gguf) to apply over the local frozen base model.

---

## completed features (recent updates)

### ai-assisted research paper writer (latex)
- **editor:** built-in text editor where users write prompts or ideas inside a `.ths` file, and a local AI converts them in-place to compilable LaTeX.
- **real-time preview:** client-side LaTeX HTML renderer using KaTeX. renders sections, math, tables, lists live as you type. two-tab pane: instant "Live Preview" + compiled "PDF" view.
- **compilation:** compiles to PDF using the local system's `pdflatex` with auto-healing (missing package injection, bare snippet wrapping, broken environment isolation).
- **future enhancement:** bundle Tectonic as an offline sidecar for self-contained, zero-dependency compiling.

### fine-tuning data collection pipeline
- every prompt LaTeX generation is passively logged to `data/training/latex_generation.jsonl`.
- gap analysis results logged to `data/training/gap_analysis.jsonl`.
- data is in chat-format JSONL (system/user/assistant messages), ready for QLoRA fine-tuning.

### cpu-only inference defaults
- `llm_gpu_layers` defaults to 0 so the app runs on any machine without GPU drivers.
- model path defaults to `data/models/` (portable, no hardcoded paths).
- `src-tauri/src/lib.rs` auto-detects python venv, project directory, and model path on both Linux and Windows.

---

## planned features

### implemented: ai-powered research paper writer (latex)
**status:** shipped. a text editor where the user writes plain english / pseudo-code, and the local slm converts it into compilable latex (`/api/papers/generate`).
- offline compilation to pdf via `pdflatex` with auto-healing compiler.
- real-time client-side latex preview using KaTeX (no compilation needed for preview).
- project workspace with create / save / list / compile / download / delete.
- training data collection: all generate calls are logged for future fine-tuning.
- **remaining:** bundling tectonic for a tex-free install.

### priority 2: secure authorized communication (p2p sharing)
**description:** decentralized, trust-based networking using libp2p.
- allows users to securely share their local research papers, generated drafts, and analysis results with specific peers.
- utilizes public key infrastructure (pki) and digital signatures. no central server holds user data or access lists.

### priority 2: advanced gap analysis targeting future work
**description:** expanding the current gap analysis engine to specifically target and synthesize the "future work" and "limitations" sections of multiple ingested papers using cross-attention analysis.

### priority 3: citation visualization
**description:** a graphical visualization of document citations.
- will allow users to map how different papers reference one another, highlighting foundational papers and identifying research clusters visually.
