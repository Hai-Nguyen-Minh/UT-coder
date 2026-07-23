# Triển khai UT-Coder

Tài liệu này ưu tiên đúng kiến trúc đang sử dụng: AI chạy trên máy local có GPU; UI, ChromaDB, sandbox và benchmark chạy trên server Ubuntu.

## 1. Thành phần và yêu cầu

### Máy local có GPU

- Ollama đang hoạt động tại `127.0.0.1:11434`.
- Đủ RAM/VRAM cho từng model 7B/8B đã lượng tử hóa.
- Có SSH client và kết nối được tới server.
- Các model:

```bash
ollama pull qwen2.5-coder:7b
ollama pull llama3.1:8b
ollama pull nomic-embed-text
ollama list
```

Chỉ một model sinh code được giữ trong bộ nhớ tại một thời điểm. Benchmark sẽ unload model cũ và xác nhận qua Ollama trước khi chạy model tiếp theo.

### Server Ubuntu

Khuyến nghị Ubuntu 22.04/24.04, Docker Engine và Docker Compose plugin. Server cần CPU/RAM cho pytest, Coverage.py và mutmut; không cần GPU.

Kiểm tra nhanh:

```bash
docker --version
docker compose version
free -h
nproc
df -h
```

Các cổng ứng dụng:

- `7860`: Gradio UI.
- `8000`: REST API Python cho VS Code/automation; trong hybrid mặc định chỉ listen loopback.
- `11434`: reverse SSH chỉ cần listen trên loopback của server.

## 2. Tạo kết nối Ollama từ local tới server

Trên máy local, mở terminal riêng và giữ lệnh này trong suốt thời gian chạy:

```bash
ssh -N -R 11434:127.0.0.1:11434 <user>@<server-ip>
```

Ví dụ:

```bash
ssh -N -R 11434:127.0.0.1:11434 sysadmin@172.16.10.58
```

Kiểm tra trên server:

```bash
curl http://127.0.0.1:11434/api/tags
```

Nếu request không trả về danh sách model:

1. Kiểm tra `ollama ps` và `curl http://127.0.0.1:11434/api/tags` trên máy local.
2. Kiểm tra phiên SSH còn sống.
3. Kiểm tra port server chưa bị tiến trình khác chiếm: `ss -ltnp | grep 11434`.
4. Tạo lại tunnel với `-o ExitOnForwardFailure=yes` để SSH báo lỗi ngay:

```bash
ssh -N -o ExitOnForwardFailure=yes -R 11434:127.0.0.1:11434 <user>@<server-ip>
```

Không cần public port 11434 hoặc đổi Ollama thành `0.0.0.0`; để loopback an toàn hơn.

## 3. Chuẩn bị source đưa lên server

### Cách A — triển khai từ Git

```bash
git clone <repo-url> utcoder
cd utcoder
```

Repository chỉ commit một `config.json`. `docker-compose.server.yml` truyền các ghi đè môi trường cần thiết; không copy/đổi tên config theo máy.

Khởi động bằng file Compose server:

```bash
docker compose -f docker-compose.server.yml build utcoder
docker compose -f docker-compose.server.yml up -d utcoder utcoder-api
```

### Cách B — server không lấy được Git

Trên máy chứa repository:

```bash
python prepare_server.py
```

Script tạo `utcoder_server.zip` với:

- runtime trong `core/` và `ui/`;
- `config.json` duy nhất;
- `docker-compose.server.yml` được đổi tên thành `docker-compose.yml` trong ZIP;
- `valid_dataset.json` để có thể dựng lại ChromaDB;
- ChromaDB hiện có, nếu thư mục `chroma_db/` tồn tại;
- dependency/runtime cần cho server.

Script không đóng gói file Markdown, raw dataset, regression tests, cache, log hoặc kết quả benchmark.

Copy và giải nén trên server:

```bash
scp utcoder_server.zip <user>@<server-ip>:~/
ssh <user>@<server-ip>
mkdir -p ~/utcoder
unzip -o ~/utcoder_server.zip -d ~/utcoder
cd ~/utcoder
docker compose build utcoder
docker compose up -d utcoder utcoder-api
```

Trong gói ZIP, file Compose đã là bản server nên không có service Ollama.

