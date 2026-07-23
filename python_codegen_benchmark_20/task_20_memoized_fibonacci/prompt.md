# Fibonacci có cache thống kê

Cài đặt class `MemoizedFibonacci`.

API:
- `fib(n)` trả về số Fibonacci với `fib(0)=0`, `fib(1)=1`.
- `n` phải là số nguyên không âm; nếu không raise `ValueError`.
- Kết quả đã tính phải được cache giữa các lần gọi.
- Thuộc tính chỉ đọc `computed_count` cho biết có bao nhiêu giá trị mới với `n >= 2` đã thực sự được tính kể từ khi tạo object.
- Gọi lại một `n` đã cache không làm tăng `computed_count`.
