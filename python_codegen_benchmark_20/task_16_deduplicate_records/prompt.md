# Loại trùng record theo khóa

Viết hàm `deduplicate_records(records, key)` nhận iterable các dictionary.

Yêu cầu:
- Chỉ giữ record đầu tiên cho mỗi giá trị `record[key]`.
- Giữ nguyên thứ tự.
- Trả về các bản sao dictionary mới (shallow copy), không trả lại chính object đầu vào.
- Nếu record thiếu key, raise `KeyError`.
