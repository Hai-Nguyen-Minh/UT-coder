# UT-Coder Deployment Guide

UT-Coder hỗ trợ 2 chế độ triển khai. Chọn chế độ phù hợp với phần cứng của bạn.

---

## Chế độ 1: Local (Chạy tất cả trên 1 máy có GPU)

Dành cho máy tính có card NVIDIA GPU (≥ 4GB VRAM).

### Yêu cầu
- Docker & Docker Compose
- NVIDIA GPU + NVIDIA Container Toolkit

### Cài đặt

```bash
# 1. Clone repo
git clone <repo-url> && cd UT-coder

# 2. Sử dụng config dành cho local
cp config.local.json config.json

# 3. Khởi động (Ollama + UT-Coder cùng chạy trên 1 máy)
docker compose up -d

# 4. Tải model AI (chỉ cần chạy 1 lần đầu)
docker compose exec ollama ollama pull qwen2.5-coder:7b
docker compose exec ollama ollama pull nomic-embed-text

# 5. (Tùy chọn) Nạp dataset vào ChromaDB
docker compose exec utcoder python core/dataset/embed_rag.py
docker compose exec utcoder python core/dataset/seed_fewshot_multilang.py
```

### Truy cập
- Giao diện: **http://localhost:7860**

### Dừng hệ thống
```bash
docker compose down
```

---

## Chế độ 2: Hybrid (Server + Local GPU)

Dành cho trường hợp bạn có:
- **Máy Local** (Windows/Linux): Có GPU, chạy AI (Ollama).
- **Server** (Linux): Không có GPU nhưng mạnh CPU/RAM, chạy UI + Sandbox.

Kiến trúc:
```
┌─────────────────────┐         SSH Tunnel          ┌──────────────────────┐
│   Máy Local (GPU)   │◄──────────────────────────►│    Server (No GPU)    │
│                     │   Port 11434 (Ollama API)   │                      │
│  - Ollama           │                             │  - UT-Coder UI       │
│  - qwen2.5-coder    │                             │  - Sandbox           │
│  - nomic-embed-text │                             │  - ChromaDB          │
└─────────────────────┘                             └──────────────────────┘
```

### Bước A: Chuẩn bị máy Local (có GPU)

```bash
# 1. Cài Ollama (https://ollama.ai) hoặc chạy qua Docker
docker compose up ollama -d

# 2. Tải model
docker compose exec ollama ollama pull qwen2.5-coder:7b
docker compose exec ollama ollama pull nomic-embed-text

# 3. Mở cổng Firewall (Windows - chạy PowerShell với quyền Admin)
New-NetFirewallRule -DisplayName "Ollama API" -Direction Inbound -LocalPort 11434 -Protocol TCP -Action Allow
```

### Bước B: Chuẩn bị Server

Vì Server không kết nối được với Git/Internet bên ngoài, bạn cần chuẩn bị sẵn một thư mục sạch từ máy Local và copy lên Server.

1. Chạy script chuẩn bị trên máy Local (máy Windows):
```bash
python prepare_server.py
```
*(Script này sẽ tạo ra thư mục `dist_server` chứa toàn bộ mã nguồn sạch, tự động đổi tên các file config và docker-compose phù hợp cho Server).*

2. Copy toàn bộ thư mục `dist_server` vừa tạo lên Server (thông qua phần mềm như WinSCP, FileZilla, hoặc copy trực tiếp).

3. Trên Server, vào thư mục vừa copy và khởi động UT-Coder:
```bash
cd dist_server
docker compose up -d
```

4. (Tùy chọn) Nếu bạn đã copy thư mục `chroma_db` từ máy Local lên chung chỗ với `dist_server`, bạn không cần chạy nạp dataset nữa. Nếu chưa, hãy chạy:
```bash
docker compose exec utcoder python core/dataset/embed_rag.py
docker compose exec utcoder python core/dataset/seed_fewshot_multilang.py
```

### Bước C: Kết nối 2 máy bằng SSH Tunnel

