# Phân tích dòng log

Viết hàm `parse_log_lines(lines)` phân tích các dòng theo định dạng:

`YYYY-MM-DD HH:MM:SS | LEVEL | message`

Kết quả là list dictionary:
`{"timestamp": datetime, "level": str, "message": str}`.

Yêu cầu:
- Bỏ qua dòng rỗng.
- `LEVEL` được chuẩn hóa thành chữ hoa.
- Nếu một dòng không đúng định dạng hoặc timestamp không hợp lệ, raise `ValueError` kèm số dòng bắt đầu từ 1.
- Khoảng trắng quanh ba trường được loại bỏ.
