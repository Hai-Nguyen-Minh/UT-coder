# Tổng hợp CSV

Viết hàm `summarize_csv(text)` đọc CSV từ chuỗi.

CSV có header bắt buộc: `category,amount`.
Trả về dictionary tổng `amount` theo `category`.

Yêu cầu:
- `amount` được parse bằng `Decimal`.
- Bỏ qua dòng trống.
- Loại khoảng trắng quanh category và amount.
- Category rỗng hoặc amount không hợp lệ -> raise `ValueError`.
- Thiếu header yêu cầu -> raise `ValueError`.
