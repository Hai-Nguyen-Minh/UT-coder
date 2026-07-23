# Chia iterable thành từng nhóm

Viết generator `chunked(iterable, size)` chia iterable thành các list có tối đa `size` phần tử.

Yêu cầu:
- Hoạt động với mọi iterable, kể cả generator.
- Không chuyển toàn bộ iterable thành list trước.
- Nhóm cuối có thể ngắn hơn.
- `size` phải là số nguyên dương; nếu không raise `ValueError` khi bắt đầu duyệt generator.
