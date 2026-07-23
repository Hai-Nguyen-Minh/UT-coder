# Chia dữ liệu có xử lý lỗi

Viết hàm `safe_divide_records(records)` nhận iterable các cặp `(numerator, denominator)`.

Trả về list:
- Nếu chia được: kết quả phép chia.
- Nếu denominator bằng 0: chuỗi `"division_by_zero"`.
- Nếu giá trị không hỗ trợ phép chia: chuỗi `"invalid_operand"`.

Không được dừng toàn bộ xử lý chỉ vì một record lỗi.
