# Nhật ký thay đổi UT-Coder

Tài liệu này tóm tắt đợt nâng cấp hiện tại so với phiên bản sinh test một lượt ban đầu. Chi tiết vận hành nằm trong `README.md`, `DEPLOYMENT.md` và `core/benchmark/BENCHMARK.md`.

## Phạm vi sản phẩm

- Phạm vi được hỗ trợ và benchmark chính thức hiện tại là Python/pytest.
- Java, C# và JavaScript chỉ là prototype cũ và định hướng tương lai.
- Config, Docker image, Gradio, REST API và VS Code extension production đều được thu hẹp về Python.

## Luồng sinh và self-reflection

- Thay luồng “LLM sinh rồi trả ngay” bằng `generate_with_reflection`.
- Test Python được compile, chạy thật bằng pytest và đo Coverage.py trong sandbox.
- Candidate chỉ được chấp nhận khi pytest pass, coverage hợp lệ và line coverage đạt tối thiểu 80%.
- Giữ candidate chạy được/có coverage tốt nhất xuyên suốt các lượt reflection.
- Pytest pass nhưng coverage thấp vẫn kích hoạt coverage reflection nếu còn lượt.
- Reflection có mục tiêu từ tên test fail/error; AST patcher hỗ trợ function và method trong class.

## Behavioral probing và RAG

- Phân tích source để route giữa `behavioral_probe` và `codegen_with_mocks_or_objects`.
- JSON plan có repair/structured output, kiểm tra arity runtime và canonical deduplication.
- Heuristic bổ sung case chỉ ở mức primitive nông; không suy diễn deep shape thiếu chắc chắn.
- Fast-retry cho thư mục tương đối bị thiếu dựa trên `FileNotFoundError` thực tế.
- Chuẩn hóa `valid_dataset.json`, giữ ground truth gốc và tạo `rag_tests` riêng.
- Chỉ mẫu coverage 100%, có assertion, parse và normalize thành công mới được embed.
- ChromaDB được build vào collection tạm rồi mới thay collection live khi hoàn tất.

## Sandbox và an toàn

- Dùng UID/GID `utcoder-sandbox`, tránh lỗi `RLIMIT_NPROC` do dùng chung tài khoản `nobody` trên Ubuntu.
- Giới hạn timeout, RAM và số process cho compile, pytest, coverage và mutation.
- Mỗi stage chạy trong workspace mới; xóa coverage cũ trước mỗi lượt để chống ghost coverage.
- Phân biệt lỗi hạ tầng với lỗi model; benchmark dừng khi sandbox/evaluator hỏng.
- Có deterministic preflight cho sandbox và mutation evaluator.

## Benchmark chính thức

- 50 task unseen cho mỗi model `qwen2.5-coder:7b` và `llama3.1:8b`.
- Đánh giá compile, collection, ba lượt stability, line coverage, branch coverage và mutation score.
- Điểm mặc định: 55% mutation, 30% branch, 15% line; suite flaky 2/3 chịu hệ số 0,8.
- Hard-gate fail có điểm 0; mutation chưa hoàn tất để điểm rỗng thay vì suy đoán.
- Ghi schema/evaluator version, hash, CSV, JSONL và artifact theo model/task.
- Resume theo model + task + source hash + evaluator version; hỗ trợ rerun hàng fail/incomplete.
- Có paired comparison, bootstrap CI 95%, bảng trạng thái và biểu đồ chất lượng.
- Sau mỗi model, gửi `keep_alive=0` và xác nhận Ollama đã giải phóng model khỏi RAM/VRAM.

## Cấu hình và triển khai

- Hợp nhất về một `config.json`; xóa `config.local.json` và `config.server.json`.
- Ghi đè khác biệt môi trường bằng biến `UTCODER_*`.
- `docker-compose.yml` phục vụ all-in-one; `docker-compose.server.yml` phục vụ hybrid với Ollama local qua reverse SSH.
- Thu gọn Docker image production về Python-only; bỏ Java/Maven, Node.js và .NET prototype.
- `prepare_server.py` đóng gói runtime/ChromaDB/dataset đã kiểm chứng, loại Markdown, tests, log, raw dataset và artifact khỏi ZIP server.
- Thêm `.env.example`, `.dockerignore` và chuẩn hóa `.gitignore`.

## REST API, Gradio và VS Code extension

- Tách `server.py` thành process API Python riêng trên cổng 8000; Gradio chạy độc lập trên cổng 7860.
- `POST /api/generate` dùng đúng RAG, sandbox và self-reflection; không trả code chưa đạt gate.
- Health check xác minh Ollama/model thật, ChromaDB và dependency sandbox; `GET /api/health?deep=1` chạy preflight.
- API có giới hạn request, bearer token tùy chọn, threaded health và khóa một lượt generation để kiểm soát tài nguyên.
- Thêm service `utcoder-api` vào Compose all-in-one và hybrid; hybrid bind loopback để dùng qua SSH local-forward.
- Extension chỉ nhận `.py`, dùng timeout/cancel thật, gửi bearer token và chỉ ghi response đã accepted.
- Sửa callback Gradio sai số lượng output, chỉ nhận `.py` và bắt buộc mọi file tải xuống qua reflection + coverage gate.
- TypeScript extension đã compile và VSIX đã được đóng gói kiểm chứng.

## Tài liệu

- Giữ và cập nhật đầy đủ System Architecture cùng Pipeline Deep-Dive trong `README.md`.
- `DEPLOYMENT.md` mô tả kiến trúc local-AI/server-runtime, API và SSH tunnel.
- `core/benchmark/BENCHMARK.md` giải thích hard gate, mutation policy, công thức điểm và cách diễn giải.
