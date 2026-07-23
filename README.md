# 🧪 UTcoder — AI-Powered Unit Test Generator

**Local. Private. Offline.** UTcoder là hệ thống sinh unit test Python tự động từ source code bằng cách kết hợp **LLM** (local qua Ollama), **RAG** (Retrieval-Augmented Generation với ChromaDB) và **Real Sandbox Execution**. Phạm vi sản phẩm hiện tại được chốt là **Python-only**. Những file runner/cấu hình Java, C# và JavaScript còn trong repository chỉ là prototype cũ và định hướng tương lai, chưa phải tính năng được hỗ trợ chính thức.

Phiên bản hiện tại giữ nguyên nền tảng đó nhưng bổ sung lớp kiểm chứng thực thi: test được chạy trong sandbox, đo coverage thật, self-reflection theo log lỗi và đánh giá chất lượng bằng mutation testing. Trọng tâm benchmark hiện tại là Python với hai mô hình local:
- `qwen2.5-coder:7b`
- `llama3.1:8b`

Khác với các công cụ AI gen code thông thường, UTcoder **không coi câu trả lời của LLM là kết quả cuối**. Mọi unit test Python được sinh ra đều phải trải qua một vòng lặp: **Biên dịch → Chạy thật → Đo Coverage → LLM Tự sửa lỗi (Reflection) → Đánh giá bằng Mutation Testing**.

---

## 🌟 Tính năng Nổi bật (Key Features)

1. **Private & Local**: Mã nguồn không bao giờ bị gửi lên cloud. Mọi thứ chạy trên máy chủ nội bộ hoặc máy cá nhân của bạn. Dữ liệu không đi ra dịch vụ AI bên thứ ba.
2. **Context-Aware (RAG)**: Sử dụng ChromaDB để tự động tìm kiếm các đoạn code liên quan và các mẫu test chuẩn (few-shot) để đưa vào ngữ cảnh cho AI.
3. **Execution & Self-Reflection**: Test sinh ra được ném vào Sandbox chạy thử (`pytest`). Nếu có lỗi, AI sẽ đọc Log lỗi để tự sửa chữa (Targeted Reflection).
4. **Advanced Python Test Evaluator**: Test không chỉ cần "pass", mà còn bị thử thách bởi **Mutation Testing** (`mutmut`), đo **Branch Coverage**, và kiểm tra độ ổn định (**Flakiness check**).

---

## 🏗️ Kiến Trúc Hệ Thống (System Architecture)

UTcoder được thiết kế theo mô hình **Hybrid Deployment**: Tách biệt phần AI nặng nề (chạy trên máy có GPU) và phần lõi nghiệp vụ/Giao diện (chạy trên Server Ubuntu).

```text
┌────────────────────────────── INTERFACE LAYER ──────────────────────────────┐
│                                                                             │
│  ┌──────────────────┐      ┌────────────────────┐      ┌─────────────────┐  │
│  │ Gradio Web UI    │      │ VS Code Extension  │      │ REST/CLI        │  │
│  │ upload/download  │      │ right-click source │      │ automation      │  │
│  └────────┬─────────┘      └──────────┬─────────┘      └───────┬─────────┘  │
│           └───────────────────────────┼─────────────────────────┘           │
│                                       ▼                                     │
│                              server.py / main.py                            │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
┌────────────────────────────── SERVER UBUNTU ────────────────────────────────┐
│                                       ▼                                     │
│  ┌──────────────────────── generator.py ─────────────────────────────────┐  │
│  │ code_parser.py → source_analyzer.py → RAG retrieval                   │  │
│  │       │                  │                 │                          │  │
│  │       │                  ├─ behavioral probing                        │  │
│  │       │                  └─ code generation/mocking route             │  │
│  │       │                                    │                          │  │
│  │       └────────────────────────────────────┼─► prompt + reflection    │  │
│  └────────────────────────────────────────────┼──────────────────────────┘  │
│                                               │                             │
│  ChromaDB ◄── valid_dataset.json              │ reverse SSH                 │
│     ▲          → quality gate                 │ localhost:11434             │
│     └──────────→ nomic-embed-text ────────────┼───────────────┐             │
│                                               │               │             │
│  ast_patcher.py ◄── sandbox pytest/coverage ◄─┘               │             │
│                         │                                     │             │
│                         └─ benchmark evaluator + mutmut       │             │
└───────────────────────────────────────────────────────────────┼─────────────┘
                                                                │
┌──────────────────────────── MÁY LOCAL CÓ GPU ─────────────────▼─────────────┐
│ Ollama: qwen2.5-coder:7b, llama3.1:8b, nomic-embed-text                     │
│ Chỉ chạy model inference/embedding; không chạy sandbox hoặc ChromaDB        │
└─────────────────────────────────────────────────────────────────────────────┘
```

