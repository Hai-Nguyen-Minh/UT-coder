# 🧪 UTcoder — AI-Powered Unit Test Generator

**Local. Private. Offline.** UTcoder is an AI system that generates production-quality unit tests from source code using Ollama-powered LLMs, RAG over ChromaDB, and LoRA fine-tuning — all running entirely on your machine with zero data leaving it.

> **TL;DR:** Upload source code → AI generates tests + checks syntax + estimates coverage. Works offline. Fine-tunable on consumer GPUs.

---

## 🚀 Quick Start

```bash
# 1. Install Ollama and pull a code model
ollama pull deepseek-coder:6.7b
ollama pull nomic-embed-text

# 2. Install UTcoder
git clone <repo-url> && cd UTcoder
pip install -r requirements.txt

# 3. Launch (choose one)
python main.py            # Gradio Web UI → http://localhost:7860
python server.py          # REST API      → http://localhost:8000
```

**VS Code Extension:** Install from the `vscode-extension/` directory, right-click any source file, and select "UTcoder: Generate Unit Tests".

---

## 📁 Project Structure (At a Glance)

```
UTcoder/
├── main.py, server.py          # Entry points (UI + API)
├── core/
│   ├── llm.py                  # Ollama LLM wrapper
│   ├── generator.py            # Test generation pipeline
│   ├── vectorstore.py          # ChromaDB + RAG
│   ├── code_parser.py          # Language-aware code chunking
│   ├── compiler.py             # AI-based compile checking
│   ├── coverager.py            # AI-based coverage analysis
│   └── dataset/ingest.py       # LoRA/QLoRA fine-tuning pipeline
├── ui/app.py                   # Gradio web interface
└── vscode-extension/           # VS Code extension (TypeScript)
```

---

## 🏗️ System Architecture

```
┌──────────────────────────────────────────────────┐
│                   UI LAYER                       │
│  ┌─────────────────┐      ┌───────────────────┐ │
│  │  Gradio Web App  │      │  VS Code Extension│ │
│  │  (drag & drop)   │      │  (right-click)    │ │
│  └────────┬─────────┘      └────────┬──────────┘ │
│           │                         │             │
├───────────┼─────────────────────────┼─────────────┤
│           │      REST API (server.py)            │
│           ▼                                      │
│  ┌──────────────────────────────────────────┐   │
│  │  POST /api/generate     (test gen)       │   │
│  │  POST /api/compile-check (syntax check)  │   │
│  │  POST /api/coverage     (coverage est.)  │   │
│  │  GET  /api/health       (server status)  │   │
│  └────────────────┬─────────────────────────┘   │
│                   │                              │
├───────────────────┼──────────────────────────────┤
│                   ▼  CORE LAYER                  │
│  ┌──────────────────────────────────────────┐   │
│  │  generator.py (orchestrator)             │   │
│  │     │                                     │   │
│  │     ├── code_parser.py ─── chunk code     │   │
│  │     ├── vectorstore.py ── embed + index   │   │
│  │     ├── RAG retrieval ─── top-4 chunks    │   │
│  │     └── llm.py ────────── stream prompt   │   │
│  │                                           │   │
│  │  compiler.py  (LLM-as-compiler)           │   │
│  │  coverager.py (LLM-as-coverage-analyst)   │   │
│  │  sandbox/     (Pytest + Mutmut execution) │   │
│  └──────────────────────────────────────────┘   │
│                                                   │
│  ┌──────────────────────────────────────────┐   │
│  │  TRAINING PIPELINE (core/dataset/)        │   │
│  │  CSV → JSONL → LoRA/QLoRA → Adapter      │   │
│  └──────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

---

## 🔄 Pipeline Deep-Dive: From File Upload to Test Output

Here is the exact data flow when a user uploads a file and clicks "Generate":

```
User Uploads File
       │
       ▼