## 4. Cấu hình môi trường

Giá trị mặc định trong `config.json` phù hợp với hybrid: Ollama ở `http://localhost:11434`, temperature `0.1`, ChromaDB tại `./chroma_db`.

Chỉ tạo `.env` khi cần ghi đè:

```bash
cp .env.example .env
```

Ví dụ cấu hình server thận trọng:

```dotenv
UTCODER_OLLAMA_BASE_URL=http://localhost:11434
UTCODER_LLM_MODEL=qwen2.5-coder:7b
UTCODER_LLM_TEMPERATURE=0.1
UTCODER_CHROMA_DIR=./chroma_db
UTCODER_API_HOST=127.0.0.1
UTCODER_API_PORT=8000
UTCODER_API_TOKEN=<random-secret>
UTCODER_EVAL_MUTATION_TIMEOUT=180
UTCODER_EVAL_MUTATION_CHILDREN=2
UTCODER_EVAL_MUTATION_MEMORY_MB=1536
UTCODER_EVAL_MAX_PROCESSES=32
```

Sau khi đổi `.env`, recreate container:

```bash
docker compose up -d --force-recreate utcoder
docker compose up -d --force-recreate utcoder-api
```

Không commit `.env` vì về sau có thể chứa địa chỉ hoặc bí mật riêng của hệ thống.

## 5. Preflight bắt buộc

Sau build/rebuild, chạy đúng một dòng để tránh lỗi shell do xuống dòng sai:

```bash
docker compose -f docker-compose.yml exec utcoder python -m core.sandbox.preflight
```

Nếu triển khai trực tiếp từ Git bằng file server chưa đổi tên:

```bash
docker compose -f docker-compose.server.yml exec utcoder python -m core.sandbox.preflight
```

Kết quả mong đợi:

```text
Sandbox preflight passed (coverage=100.0%).
Evaluator preflight passed (score=100.0, mutants=6).
```

Preflight kiểm tra hai tầng:

- pytest/coverage trong sandbox, gồm quyền ghi temp và pycache;
- evaluator thật với compile, collection, ba lượt chạy, coverage và mutmut.

Không chạy benchmark dài nếu một trong hai tầng thất bại. Lỗi preflight là lỗi hạ tầng, không phải lỗi model.

### Lỗi permission trong `/tmp/.../pycache/tmp`

Đây thường là image/container cũ chưa có thay đổi UID/GID hoặc quyền temp của sandbox. Thực hiện:

```bash
docker compose down
docker compose build --no-cache utcoder
docker compose up -d utcoder
docker compose up -d utcoder-api
docker compose exec utcoder python -m core.sandbox.preflight
```

Nếu dùng file server trong Git, thêm `-f docker-compose.server.yml` vào từng lệnh.

## 6. Khởi tạo hoặc cập nhật ChromaDB

Nếu gói đã mang theo `chroma_db/` hợp lệ, có thể bỏ qua bước này. Nếu thay `valid_dataset.json`, schema RAG hoặc embedding model, chạy trên server trong khi tunnel Ollama đang hoạt động:

```bash
docker compose exec utcoder python core/dataset/prepare_rag_dataset.py
docker compose exec utcoder python core/dataset/prepare_rag_dataset.py --write
docker compose exec utcoder python core/dataset/embed_rag.py
docker compose exec utcoder python core/dataset/seed_fewshot_multilang.py
```

Lần đầu là dry-run. Kiểm tra số `rag_eligible` rồi mới chạy `--write`. Embed build collection tạm và chỉ thay collection live khi hoàn tất, nên không kích hoạt index dở dang.

Trong kiến trúc hybrid, ChromaDB vẫn nằm trên server; chỉ phép tính embedding được gọi qua Ollama local.

## 7. Kiểm tra ứng dụng

```bash
docker compose ps
docker compose logs --tail=200 utcoder
docker compose logs --tail=200 utcoder-api
curl http://127.0.0.1:7860
curl http://127.0.0.1:8000/api/health
```

Mở từ máy người dùng:

```text
http://<server-ip>:7860
```

Không cần public cổng 8000. Trên máy chạy VS Code, mở local-forward riêng:

```bash
ssh -N -L 8000:127.0.0.1:8000 <user>@<server-ip>
```

