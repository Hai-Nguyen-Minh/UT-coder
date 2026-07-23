# Sắp xếp phụ thuộc

Viết hàm `dependency_order(graph)` với `graph` là dictionary:
`node -> iterable các dependency trực tiếp`.

Trả về list thứ tự sao cho mọi dependency đứng trước node.

Yêu cầu:
- Bao gồm cả node chỉ xuất hiện trong danh sách dependency.
- Khi có nhiều lựa chọn hợp lệ, chọn node nhỏ nhất theo thứ tự từ điển của `str(node)`.
- Nếu có chu trình, raise `ValueError`.
- Không thay đổi đầu vào.