┌─────────────────────────────────────────────────┐
│ 1. LANGUAGE DETECTION & PARSING                 │
│                                                  │
│    code_parser.py                                │
│       │ detect_language(file_name) → "python"    │
│       │ parse_code(file, source) → chunks       │
│       │                                          │
│    LangChain RecursiveCharacterTextSplitter      │
│       │ chunk_size=1000, overlap=150             │
│       │ language-aware separators                │
│       │   Python: def, class, \n\n, \n, etc.    │
│       │   Java:   class, {, }, ;, \n\n, etc.    │
│       └────────────────────────────────────┬──────┘
│                                            │
├────────────────────────────────────────────┼──────┤
│ 2. VECTOR EMBEDDING & INDEXING             │      │
│                                            ▼      │
│    vectorstore.py                                 │
│       │ OllamaEmbeddings(model="nomic-embed-text")│
│       │   each chunk → 768-dim vector             │
│       │                                           │
│       │ ChromaDB (PersistentClient)                │
│       │   collection_name = "utcoder_{filename}"  │
│       │   delete stale collection                 │
│       │   Chroma.from_documents(docs, embeddings) │
│       └────────────────────────────────────┬──────┘
│                                            │
├────────────────────────────────────────────┼──────┤
│ 3. RAG RETRIEVAL                          │      │
│                                            ▼      │
│    vectorstore.similarity_search(                │
│        query="functions methods classes...",     │
│        collection_name=..., k=4                  │
│    )                                              │
│       │ cosine similarity search                  │
│       │ returns top-4 most relevant chunks        │
│       └────────────────────────────────────┬──────┘
│                                            │
├────────────────────────────────────────────┼──────┤
│ 4. PROMPT CONSTRUCTION                    │      │
│                                            ▼      │
│    generator.py                                   │
│       │ system_prompt:                             │
│       │   "You are a senior software engineer..."  │
│       │   + language-specific instructions         │
│       │   + test framework from config             │
│       │                                            │
│       │ user_prompt:                                │
│       │   source code (raw)                        │
│       │   + RAG context_block                      │
│       └────────────────────────────────────┬──────┘
│                                            │
├────────────────────────────────────────────┼──────┤
│ 5. LLM INFERENCE (Streaming)              │      │
│                                            ▼      │
│    llm.py → ChatOllama.stream([                  │
│        {"role": "system", "content": ...},       │
│        {"role": "user", "content": ...}          │
│    ])                                             │
│       │ model autoregressively generates tokens   │
│       │ yields each token to UI in real-time      │
│       └────────────────────────────────────┬──────┘
│                                            │
├────────────────────────────────────────────┼──────┤
│ 6. POST-PROCESSING & SELF-REFLECTION      │      │
│                                            ▼      │
│    _clean_generated_code()                        │
│       │ strip markdown fences (```...```)         │
│       │                                           │
│    python_sandbox.py                              │
│       │ run pytest + coverage + mutmut            │
│       │ if coverage < 80% or error: feed error    │
│       │ log back to LLM and retry (max 3 attempts)│
│       └──────────────────────────────────────────┘
│                                                  │
│  User Sees:  ✓ Generated file ready for download │
│             [Visual Coverage Highlighting UI]    │
└──────────────────────────────────────────────────┘
```

---

## 🧠 Deep Learning Techniques

### Overview Table

| # | Technique | Category | Role in UTcoder | Original LLM | UTcoder Advantage |
|---|-----------|----------|-----------------|--------------|-------------------|
| 1 | **Autoregressive Causal Language Modelling** | Inference | Core text generation — produces tests, compile checks, and coverage analyses token by token via `ChatOllama` | Generates free-form text from a raw prompt | Structured system prompts with language-specific instructions, framework constraints, and JSON output schemas |
| 2 | **Dense Text Embeddings** (Vector Representations) | Inference | Converts code chunks into 768-dimensional vectors via `OllamaEmbeddings` for semantic similarity search | No ability to search or rank document relevance | Enables efficient semantic search over code, selecting the most relevant sections for the prompt |
| 3 | **Retrieval-Augmented Generation (RAG)** | Inference | Retrieves top-4 relevant code chunks from ChromaDB and injects them into the LLM prompt as additional context | Only sees raw source file — no structured retrieval of related code | Provides function signatures, class hierarchies, and code patterns as context, enabling more informed test generation |
| 4 | **Parameter-Efficient Fine-Tuning (PEFT) — LoRA** | Training | Inserts low-rank adapter matrices into attention layers, specialising the model for test generation with minimal parameter changes | Generic code knowledge; not specialised for unit test generation | Produces higher-quality, more focused test outputs without full fine-tuning costs |
| 5 | **QLoRA (4-bit Quantisation + LoRA)** | Training | Loads the base model in 4-bit NF4 with double quantisation, enabling fine-tuning on 6GB GPUs | Standard fine-tuning requires 24GB+ VRAM for 7B models | Democratises fine-tuning — consumer GPU accessible |
| 6 | **Gradient Checkpointing** | Training | Recomputes activations during backpropagation instead of storing them | Standard training stores all intermediate activations | Enables longer sequences and larger models within the same memory budget |
| 7 | **Paged AdamW 8-bit Optimizer** | Training | Offloads optimizer states to CPU RAM when GPU memory is exhausted | Standard AdamW keeps full-precision states in GPU memory (~8 bytes/param) | Dramatically reduces GPU memory pressure |
| 8 | **Cosine LR Scheduling with Warmup** | Training | Warmup phase → high cosine LR → fine-grained decay for stable convergence | Constant or linear LR may overshoot minima or converge poorly | Stable early training followed by aggressive exploration then fine-grained convergence |
| 9 | **Supervised Fine-Tuning (SFT) with Chat Templates** | Training | Converts the dataset into chat-format messages (system/user/assistant) and trains with `SFTTrainer` | Pre-trained on raw text/code, not instruction format | Teaches the model to follow structured instructions (persona + task + output constraints) |
| 10 | **Language-Aware Recursive Text Splitting** | Preprocessing | Splits code at language-specific syntax boundaries for coherent chunks | No code chunking — full file as a single block | Preserves code structure so each chunk remains semantically meaningful |

---

### 1. Local LLM Inference — Autoregressive Causal Language Modelling

**File:** `core/llm.py`

Uses `ChatOllama` from LangChain, which wraps Ollama's local LLM inference. The model is a causal (autoregressive) transformer that generates one token at a time, conditioned on all previous tokens.

```python
@lru_cache(maxsize=1)
def get_llm() -> ChatOllama:
    cfg = get_config()["llm"]
    return ChatOllama(
        model=cfg["model"],
        temperature=cfg.get("temperature", 0.3),
    )
