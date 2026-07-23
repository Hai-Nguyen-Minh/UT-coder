# Decorator retry

Viết decorator factory `retry(max_attempts, exceptions=(Exception,))`.

Hành vi:
- Gọi hàm tối đa `max_attempts` lần.
- Chỉ retry khi exception thuộc `exceptions`.
- Nếu vẫn lỗi ở lần cuối, raise lại chính exception cuối.
- Exception không thuộc `exceptions` phải được raise ngay.
- Bảo toàn metadata của hàm bằng `functools.wraps`.
- `max_attempts` phải là số nguyên dương, nếu không raise `ValueError`.
