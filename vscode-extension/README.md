# UTcoder — Python Unit Test Generator for VS Code

Extension này gửi file Python tới REST API của UTcoder và chỉ tạo file test khi server đã xác nhận:

- source và test compile được;
- pytest pass;
- báo cáo coverage hợp lệ;
- line coverage đạt cổng generation hiện tại (mặc định 80%).

Java, C#, JavaScript và TypeScript chưa được hỗ trợ chính thức.

## Luồng hoạt động

```text
Right-click file .py
    → GET /api/health
    → POST /api/generate
    → RAG + Ollama + sandbox + self-reflection trên server
    → nhận test đã accepted
    → tạo test_<tên_file>.py
```

Extension không tự chạy pytest trên máy VS Code. Việc kiểm chứng diễn ra trong sandbox của server.

## Chạy API trên server

Với Docker Compose:

```bash
docker compose up -d utcoder utcoder-api
docker compose exec utcoder python -m core.sandbox.preflight
```

API hybrid mặc định chỉ listen tại `127.0.0.1:8000` trên server. Từ máy đang chạy VS Code, mở SSH local-forward:

```bash
ssh -N -L 8000:127.0.0.1:8000 <user>@<server-ip>
```

Sau đó giữ setting `utcoder.serverUrl` là `http://localhost:8000`. Cách này mã hóa source qua SSH và không cần public cổng API.

Nếu chạy trực tiếp để phát triển:

```bash
python server.py
```

## Cài extension

```bash
cd vscode-extension
npm ci
npm run compile
npx @vscode/vsce package --out utcoder-vscode.vsix
code --install-extension utcoder-vscode.vsix
```

## Sử dụng

- Chuột phải file `.py` → **UTcoder: Generate Unit Tests**.
- Command Palette → `UTcoder: Generate Unit Tests`.
- Phím tắt `Ctrl+Alt+G` (`Cmd+Alt+G` trên macOS).
- `UTcoder: Check Server Health` để kiểm tra Ollama, ChromaDB và dependency sandbox.

Extension từ chối ghi file nếu candidate không qua pytest và cổng coverage. Khi thành công, thông báo hiển thị coverage server đã đo.

## Cấu hình

| Setting | Mặc định | Ý nghĩa |
|---|---|---|
| `utcoder.serverUrl` | `http://localhost:8000` | REST API URL |
| `utcoder.serverTimeout` | `120000` | Timeout request tính bằng mili-giây |
Bearer token không được lưu trong `settings.json`. Chạy command **UTcoder: Set API Token** để lưu token khớp `UTCODER_API_TOKEN` bằng VS Code SecretStorage; nhập rỗng để xóa.

Nếu API được đưa ra ngoài loopback/LAN tin cậy, phải dùng HTTPS và token. SSH local-forward là cấu hình được khuyến nghị.

## API contract

### `GET /api/health`

Trả trạng thái thực của Ollama, configured model, ChromaDB path và Python sandbox dependencies.

### `POST /api/generate`

Request:

```json
{
  "file_name": "calculator.py",
  "source_code": "def add(a, b): return a + b",
  "language": "python"
}
```

Response thành công:

```json
{
  "success": true,
  "accepted": true,
  "code": "import pytest\nfrom calculator import add\n...",
  "test_file_name": "test_calculator.py",
  "coverage": 100.0,
  "execution_status": "tests_passed"
}
```

## Giới hạn

- Mỗi API process chỉ nhận một generation request tại một thời điểm để phù hợp Ollama local.
- File quá giới hạn `UTCODER_API_MAX_REQUEST_BYTES` bị từ chối.
- API không phải OpenAI-compatible API và không có `/v1/chat/completions`.
- Test được tạo theo module basename; project có layout import đặc biệt có thể cần chỉnh import sau khi tạo.

## License

[MIT](LICENSE)