```

The system prompt passed to the LLM includes:
- Language-specific testing instructions (pytest conventions, JUnit annotations, xUnit patterns, Jest idioms)
- Test framework specification (configurable per language in `config.json`)
- Output format constraints (JSON schema for compile checks, code-only for generation)

**Achievements:**
- ✅ **Zero data leaves the machine** — complete privacy for proprietary codebases
- ✅ No API costs per generation
- ✅ Configurable model backend (DeepSeek Coder, CodeLlama, Llama 3, etc.)
- ✅ Streaming output for real-time display

**Limitations:**
- ❌ Smaller local models (7B) lag behind cloud APIs (GPT-4, Claude) in reliability
- ❌ CPU-only inference is slow; GPU acceleration strongly recommended
- ❌ Prompt sensitivity — small changes can significantly alter output quality

---

### 2. Dense Text Embeddings + Retrieval-Augmented Generation (RAG)

**Files:** `core/vectorstore.py`, `core/code_parser.py`

Code chunks are embedded into 768-dimensional dense vectors via `OllamaEmbeddings` (default embedding model: `nomic-embed-text`) and stored in ChromaDB for cosine similarity search.

```
Source Code ──→ Language-Aware Splitter ──→ Embedder ──→ ChromaDB Index
                                                           │
User Query ──→ Embedder ──→ ChromaDB Similarity Search ←──┘
                                                           │
                                              Top-4 chunks injected into LLM prompt
