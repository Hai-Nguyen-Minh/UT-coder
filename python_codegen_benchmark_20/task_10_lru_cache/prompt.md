# Cài đặt LRU Cache

Cài đặt class `LRUCache`:

- `LRUCache(capacity)` với `capacity` là số nguyên dương, nếu không raise `ValueError`.
- `get(key)` trả về value; nếu không tồn tại trả về `None`. Truy cập thành công làm key trở thành mới dùng nhất.
- `put(key, value)` thêm/cập nhật key. Khi vượt capacity, xóa key ít dùng gần đây nhất.
- `len(cache)` trả về số phần tử hiện tại.

Mục tiêu: `get` và `put` có độ phức tạp trung bình O(1).