Extension dùng `http://localhost:8000`. Nếu `.env` có `UTCODER_API_TOKEN`, chạy command **UTcoder: Set API Token** để lưu cùng token trong VS Code SecretStorage. Chỉ public cổng 7860 nếu cần; không public sandbox, API hoặc Ollama trực tiếp ra Internet.

## 8. Chạy benchmark trên server

Chạy trực tiếp:

```bash
docker compose exec utcoder python core/benchmark/evaluate_models.py
```

Lệnh trên resume benchmark 50 task của hai model. Chỉ sau khi benchmark chính hoàn tất thành công và model cuối đã được unload, tiến trình tự chuyển sang workbench RAG ablation 20 project-task × 2 điều kiện với Qwen. Kết quả RAG được lưu riêng trong `core/benchmark/rag_ablation/`, không ghi vào CSV benchmark model.

Chạy nền qua SSH:

```bash
nohup docker compose exec -T utcoder python core/benchmark/evaluate_models.py > benchmark_run.log 2>&1 &
```

Theo dõi:

```bash
tail -f benchmark_run.log
tail -f core/benchmark/benchmark_progress.log
```

Chạy lại chỉ các cặp model/task fail hoặc chưa đủ điểm từ file cũ:

```bash
docker compose exec utcoder python core/benchmark/evaluate_models.py --rerun-failed-from core/benchmark/benchmark_results.csv
```

Failed-only mode không tự chạy RAG ablation. Có thể chạy/resume workbench này độc lập:

```bash
docker compose exec utcoder python -m core.benchmark.rag_ablation.evaluate_rag_ablation --condition both
```

Muốn hoàn tất benchmark chính mà không chain workbench RAG:

```bash
docker compose exec utcoder python core/benchmark/evaluate_models.py --skip-rag-ablation
```

Trước lượt chạy chính thức, validate 20 project-task:

```bash
docker compose exec utcoder python -m core.benchmark.rag_ablation.validate_dataset
```

Không chèn khoảng trắng sau ký tự `\` trong lệnh shell. An toàn nhất là dùng lệnh một dòng như trên; lỗi `exec: " ": executable file not found` là do Docker nhận một chuỗi khoảng trắng làm executable.

Chi tiết output và công thức ở [core/benchmark/BENCHMARK.md](core/benchmark/BENCHMARK.md).

## 9. Khi nào cần rebuild

Cần rebuild image khi thay:

- `Dockerfile`;
- `requirements.txt` hoặc `core/sandbox/requirements-eval.txt`;
- UID/GID, runtime Python hoặc dependency evaluator đã đổi trong image.

Chỉ cần restart/recreate khi thay:

- `config.json`, `.env`, Compose hoặc command;
- source Python nếu không bind-mount source.

Compose hiện bind-mount repository vào `/app`, nên sửa source Python thường chỉ cần restart process/container. Trước benchmark chính thức vẫn nên build image từ commit sẽ chạy để tránh source và dependency lệch nhau.

## 10. Cập nhật phiên bản an toàn

```bash
git pull --ff-only
docker compose build utcoder
docker compose up -d utcoder utcoder-api
docker compose exec utcoder python -m core.sandbox.preflight
```

Nếu đang có benchmark chạy, chờ hoàn thành hoặc dừng rõ ràng trước khi recreate container. Lưu file CSV/JSONL và thư mục artifact ra nơi backup nếu cần giữ lịch sử.

## 11. Dừng và gỡ

Dừng nhưng giữ image/data:

```bash
docker compose down
```

`uninstall.sh` là thao tác xóa mạnh dành cho server. Đọc script và xác nhận đúng thư mục trước khi chạy; không dùng trong lúc còn dữ liệu benchmark/ChromaDB chưa backup.

## 12. Chế độ all-in-one tùy chọn

Chế độ này dành cho máy Linux có GPU và NVIDIA Container Toolkit. File `docker-compose.yml` ở repository khởi động cả app và Ollama:

```bash
docker compose up -d
docker compose exec ollama ollama pull qwen2.5-coder:7b
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec utcoder python -m core.sandbox.preflight
```

Compose tự đặt `UTCODER_OLLAMA_BASE_URL=http://ollama:11434`; không cần file config local riêng.
