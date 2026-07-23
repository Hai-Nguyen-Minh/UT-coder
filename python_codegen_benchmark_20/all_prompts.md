# 20 bài Python dùng để benchmark AI sinh code

## 1. Tìm hai chỉ số có tổng bằng target (easy)

Viết hàm `two_sum_indices(nums, target)` nhận một danh sách số nguyên `nums` và số nguyên `target`.
Hàm trả về tuple `(i, j)` với `i < j` sao cho `nums[i] + nums[j] == target`.

Yêu cầu:
- Nếu có nhiều đáp án, trả về cặp có `j` nhỏ nhất; nếu vẫn trùng, chọn `i` nhỏ nhất.
- Nếu không có đáp án, trả về `None`.
- Không được thay đổi danh sách đầu vào.


## 2. Chuẩn hóa khoảng trắng (easy)

Viết hàm `normalize_whitespace(text)`:
- Xóa khoảng trắng ở đầu và cuối.
- Mọi chuỗi ký tự whitespace liên tiếp (space, tab, newline...) được thay bằng đúng một dấu cách.
- Trả về chuỗi rỗng nếu đầu vào chỉ chứa whitespace.


## 3. Gộp các khoảng giao nhau (medium)

Viết hàm `merge_intervals(intervals)` nhận danh sách các cặp `(start, end)`.

Yêu cầu:
- Mỗi khoảng hợp lệ khi `start <= end`; nếu không, raise `ValueError`.
- Gộp cả các khoảng giao nhau hoặc chạm nhau, ví dụ `(1, 3)` và `(3, 5)` thành `(1, 5)`.
- Kết quả sắp tăng theo `start`.
- Không thay đổi đầu vào.


## 4. Nhóm các từ đảo chữ (easy)

Viết hàm `group_anagrams(words)` nhóm các chuỗi là anagram của nhau.

Quy tắc:
- Phân biệt chữ hoa/chữ thường.
- Giữ nguyên thứ tự xuất hiện của các nhóm theo phần tử đầu tiên.
- Trong mỗi nhóm, giữ nguyên thứ tự đầu vào.
- Trả về list các list.


## 5. Mã hóa run-length (easy)

Viết hàm `run_length_encode(text)` trả về danh sách tuple `(character, count)` cho các ký tự liên tiếp.

Ví dụ: `"aaabbcaaa"` -> `[("a", 3), ("b", 2), ("c", 1), ("a", 3)]`.
Chuỗi rỗng trả về `[]`.


## 6. Kiểm tra ngoặc cân bằng (easy)

Viết hàm `is_balanced(text)` kiểm tra các dấu ngoặc `()`, `[]`, `{}` trong chuỗi có cân bằng và lồng đúng thứ tự hay không.
Mọi ký tự khác được bỏ qua.


## 7. Xoay ma trận 90 độ (medium)

Viết hàm `rotate_clockwise(matrix)` xoay ma trận hình chữ nhật 90 độ theo chiều kim đồng hồ.

Yêu cầu:
- Ma trận rỗng `[]` trả về `[]`.
- Tất cả các hàng phải có cùng độ dài, nếu không raise `ValueError`.
- Không thay đổi ma trận đầu vào.


## 8. K phần tử xuất hiện nhiều nhất (medium)

Viết hàm `top_k_frequent(items, k)` trả về tối đa `k` phần tử xuất hiện nhiều nhất.

Thứ tự:
1. Tần suất giảm dần.
2. Nếu bằng tần suất, phần tử xuất hiện trước trong đầu vào đứng trước.

`k <= 0` trả về `[]`. Các phần tử đầu vào là hashable.


## 9. Làm phẳng dictionary lồng nhau (medium)

Viết hàm `flatten_dict(data, sep=".")` làm phẳng dictionary lồng nhau.

Ví dụ:
`{"a": {"b": 1}, "c": 2}` -> `{"a.b": 1, "c": 2}`.

Quy tắc:
- Chỉ dictionary được mở rộng; list và kiểu khác được xem là giá trị.
- Dictionary rỗng tại một khóa được giữ dưới dạng `{}`.
- Khóa được chuyển sang chuỗi bằng `str`.
- Dictionary gốc rỗng trả về `{}`.


## 10. Cài đặt LRU Cache (hard)

Cài đặt class `LRUCache`:

- `LRUCache(capacity)` với `capacity` là số nguyên dương, nếu không raise `ValueError`.
- `get(key)` trả về value; nếu không tồn tại trả về `None`. Truy cập thành công làm key trở thành mới dùng nhất.
- `put(key, value)` thêm/cập nhật key. Khi vượt capacity, xóa key ít dùng gần đây nhất.
- `len(cache)` trả về số phần tử hiện tại.

Mục tiêu: `get` và `put` có độ phức tạp trung bình O(1).


## 11. Chia dữ liệu có xử lý lỗi (easy)

Viết hàm `safe_divide_records(records)` nhận iterable các cặp `(numerator, denominator)`.

