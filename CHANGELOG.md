# UT-Coder: Updates & Enhancements

Tài liệu này tổng hợp toàn bộ các tính năng, cải tiến kiến trúc và các file mới đã được thêm vào dự án so với phiên bản gốc trên Git. Trọng tâm của đợt nâng cấp này là **Hệ thống Self-Reflection Sandbox** (Tự động tự kiểm tra và sửa lỗi code) và tối ưu hóa **Môi trường Triển khai Server**.

---

## 1. Hệ thống Self-Reflection Sandbox (AI Tự Sửa Lỗi)
Phiên bản cũ chỉ đơn thuần gọi LLM sinh code rồi hiển thị cho người dùng. Phiên bản mới đã tích hợp một "Hộp cát" (Sandbox) cách ly. Code do AI sinh ra sẽ được tự động chạy thử (execute), đo lường mức độ bao phủ (coverage) và thậm chí là đo lường bằng kiểm thử đột biến (mutation testing). Nếu có lỗi hoặc coverage không đạt mốc tối thiểu (80%), AI sẽ nhận được log lỗi để tự viết lại code cho đến khi Pass (tối đa 3 lần thử).

### Các File Thêm Mới:
- **`core/sandbox/__init__.py`**: Khởi tạo module sandbox.
- **`core/sandbox/base.py`**: Định nghĩa kiến trúc lõi (`SandboxResult` và `class Sandbox`). Chứa các interface trừu tượng giúp chuẩn hóa đầu ra của Sandbox (kết quả pass/fail, error log, điểm coverage, missing lines) và dọn đường để mở rộng hỗ trợ đa ngôn ngữ trong tương lai (Java, C++, JS...).
- **`core/sandbox/python_sandbox.py`**: Thực thi Sandbox dành riêng cho Python. File này tự động tạo môi trường tạm thời (temp file), chạy lệnh `pytest`, sử dụng `pytest-cov` để đo lường Coverage, và sử dụng `mutmut` để chạy Mutation Testing. Nó cũng tự động tiêm (inject) file `setup.cfg` để công cụ `mutmut` không bị lỗi khởi tạo.
- **`core/coverager.py`**: Chịu trách nhiệm phân tích dữ liệu mảng các "dòng code bị sót" (missing_lines) trả về từ Sandbox, từ đó sinh ra một đoạn mã HTML có tô màu đỏ/xanh (Highlight) giúp người dùng trực quan nhìn thấy đoạn code nào chưa được AI viết test.

### Các File Cũ Được Nâng Cấp:
- **`core/generator.py`**: Viết lại luồng `generate_unit_tests` thành `generate_with_reflection`. Bổ sung vòng lặp retry (tối đa 3 lần). Nếu code có lỗi hoặc Coverage < 80%, LLM sẽ được mớm thêm Error Log để sửa bài.

---

## 2. Giao diện Người dùng (Gradio UI)
Giao diện được làm mới theo hướng tinh gọn và tự động hóa cao hơn. Cung cấp ngay kết quả trực quan thay vì bắt người dùng phải đọc log thô.

### Thay đổi trên `ui/app.py`:
- **Xóa bỏ tab "Compile Check":** Vì mọi quá trình biên dịch, kiểm thử đều đã được tự động chạy ngầm trong Self-Reflection Sandbox.
- **Bổ sung Checkbox "Use Self-Reflection Sandbox":** Cho phép người dùng linh hoạt bật/tắt tính năng tự kiểm tra của AI. Nếu tắt, AI sẽ sinh code 1 lần như cũ để tiết kiệm thời gian.
- **Thêm Tab "📊 Visual Coverage":** Hiển thị trực tiếp file code gốc được tô màu (Highlight). Những dòng nào đã được Unit Test bao phủ sẽ có viền xanh, những dòng chưa được test sẽ bị bôi đỏ.
- **Hardcode Mốc Target Coverage = 80%:** Tham số này được ẩn đi và cố định trong hệ thống, buộc LLM phải luôn cố gắng sinh ra bài test cover từ 80% trở lên.

---

## 3. Server Deployment (Triển khai hệ thống)
Đã tái cấu trúc cách đóng gói dự án để dễ dàng đưa lên Ubuntu Server, tách bạch giữa việc chạy LLM cục bộ (Ollama) và việc chạy App Server (chỉ call API).

### Các File Thêm Mới:
- **`DEPLOYMENT.md`**: File hướng dẫn chi tiết từng bước (Step-by-step) cách cấu hình môi trường, cài đặt Docker, mở port trên Ubuntu và cách phân tách 2 cỗ máy (1 máy chuyên chạy LLM và 1 máy chuyên chạy Web Server).
- **`config.server.json` & `docker-compose.server.yml`**: Các file cấu hình mẫu chuyên dụng cho môi trường Server (khác với môi trường Local).
- **`prepare_server.py`**: Một script Python tiện ích (Utility). Khi chạy, nó sẽ tự động thu gom các file cốt lõi (core, ui, main, requirements...), bỏ qua các file thừa thãi (chroma_db, pycache), sau đó đóng gói tất cả vào một file **`utcoder_server.zip`**. Script này cũng tự động đổi tên `docker-compose.server.yml` thành `docker-compose.yml` ngay bên trong file Zip, giúp người dùng chỉ việc tải file Zip lên server và chạy.
- **`patch_ui.py` (Script chạy một lần):** File script được sử dụng trong quá trình vá lỗi (Patch) giao diện của hệ thống để thay thế an toàn các khối mã phức tạp (hiện tại có thể được xóa bỏ).

---