> **Giải thích**: Máy local (của Dev) chỉ chịu tải chạy Ollama. Source code, Vector Database, Sandbox, và Web UI nằm toàn bộ trên Server Ubuntu. Hai bên kết nối bảo mật qua Reverse SSH tunnel (`localhost:11434`), không cần mở port Ollama ra ngoài Internet.

---

## 🔄 Luồng Xử Lý Chi Tiết (Pipeline Deep-Dive)

Đây là hành trình từ lúc upload source file cho đến khi nhận được test đã kiểm chứng:

```text
Người dùng upload/chọn source file
        │
        ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ 1. PYTHON SOURCE DETECTION & PARSING                                       │
│    xác nhận file .py → parse_code() → Python-aware chunks                  │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ 2. SOURCE ANALYSIS & STRATEGY ROUTING                                      │
│    AST/source contract                                                     │
│      ├─ hàm thuần, kiểu JSON cơ bản → behavioral probing                   │
│      └─ OOP/dependency/I/O phức tạp → code generation + mocks              │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ 3. EMBEDDING & RAG RETRIEVAL                                               │
│    source query → nomic-embed-text → ChromaDB similarity search            │
│    lấy code chunks + few-shot tests đã qua quality gate                    │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ 4. PROMPT CONSTRUCTION / BEHAVIORAL PLAN                                   │
│    source + framework rules + RAG context + strategy-specific schema       │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ 5. LOCAL LLM INFERENCE                                                     │
│    server → reverse SSH → Ollama local                                     │
│    qwen2.5-coder:7b hoặc llama3.1:8b, temperature=0.1                      │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ 6. NORMALIZATION & REAL SANDBOX                                            │
│    clean markdown/prose → normalize imports/module → arity validation      │
│    compile → pytest → Coverage.py                                          │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      ▼
                      ┌──────────── test/coverage đạt? ────────────┐
                      │ Không                                      │ Có
                      ▼                                            ▼
┌──────────────────────────────────────────────┐   ┌─────────────────────────┐
│ 7. TARGETED SELF-REFLECTION                  │   │ 8. FINAL CANDIDATE      │
│    error log/missing lines → LLM repair      │   │ giữ candidate tốt nhất  │
│    AST patch Class::method / expansion       │   │ trả file + coverage UI  │
│    fast retry cho missing relative directory │   └─────────────┬───────────┘
└───────────────────────┬──────────────────────┘                 │
                        └───────── quay lại sandbox ─────────────┘
                                                                 │
                                                                 ▼
                                        Benchmark: 3× stability → branch
                                        coverage → mutmut → final score
```

### Điểm nhấn Công nghệ:
- **Behavioral Probing & Fast Retry**: Chuyên trị lỗi "đoán mò" (Oracle problem) của AI cỡ nhỏ. Thay vì bắt AI tự viết toàn bộ đoạn code `pytest` và tự đoán kết quả Output, hệ thống chia việc:
  - **AI đóng vai trò "Người lên kịch bản":** Chỉ đề xuất các Input cần test (VD: chuỗi rỗng, mảng âm...).
  - **Server đóng vai trò "Thợ gõ code":** Lấy các Input đó chạy thử trên Sandbox để xem hàm trả về kết quả gì, sau đó Server sẽ tự động gen ra đoạn code `pytest` cuối cùng dựa trên kết quả chạy thật.
  - *(Lưu ý: Chỉ áp dụng cho Hàm thuần. Với code OOP hay có kết nối Database, hệ thống sẽ tự chuyển về chiến lược bắt AI viết toàn bộ code kiểu truyền thống).*
  - Nếu thiếu thư mục tương đối lúc chạy thử, sandbox sẽ tự tạo thư mục an toàn và thử lại nhanh (fast-retry) mà không cần AI can thiệp.
- **Targeted Self-Reflection**: Khi test lỗi, thay vì hỏi lại mù quáng, hệ thống parse log `FAILED`/`ERROR` hoặc dùng AST Patcher để chắp vá hàm/method cụ thể. Nếu coverage dưới 80%, quá trình reflection vẫn tiếp tục để tăng độ phủ.
- **Giới hạn tài nguyên (Sandbox Limits)**: Mã do AI tạo chạy trong môi trường có kiểm soát (UID/GID riêng, timeout, RAM, số processes) để tránh lạm dụng hệ thống.

