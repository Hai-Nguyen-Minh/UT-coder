# Lấy dữ liệu theo đường dẫn

Viết hàm `deep_get(data, path, default=None)`.

`path` là chuỗi dùng dấu chấm, ví dụ `"users.0.name"`.
- Với dictionary: segment dùng làm key chuỗi.
- Với list/tuple: segment phải là chỉ số nguyên không âm.
- Nếu bất kỳ bước nào không tồn tại hoặc không hợp lệ, trả về `default`.
- Path rỗng `""` trả về chính `data`.
