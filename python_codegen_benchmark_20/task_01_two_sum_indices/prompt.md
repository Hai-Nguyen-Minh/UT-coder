# Tìm hai chỉ số có tổng bằng target

Viết hàm `two_sum_indices(nums, target)` nhận một danh sách số nguyên `nums` và số nguyên `target`.
Hàm trả về tuple `(i, j)` với `i < j` sao cho `nums[i] + nums[j] == target`.

Yêu cầu:
- Nếu có nhiều đáp án, trả về cặp có `j` nhỏ nhất; nếu vẫn trùng, chọn `i` nhỏ nhất.
- Nếu không có đáp án, trả về `None`.
- Không được thay đổi danh sách đầu vào.