---

## 🧠 Nền tảng AI và Kỹ thuật Lõi (Technical Overview)

Bên dưới pipeline trên, UTcoder sử dụng các kỹ thuật sau:

| Kỹ thuật | Thành phần | Vai trò hiện tại |
|---|---|---|
| Autoregressive causal language modelling | `core/llm.py` | Sinh test theo token bằng model Ollama local |
| Dense text embeddings | `core/vectorstore.py` | Biến source/ví dụ thành vector để tìm kiếm ngữ nghĩa |
| Retrieval-Augmented Generation | ChromaDB + generator | Đưa các đoạn code và mẫu test liên quan vào prompt |
| Fine-tuning thử nghiệm | `core/dataset/ingest.py` | Có mã SFT/LoRA/QLoRA cũ nhưng không được runtime hay benchmark gọi |
| Gradient checkpointing & Paged AdamW | Pipeline training | Kỹ thuật tối ưu bộ nhớ khi train/fine-tune |
| Python-aware splitting | `core/code_parser.py` | Chia source Python theo biên hàm/lớp để phục vụ RAG |
| Structured output | Prompt + JSON repair | Giảm output thừa/sai JSON trong compile check và behavioral plan |
| Real execution feedback | `core/sandbox/` | Thay suy đoán bằng compile, pytest và coverage thật |

### 1. Phạm vi Python hiện tại và định hướng đa ngôn ngữ

`core/code_parser.py` có ánh xạ extension cho nhiều ngôn ngữ từ kiến trúc cũ, nhưng luồng được kiểm chứng và benchmark chính thức hiện chỉ dành cho Python:

| Ngôn ngữ | Trạng thái | Ghi chú |
|---|---|---|
| Python/pytest | Hỗ trợ chính thức | Có normalize, sandbox, reflection, stability, coverage và mutation |
| Java/JUnit 5 | Định hướng tương lai | Runner hiện tại chỉ là prototype, chưa có evaluator/preflight chuẩn |
| C#/xUnit | Định hướng tương lai | Runner hiện tại chỉ là prototype, chưa có evaluator/preflight chuẩn |
| JavaScript/Jest | Định hướng tương lai | Runner hiện tại chỉ là prototype, chưa có evaluator/preflight chuẩn |

Không dùng kết quả từ các runner prototype để công bố pass rate hoặc so sánh model. Khi mở lại hướng đa ngôn ngữ, mỗi ngôn ngữ phải có dependency offline, resource limit, preflight, dataset unseen và mutation evaluator riêng.

### 2. Trạng thái của SFT, LoRA và QLoRA
Mặc dù có mã PEFT trong `core/dataset/ingest.py`, hiện tại **hệ thống đang chạy các model LLM gốc** kết hợp RAG. Kết quả benchmark hiện tại (Qwen/Llama) đều là của mô hình không qua fine-tune chuyên biệt.

### 3. Compile check và coverage: Từ AI ước lượng đến thực thi thật
Trước đây, hệ thống dùng LLM làm "virtual compiler" (AI tự suy đoán code có chạy được không và coverage bao nhiêu). Hiện nay Python luôn chạy test thật và lấy coverage thật. Phần AI review/estimate cùng các runner ngôn ngữ khác chỉ được giữ như mã prototype; chúng không nằm trong tiêu chí pass/fail hoặc benchmark chính thức.

---

## 📈 Đánh giá Kiến trúc Hiện tại (Overall Assessment)

Phần này đặc biệt quan trọng để team nắm được mức độ trưởng thành của từng module:

| Thành phần | Mức trưởng thành | Nhận xét |
|---|---|---|
| Ollama local inference | Cao | Riêng tư, dễ đổi model; chất lượng phụ thuộc model 7B/8B |
| Dense embedding + RAG | Cao | Có dataset gate và atomic collection activation |
| Mã thử nghiệm LoRA/QLoRA | Chưa tích hợp | Có trong `ingest.py`, không được runtime/benchmark sử dụng |
| AI compile/coverage fallback | Prototype | Không dùng làm ground truth hoặc kết quả công bố |
| Python sandbox + reflection | Cao | Dùng lỗi và coverage runtime thật, có resource limit |
| Behavioral probing | Khá | Tốt cho hàm thuần; OOP/dependency ngoài phải route sang code/mocking |
| Python benchmark evaluator | Cao | Có hard gate, stability, branch và mutation |
| UI/API/VS Code | Khá | Nhiều cách truy cập nhưng deployment public cần auth/TLS |