Từ **máy Local** (có GPU), mở terminal và chạy:
```bash
ssh -R 11434:localhost:11434 <user>@<server-ip>
```

Ví dụ:
```bash
ssh -R 11434:localhost:11434 sysadmin@172.16.10.58
```

> **Lưu ý quan trọng:**
> - Giữ nguyên cửa sổ SSH này, **KHÔNG ĐƯỢC ĐÓNG** (nếu đóng thì mất kết nối AI).
> - Nếu muốn chạy nền, thêm flag `-fN`: `ssh -fN -R 11434:localhost:11434 <user>@<server-ip>`
> - Kiểm tra kết nối bằng: `curl http://localhost:11434` (trên server, phải trả về "Ollama is running")

### Truy cập
- Giao diện: **http://<server-ip>:7860**

### Dừng hệ thống

Trên Server:
```bash
cd ~/UT-coder
docker compose -f docker-compose.server.yml down
```

Trên máy Local:
```bash
docker compose down
```

---

## Gỡ cài đặt hoàn toàn (Server)

Nếu server là máy dùng chung và bạn muốn xóa sạch:
```bash
cd ~/UT-coder
bash uninstall.sh
```

---

## Cấu trúc thư mục

```
UT-coder/
├── config.json                  # Config đang dùng (copy từ .local hoặc .server)
├── config.local.json            # Template: chạy tất cả trên 1 máy
├── config.server.json           # Template: chạy hybrid (server + local GPU)
├── docker-compose.yml           # Docker Compose cho chế độ Local
├── docker-compose.server.yml    # Docker Compose cho chế độ Server (không có Ollama)
├── Dockerfile                   # Build image UT-Coder
├── requirements.txt             # Python dependencies
├── main.py                      # Entry point
├── server.py                    # FastAPI server
├── uninstall.sh                 # Script gỡ cài đặt trên server
├── core/
│   ├── llm.py                   # LLM wrapper (đọc base_url từ config.json)
│   ├── generator.py             # Sinh unit test bằng AI + RAG
│   ├── compiler.py              # Self-reflection loop
│   ├── coverager.py             # Tính toán coverage
│   ├── vectorstore.py           # ChromaDB wrapper
│   ├── code_parser.py           # Parse code thành chunks
│   ├── config.py                # Đọc config.json
│   ├── sandbox/                 # Sandbox thực thi code
│   │   ├── python_sandbox.py
│   │   ├── java_sandbox.py
│   │   ├── js_sandbox.py
│   │   └── csharp_sandbox.py
│   └── dataset/                 # Dataset & RAG ingestion
│       ├── embed_rag.py         # Nạp dataset CSV vào ChromaDB
│       ├── seed_fewshot.py      # Seed Python few-shot examples
│       ├── seed_fewshot_multilang.py  # Seed Java/C#/JS few-shot examples
│       ├── ingest.py            # Fine-tuning pipeline
│       ├── split_dataset.py     # Chia dataset train/test
│       ├── CodeRM_UnitTest/     # Training data (CSV)
│       └── CodeRM_UnitTest (test)/  # Test data (CSV)
├── ui/
│   └── app.py                   # Gradio UI
└── vscode-extension/            # VS Code extension
```

---

## Câu hỏi thường gặp

**Q: Tại sao không để Ollama chạy luôn trên Server?**
A: Server không có GPU. Chạy AI bằng CPU sẽ cực kỳ chậm (2-5 từ/giây so với 20-30 từ/giây trên GPU).

**Q: SSH Tunnel bị đứt thì sao?**
A: Giao diện web vẫn hoạt động nhưng khi bấm Generate sẽ báo lỗi timeout. Chỉ cần mở lại SSH Tunnel là được.

**Q: Có thể dùng Ollama cài trực tiếp trên Windows thay vì Docker không?**
A: Có! Cài từ https://ollama.ai rồi chạy `ollama serve`. Nó sẽ tự lắng nghe trên port 11434. Lúc này không cần `docker compose up ollama` nữa.