```

**Chunking strategy** (language-specific separators preserve code structure):

| Extension | Language | Split Separators |
|-----------|----------|-----------------|
| `.py` | Python | `def`, `class`, `return`, `import` |
| `.java` | Java | `{`, `}`, `;`, `public`, `class` |
| `.cs` | C# | `{`, `}`, `;`, `public`, `class` |
| `.js` / `.jsx` / `.mjs` / `.cjs` | JavaScript | `function`, `class`, `=>`, `{`, `}` |

```python
# Indexing
vs.index_documents(docs, col_name)

# Retrieval
context_snippets = vs.similarity_search(
    query=f"functions methods classes interfaces in {file_name}",
    collection_name=col_name, k=4,
)
```

**Achievements:**
- ✅ Context-aware test generation with semantically retrieved code context
- ✅ Persistent ChromaDB store — embeddings survive between sessions
- ✅ Language-aware chunking preserves code structure integrity
- ✅ Collection-per-file isolation prevents cross-contamination between different source files

**Limitations:**
- ❌ Synchronous re-indexing on every generation call (deletes & recreates the collection)
- ❌ Single embedding model (`nomic-embed-text`) — not specialised for code compared to CodeBERT, GraphCodeBERT, etc.
- ❌ Fixed 1000-char chunk size — large functions get split mid-body
- ❌ No hierarchical retrieval (flat chunks only, no class/function tree awareness)

---

### 3. Supervised Fine-Tuning (SFT) + LoRA / QLoRA

**File:** `core/dataset/ingest.py`

A complete fine-tuning pipeline that specialises a base LLM for unit test generation using the CodeRM_UnitTest dataset. Designed from the ground up for **6 GB GPU VRAM**.

#### Data Flow

```
CSV Dataset        ──→  Chat-Format JSONL    ──→  SFTTrainer     ──→  LoRA Adapter
(task_id,                (system + user +         (HuggingFace        (saved to
 question,                assistant messages)      Transformers)      finetune_output/)
 code_gt,
 unit_tests)
```

#### Memory Optimisation Stack

| Technique | What It Does | Memory Saving |
|-----------|-------------|---------------|
| **4-bit NF4 Quantisation** | Quantises model weights to 4-bit normal float format | ~4× vs 16-bit |
| **Double Quantisation** | Quantises the quantization constants themselves | ~0.5 GB additional |
| **LoRA (rank=16)** | Trains only ~0.1% of parameters via low-rank adapters | ~10× vs full fine-tune |
| **Gradient Checkpointing** | Recomputes activations on-the-fly instead of storing them | ~3× reduction |
| **Paged AdamW 8-bit** | Offloads optimizer states to CPU RAM when GPU is full | ~2× reduction |
| **Gradient Accumulation (4 steps)** | Simulates batch_size=4 with batch_size=1 memory usage | 4× effective batch |

```python
# BitsAndBytes 4-bit config
quant_cfg = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
)

# LoRA config (targeting all attention projection layers)
lora_cfg = LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
)
```

**Achievements:**
- ✅ Memory-efficient: fine-tunes 7B models on consumer GPUs with 6 GB VRAM
- ✅ Complete CLI pipeline: `python -m core.dataset.ingest train` handles ingestion → formatting → training → evaluation
- ✅ Chat template handling with automatic fallback for models missing `chat_template`
- ✅ Optional ChromaDB integration for retrieval-augmented training
- ✅ LoRA adapters are modular, swappable, and shareable — enabling task-specific model specialisation

**Limitations:**
- ❌ Short context window (default `max_seq_length=512`) — limits test complexity
- ❌ Hardcoded to CodeRM_UnitTest dataset schema (task_id, question, code_ground_truth, unit_tests columns)
- ❌ All training samples use the same system prompt — may limit framework/style diversity
- ❌ LoRA-only — no IA3, AdaLoRA, or full fine-tuning support
- ❌ Single-GPU only

---

### 4. AI-Based Compile Checking (Virtual Compiler)

**File:** `core/compiler.py`

Uses the LLM to simulate a compiler — reviewing generated test code for syntax errors, missing imports, incorrect API usage, and common mistakes without actually compiling or running anything.

```
Test Code ──→ LLM (with language-specific checklist)
                  │
                  ▼
            JSON Response
             ├── has_issues: true/false
             ├── issues: [{description, line_reference, suggestion}]
             └── overall_assessment: string