> So với việc chỉ gọi LLM trực tiếp, UTcoder bổ sung context RAG, chuẩn hóa output, chạy test thật, tự sửa lỗi có định hướng và chấm điểm qua mutation. Trọng tâm gần hạn là nâng chất lượng Python và khả năng unseen. Java/C#/JavaScript chỉ là định hướng sau khi pipeline Python đạt độ ổn định mong muốn.

---

## 💻 Giao Diện & Tích Hợp (Interfaces)

Gradio và REST API là hai process riêng nhưng cùng gọi pipeline Python đã kiểm chứng. `main.py` chạy UI trên cổng 7860; `server.py` chạy API trên cổng 8000 để phục vụ VS Code và automation.

| Giao diện / API | Vai trò / Cách dùng |
|---|---|
| **Gradio Web UI** | Giao diện kéo thả trực quan (`http://localhost:7860`). |
| **VS Code Extension** | Chỉ hiện trên file `.py`; gọi REST API, chờ sandbox + reflection và chỉ ghi file khi server trả candidate đã được chấp nhận. |
| `GET /api/health` | Kiểm tra Ollama/model, ChromaDB và dependency sandbox; thêm `?deep=1` để chạy preflight thật. |
| `POST /api/generate` | Sinh test qua RAG → Ollama → pytest/coverage → self-reflection; không trả code chưa đạt gate 80%. |
| `POST /api/compile-check` | Kiểm tra test Python bằng sandbox thật. |
| `POST /api/coverage` | Đo coverage Python bằng sandbox thật. |

API mặc định chỉ listen ở `127.0.0.1:8000` trong mô hình hybrid. Extension kết nối qua SSH local-forward, vì vậy không cần public cổng 8000:

```bash
ssh -N -L 8000:127.0.0.1:8000 <user>@<server-ip>
```

Nếu đặt `UTCODER_API_TOKEN` trên server, chạy command **UTcoder: Set API Token** trong VS Code để lưu cùng giá trị bằng SecretStorage. API có giới hạn kích thước body, hỗ trợ timeout/cancel phía extension và chỉ cho một lượt generation tại một thời điểm để tránh hai request tranh RAM/GPU.

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy Nhanh (Quick Start)

### Cấu hình (Config)
Toàn bộ cấu hình hệ thống nằm ở `config.json` và các biến môi trường (Environment Variables). Không còn các file `config.local.json` riêng lẻ.
Một số biến quan trọng:
- `UTCODER_OLLAMA_BASE_URL`: Địa chỉ Ollama (mặc định `http://localhost:11434`).
- `UTCODER_LLM_MODEL` / `UTCODER_LLM_TEMPERATURE`: Mô hình LLM và nhiệt độ mặc định (mặc định 0.1).
- `UTCODER_CHROMA_DIR`: Nơi lưu trữ vector DB (mặc định `./chroma_db`).
- `UTCODER_API_HOST` / `UTCODER_API_PORT`: địa chỉ bind riêng của REST API.
- `UTCODER_API_TOKEN`: bearer token tùy chọn; nên đặt nếu API không hoàn toàn nằm sau SSH/firewall.
- Sandbox Limits: `UTCODER_EVAL_MAX_PROCESSES`, `UTCODER_EVAL_MUTATION_TIMEOUT`, v.v.

*(Tạo file `.env` từ `.env.example` nếu cần ghi đè, không commit `.env`)*

### Mô hình 1: Hybrid (Dành cho Production / Team nhỏ)
*Tách AI chạy ở Local PC có GPU. Code và Server chạy ở máy chủ Ubuntu.*

1. **Trên máy Local (PC có GPU):**
   ```bash
   ollama pull qwen2.5-coder:7b && ollama pull llama3.1:8b && ollama pull nomic-embed-text
   ssh -N -R 11434:127.0.0.1:11434 <user>@<server-ip>
   ```

2. **Trên Server Ubuntu:**
   ```bash
   docker compose -f docker-compose.server.yml build utcoder
   docker compose -f docker-compose.server.yml up -d utcoder utcoder-api
   # Chạy kiểm tra (Preflight)
   docker compose -f docker-compose.yml exec utcoder python -m core.sandbox.preflight
   ```

