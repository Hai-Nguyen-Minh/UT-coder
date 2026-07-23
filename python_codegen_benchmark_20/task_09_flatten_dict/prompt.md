# Làm phẳng dictionary lồng nhau

Viết hàm `flatten_dict(data, sep=".")` làm phẳng dictionary lồng nhau.

Ví dụ:
`{"a": {"b": 1}, "c": 2}` -> `{"a.b": 1, "c": 2}`.

Quy tắc:
- Chỉ dictionary được mở rộng; list và kiểu khác được xem là giá trị.
- Dictionary rỗng tại một khóa được giữ dưới dạng `{}`.
- Khóa được chuyển sang chuỗi bằng `str`.
- Dictionary gốc rỗng trả về `{}`.
