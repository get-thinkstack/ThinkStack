# Third-party notices

ThinkStack installers **redistribute** the components below. They are not
dependencies fetched at install time; they ship inside the installer, which is
why their licences apply to our distribution and are reproduced here.

## Redistributed inside the installer

| Component | Version | Licence | Role |
|---|---|---|---|
| [Qwen2.5-0.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF) | 0.5B, Q4_K_M | Apache-2.0 | bundled language model |
| [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | - | Apache-2.0 | sentence embeddings |
| [Tectonic](https://tectonic-typesetting.github.io/) | 0.15.0 | MIT | TeX engine and package cache |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) via `llama-cpp-python` | - | MIT | inference runtime |

Qwen2.5-1.5B-Instruct-GGUF (Apache-2.0) is **not** redistributed. It is
downloaded only with the user's explicit consent, or reused from a copy the user
already has.

## Principal libraries

Backend: FastAPI, Uvicorn, Pydantic (MIT / BSD-3-Clause) · PyMuPDF (AGPL-3.0 or
commercial) · pdfplumber (MIT) · sentence-transformers, PyTorch (Apache-2.0 /
BSD-3-Clause) · rank_bm25 (Apache-2.0) · NumPy (BSD-3-Clause) · cryptography
(Apache-2.0 or BSD-3-Clause) · argon2-cffi (MIT) · httpx (BSD-3-Clause)

Desktop and interface: Tauri (MIT or Apache-2.0) · React (MIT) · Vite (MIT) ·
KaTeX (MIT) · Recharts (MIT) · Framer Motion (MIT) · Lucide (ISC)

## A note on PyMuPDF

PyMuPDF is distributed under AGPL-3.0 unless a commercial licence is obtained.
It is used for PDF text extraction. Anyone redistributing a modified ThinkStack,
or offering it as a network service, should confirm their obligations under that
licence. `pdfplumber` (MIT) already exists in the codebase as a fallback
extractor, so replacing PyMuPDF is feasible if those terms become a problem.

This file lists what is known at the time of writing and is not legal advice.
