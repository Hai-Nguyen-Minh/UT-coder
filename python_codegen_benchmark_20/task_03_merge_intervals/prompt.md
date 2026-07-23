# Gộp các khoảng giao nhau

Viết hàm `merge_intervals(intervals)` nhận danh sách các cặp `(start, end)`.

Yêu cầu:
- Mỗi khoảng hợp lệ khi `start <= end`; nếu không, raise `ValueError`.
- Gộp cả các khoảng giao nhau hoặc chạm nhau, ví dụ `(1, 3)` và `(3, 5)` thành `(1, 5)`.
- Kết quả sắp tăng theo `start`.
- Không thay đổi đầu vào.