### Mô hình 2: All-in-one (Dành cho Phát triển / Thử nghiệm)
*Chạy cả Server và AI trên cùng 1 máy có GPU (Cần Docker NVIDIA Toolkit).*
```bash
docker compose up -d
docker compose exec ollama ollama pull qwen2.5-coder:7b
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec ollama ollama pull nomic-embed-text
```

---

## 📁 Cấu Trúc Mã Nguồn (Project Structure)

Bản đồ mã nguồn giúp team dễ dàng theo dõi:
```text
UT-coder/
├── config.json                       # Cấu hình trung tâm
├── main.py / server.py               # Entry points (Gradio UI / REST API)
├── docker-compose.yml                # Cấu hình Docker
├── prepare_server.py                 # Script tạo gói utcoder_server.zip để deploy
│
├── core/                             # LÕI HỆ THỐNG
│   ├── llm.py                        # Gọi Ollama
│   ├── generator.py                  # Kịch bản chính (RAG + AI + Sandbox)
│   ├── vectorstore.py                # ChromaDB
│   ├── source_analyzer.py            # Phân tích AST, quyết định chiến lược
│   ├── behavioral_testing.py         # Sandbox probe
│   ├── ast_patcher.py                # Vá test có mục tiêu (Reflection)
│   │
│   ├── dataset/                      # Quản lý Dữ liệu Mẫu
│   │   ├── valid_dataset.json        # Dữ liệu chuẩn
│   │   └── embed_rag.py              # Script nạp dữ liệu vào ChromaDB
│   │
│   ├── sandbox/                      # Môi trường Sandbox
│   │   ├── python_sandbox.py         # Pytest & Coverage
│   │   └── internal/eval_runner.py   # Advanced Evaluator (Mutmut, Stability)
│   │
│   └── benchmark/                    # Benchmark model + RAG ablation
│       ├── evaluate_models.py        # 50 task/model, tự chain workbench RAG
│       └── rag_ablation/             # 20 project-task, RAG ON/OFF ghép cặp
│
├── python_codegen_benchmark_20/      # Fixtures benchmark
├── tests/                            # Unit tests của chính dự án UTcoder
├── ui/                               # Giao diện Gradio
└── vscode-extension/                 # Source extension VS Code
```

---

## 🛠️ Các Lệnh Hữu Ích

**Nạp lại CSDL RAG (ChromaDB)** (Chỉ chạy khi thêm/sửa file `valid_dataset.json`):
```bash
python core/dataset/prepare_rag_dataset.py --write
python core/dataset/embed_rag.py
```

**Đóng gói Server để Deploy**:
```bash
python prepare_server.py
```
> Script này gói gọn file cấu hình và mã nguồn ra `utcoder_server.zip` (loại bỏ markdown, tests, log, raw dataset) kèm theo ChromaDB hiện tại.

Image production hiện chỉ cài Python và evaluator Python. Java/Maven, Node.js và .NET không còn được cài trong Docker image; đa ngôn ngữ là định hướng tương lai và sẽ cần image/evaluator riêng.

**Chạy Regression Tests của Dự án**:
```bash
python -m pytest -q
```

**Chạy/resume benchmark chính rồi tự động chuyển sang RAG ablation**:

```bash
python core/benchmark/evaluate_models.py
```

Chi tiết dataset, kết quả riêng và cách chạy từng điều kiện nằm trong `core/benchmark/BENCHMARK.md`.

**Build và cài VS Code extension**:

```bash
cd vscode-extension
npm ci
npm run compile
npx @vscode/vsce package --out utcoder-vscode.vsix
code --install-extension utcoder-vscode.vsix
```

Sau khi server chạy, mở SSH local-forward ở trên rồi đặt `utcoder.serverUrl=http://localhost:8000`. Chi tiết nằm trong `vscode-extension/README.md`.

---

## 📚 Tài liệu liên quan
- [DEPLOYMENT.md](DEPLOYMENT.md): Hướng dẫn chi tiết setup SSH, Docker và xử lý lỗi Ubuntu.
- [core/benchmark/BENCHMARK.md](core/benchmark/BENCHMARK.md): Chi tiết luật chấm điểm Benchmark, Stability, Mutation.
- [CHANGELOG.md](CHANGELOG.md): Các thay đổi so với hệ thống ban đầu.