Trả về list:
- Nếu chia được: kết quả phép chia.
- Nếu denominator bằng 0: chuỗi `"division_by_zero"`.
- Nếu giá trị không hỗ trợ phép chia: chuỗi `"invalid_operand"`.

Không được dừng toàn bộ xử lý chỉ vì một record lỗi.


## 12. Phân tích dòng log (medium)

Viết hàm `parse_log_lines(lines)` phân tích các dòng theo định dạng:

`YYYY-MM-DD HH:MM:SS | LEVEL | message`

Kết quả là list dictionary:
`{"timestamp": datetime, "level": str, "message": str}`.

Yêu cầu:
- Bỏ qua dòng rỗng.
- `LEVEL` được chuẩn hóa thành chữ hoa.
- Nếu một dòng không đúng định dạng hoặc timestamp không hợp lệ, raise `ValueError` kèm số dòng bắt đầu từ 1.
- Khoảng trắng quanh ba trường được loại bỏ.


## 13. Decorator retry (hard)

Viết decorator factory `retry(max_attempts, exceptions=(Exception,))`.

Hành vi:
- Gọi hàm tối đa `max_attempts` lần.
- Chỉ retry khi exception thuộc `exceptions`.
- Nếu vẫn lỗi ở lần cuối, raise lại chính exception cuối.
- Exception không thuộc `exceptions` phải được raise ngay.
- Bảo toàn metadata của hàm bằng `functools.wraps`.
- `max_attempts` phải là số nguyên dương, nếu không raise `ValueError`.


## 14. Chia iterable thành từng nhóm (medium)

Viết generator `chunked(iterable, size)` chia iterable thành các list có tối đa `size` phần tử.

Yêu cầu:
- Hoạt động với mọi iterable, kể cả generator.
- Không chuyển toàn bộ iterable thành list trước.
- Nhóm cuối có thể ngắn hơn.
- `size` phải là số nguyên dương; nếu không raise `ValueError` khi bắt đầu duyệt generator.


## 15. Lấy dữ liệu theo đường dẫn (medium)

Viết hàm `deep_get(data, path, default=None)`.

`path` là chuỗi dùng dấu chấm, ví dụ `"users.0.name"`.
- Với dictionary: segment dùng làm key chuỗi.
- Với list/tuple: segment phải là chỉ số nguyên không âm.
- Nếu bất kỳ bước nào không tồn tại hoặc không hợp lệ, trả về `default`.
- Path rỗng `""` trả về chính `data`.


## 16. Loại trùng record theo khóa (medium)

Viết hàm `deduplicate_records(records, key)` nhận iterable các dictionary.

Yêu cầu:
- Chỉ giữ record đầu tiên cho mỗi giá trị `record[key]`.
- Giữ nguyên thứ tự.
- Trả về các bản sao dictionary mới (shallow copy), không trả lại chính object đầu vào.
- Nếu record thiếu key, raise `KeyError`.


## 17. Maximum của cửa sổ trượt (hard)

Viết hàm `sliding_window_max(nums, k)` trả về maximum của từng cửa sổ liên tiếp độ dài `k`.

Yêu cầu:
- Độ phức tạp O(n).
- Nếu `k` không phải số nguyên dương hoặc `k > len(nums)`, raise `ValueError`.
- Không thay đổi đầu vào.


## 18. Tổng hợp CSV (medium)

Viết hàm `summarize_csv(text)` đọc CSV từ chuỗi.

CSV có header bắt buộc: `category,amount`.
Trả về dictionary tổng `amount` theo `category`.

Yêu cầu:
- `amount` được parse bằng `Decimal`.
- Bỏ qua dòng trống.
- Loại khoảng trắng quanh category và amount.
- Category rỗng hoặc amount không hợp lệ -> raise `ValueError`.
- Thiếu header yêu cầu -> raise `ValueError`.


## 19. Sắp xếp phụ thuộc (hard)

Viết hàm `dependency_order(graph)` với `graph` là dictionary:
`node -> iterable các dependency trực tiếp`.

Trả về list thứ tự sao cho mọi dependency đứng trước node.

Yêu cầu:
- Bao gồm cả node chỉ xuất hiện trong danh sách dependency.
- Khi có nhiều lựa chọn hợp lệ, chọn node nhỏ nhất theo thứ tự từ điển của `str(node)`.
- Nếu có chu trình, raise `ValueError`.
- Không thay đổi đầu vào.


## 20. Fibonacci có cache thống kê (medium)

Cài đặt class `MemoizedFibonacci`.

API:
- `fib(n)` trả về số Fibonacci với `fib(0)=0`, `fib(1)=1`.
- `n` phải là số nguyên không âm; nếu không raise `ValueError`.
- Kết quả đã tính phải được cache giữa các lần gọi.
- Thuộc tính chỉ đọc `computed_count` cho biết có bao nhiêu giá trị mới với `n >= 2` đã thực sự được tính kể từ khi tạo object.
- Gọi lại một `n` đã cache không làm tăng `computed_count`.