```

**Key design decisions:**
- Language-specific review checklists (Python: indentation, imports; Java: annotations, generics; C#: using directives, attributes; JS: async/await, module paths)
- Robust JSON extraction pipeline: strip markdown fences → regex JSON extraction → clean control characters → parse
- Fallback retry with stricter "JSON only" prompt on parse failure
- `quick_assessment()` shorthand returns a single word (GOOD / MINOR_ISSUES / BROKEN)

**Achievements:**
- ✅ Language-agnostic virtual compiler — works without any real compiler/runtime installed
- ✅ Structured JSON output with robust parsing and retry logic
- ✅ Fallback mechanism ensures graceful degradation on parse failures
- ✅ Quick one-word assessment for rapid feedback

**Limitations:**
- ❌ **Hallucination-prone** — may flag false positives or miss real errors depending on model quality
- ❌ No actual compilation — cannot catch runtime errors, logic bugs, or type-level issues
- ❌ Significant token and latency overhead
- ❌ JSON parsing remains fragile despite robust fallback strategies

---

### 5. AI-Based Coverage Analysis (Virtual Coverage)

**File:** `core/coverager.py`

Uses the LLM to estimate code coverage by analysing line-numbered source code alongside generated test code — without executing anything.

```
Source Code (with line numbers) ──┐
                                  ├──→ LLM ──→ JSON Response
Test Code                       ──┘         │
                                             ├── coverage_pct: 0–100
                                             ├── covered_items: [function names]
                                             ├── uncovered_items: [function names]
                                             ├── covered_lines: [line numbers]
                                             ├── uncovered_lines: [line numbers]
                                             └── suggestions: [improvement ideas]
```

**Key design decisions:**
- Source code is passed with line numbers (`_add_line_numbers()` helper) so the LLM can reference specific lines
- Conservative bias in the prompt: "If unsure whether a line is tested, mark it uncovered" — reduces overestimation
- Coverage percentage clamped to 0–100, line numbers filtered to valid range
- Results rendered visually in the Gradio UI: progress bar, colour-coded tags (≥80% green, ≥50% amber, <50% red)

**Achievements:**
- ✅ Zero-execution coverage — works for any language, even without CI/CD toolchains
- ✅ Line-level granularity with 1-based line number tracking
- ✅ Conservative bias reduces overestimation
- ✅ Rich visual UI with progress bars and colour-coded percentages

**Limitations:**
- ❌ **Fundamentally unreliable** — coverage is a runtime property; the LLM can only *guess*
- ❌ No branch/path coverage — cannot analyse complex control flow
- ❌ Context-window limited — large files may be truncated
- ❌ Cannot detect test *quality* (mutation testing) — only whether lines are *visited*, not whether bugs are caught

---

### 6. Language-Aware Code Parsing

**File:** `core/code_parser.py`

Maps file extensions to programming languages and uses LangChain's `RecursiveCharacterTextSplitter` with language-specific syntax separators.

| Extension | Language | LangChain Language |
|-----------|----------|--------------------|
| `.py` | Python | `Language.PYTHON` |
| `.java` | Java | `Language.JAVA` |
| `.cs` | C# | `Language.CSHARP` |
| `.js` / `.jsx` / `.mjs` / `.cjs` | JavaScript | `Language.JS` |

Each chunk is tagged with metadata (`source`, `language`, `chunk_index`) for traceability through the pipeline.

**Achievements:**
- ✅ Language-appropriate chunk boundaries preserve code structure (functions, classes stay intact)
- ✅ Metadata enrichment for traceability
- ✅ Visual icon mapping for UI display (🐍 ☕ ⚡ 📜)

**Limitations:**
- ❌ Only 4 languages — no Go, Rust, Ruby, C/C++, or TypeScript-specific parsing
- ❌ Static 1000-char chunks — not adaptive to function complexity
- ❌ No import/dependency analysis or cross-file reference resolution

---

### 7. Dual-Interface Architecture

**Files:** `main.py` (Gradio), `server.py` (REST), `vscode-extension/src/extension.ts` (VS Code)

Three distinct interfaces targeting different developer workflows, all backed by the same core pipeline:

| Interface | Technology | How to Use |
|-----------|-----------|-----------|
| **Gradio Web UI** | Python (Gradio) | `python main.py` → drag-and-drop files, stream output, view analysis panels |
| **VS Code Extension** | TypeScript + REST | Right-click any file → "UTcoder: Generate Unit Tests" or `Ctrl+Alt+G` |
| **REST API** | Python `http.server` | `python server.py` → programmatic endpoints for CI/CD integration |

**Achievements:**
- ✅ Multi-channel access for different developer workflows
- ✅ Deep VS Code integration: context menus, keyboard shortcuts, automatic `tests/` directory detection
- ✅ Clean REST interface enables CI/CD pipeline integration
- ✅ Rich visual analytics in Gradio: styled HTML with progress bars, colour-coded tags, card layouts
- ✅ Comprehensive CSS theming system with CSS custom properties for maintainability

**Limitations:**
- ❌ No authentication/authorisation on the HTTP server
- ❌ Plain HTTP only — no HTTPS
- ❌ Gradio app and REST server share no state — redundant configuration between `config.json` and VS Code settings
- ❌ REST API buffers full response before returning — no streaming for API callers

---

## 📊 Overall Assessment

### Maturity Matrix

| Technique | Maturity | Reliability | Innovation | Practical Utility |
|-----------|----------|-------------|------------|------------------|
| Local LLM Inference (Ollama) | 🟢 High | 🟡 Medium | 🟡 Medium | 🟢 High |
| Dense Text Embeddings + RAG | 🟢 High | 🟢 High | 🟡 Medium | 🟢 High |
| LoRA Fine-Tuning (PEFT) | 🟢 High | 🟡 Medium | 🟡 Medium | 🟢 High |
| Deep Learning Pipeline (QLoRA + SFT + Grad. Checkpoint. + 8-bit Opt.) | 🟢 High | 🟢 High | 🟢 High | 🟢 High |
| AI Compile Check (Virtual Compiler) | 🟡 Medium | 🟡 Medium | 🟢 High | 🟡 Medium |
| AI Coverage Analysis (Virtual Coverage) | 🔴 Low | 🔴 Low | 🟢 High | 🔴 Low |
| Self-Reflection Sandbox (Real Execution) | 🟢 High | 🟢 High | 🟢 High | 🟢 High |
| Language-Aware Code Parsing | 🟢 High | 🟢 High | 🔴 Low | 🟢 High |
| Dual-Interface Architecture | 🟢 High | 🟢 High | 🟡 Medium | 🟢 High |

### Advantages Over Using Original (Base) LLMs Alone

| Capability | Base LLM Alone | UTcoder (Base LLM + Pipeline) |
|------------|---------------|------------------------------|
| **Test generation** | Generic code completion; unstructured, unreliable output | Structured, framework-specific tests with proper imports, fixtures, mocking, and naming conventions |
| **Code understanding** | Raw file content only; limited by context window | Augmented with RAG-retrieved context (function signatures, class structures) |
| **Output format control** | Free-form text with markdown, explanations, or incomplete code | Clean code extraction: strips fences, prose, and commentary — outputs only valid test code |
| **Compile checking** | Not available natively | AI-based virtual compiler with structured JSON output |
| **Coverage estimation** | Not available natively | AI-based coverage analysis with line-level granularity |
| **Specialisation for testing** | General code knowledge only | Fine-tuned on CodeRM_UnitTest via LoRA — specialised for test generation |
| **Hardware requirements** | Minimal (inference only) | Fine-tuning requires 6 GB+ VRAM; inference remains lightweight |
| **Extensibility** | Cannot be updated without deploying a new model | LoRA adapters are modular, swappable, and shareable |

### Key Features of the Deep Learning Pipeline

| Feature | Technique | Implementation Detail |
|---------|-----------|----------------------|
| **Privacy-preserving inference** | Local LLM via Ollama | All computation on the user's machine — zero data leaves |
| **Context-aware generation** | RAG with ChromaDB | Top-4 semantically similar code chunks injected into the prompt |
| **Memory-efficient fine-tuning** | QLoRA + Gradient Checkpointing + 8-bit Opt. | Fine-tunes 7B models on 6 GB VRAM — ~4× memory reduction |
| **Structured output enforcement** | Prompt engineering + JSON retry | Forces JSON output with fallback parsing strategies |
| **Multi-language support** | Language-aware code parsing | 4 languages with framework-specific instructions |
| **Streaming inference** | `ChatOllama.stream()` | Real-time token display in the Gradio UI |
| **Chat-aligned training** | `SFTTrainer` + `apply_chat_template` | OpenAI-compatible chat format for instruction-tuned models |

### Summary

**UTcoder is strongest** as a local, privacy-preserving unit test generator augmented with RAG. Its deep learning foundation combines mature inference techniques (autoregressive LLMs, dense embeddings) with carefully optimised training techniques (QLoRA, gradient checkpointing, paged optimizers) to deliver production-quality test generation on consumer hardware.

Its most innovative techniques — **AI-based compile checking and coverage analysis** — are ambitious attempts to bring "virtual" developer tooling to any language without toolchain dependencies. These are inherently limited by their reliance on LLM reasoning rather than actual execution, but they demonstrate a novel direction for AI-assisted development.

The **fine-tuning pipeline** is particularly well-engineered for its target audience: developers with consumer GPUs. By combining QLoRA, gradient checkpointing, and paged AdamW, it achieves an approximately 4× memory reduction over standard LoRA, making model specialisation accessible without cloud compute.

---

## 📁 Full Project Structure

```
UTcoder/
├── main.py                          # Gradio UI entry point
├── server.py                        # HTTP REST API server
├── prepare_server.py                # Server packaging utility (utcoder_server.zip)
├── DEPLOYMENT.md                    # Server deployment guide
├── config.json                      # Local configuration
├── config.server.json               # Server configuration
├── docker-compose.yml               # Local Docker compose
├── docker-compose.server.yml        # Server Docker compose
├── requirements.txt                 # Python dependencies
├── core/
│   ├── __init__.py                  # Core package
│   ├── llm.py                       # Ollama LLM wrapper (cached singleton)
│   ├── generator.py                 # Test generation pipeline (RAG + LLM + Reflection)
│   ├── vectorstore.py               # ChromaDB indexing & similarity search
│   ├── code_parser.py               # Language detection & code chunking
│   ├── compiler.py                  # AI-based compile checking
│   ├── coverager.py                 # Visual HTML coverage parser
│   ├── sandbox/                     # Isolated test execution environment
│   │   ├── base.py                  # Abstract Sandbox & SandboxResult interfaces
│   │   └── python_sandbox.py        # Pytest, Coverage, and Mutmut integration
│   ├── config.py                    # Config file loader
│   └── dataset/
│       ├── ingest.py                # Fine-tuning pipeline (LoRA/QLoRA)
│       ├── split_dataset.py         # CSV splitter utility
│       ├── CodeRM_UnitTest/         # Training dataset (CSV chunks)
│       └── CodeRM_UnitTest (test)/  # Validation dataset (CSV chunks)
├── ui/
│   ├── app.py                       # Gradio web interface
│   └── __init__.py                  # UI package
├── finetune_output/                 # Fine-tuning checkpoints
└── vscode-extension/                # VS Code extension (TypeScript)
    ├── package.json                 # Extension manifest
    ├── src/extension.ts             # Extension logic
    └── scripts/build.cmd            # Build script
```

---

## 📜 License

This project is provided under the terms included in the VS Code extension LICENSE file.
