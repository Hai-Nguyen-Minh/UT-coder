# K phần tử xuất hiện nhiều nhất

Viết hàm `top_k_frequent(items, k)` trả về tối đa `k` phần tử xuất hiện nhiều nhất.

Thứ tự:
1. Tần suất giảm dần.
2. Nếu bằng tần suất, phần tử xuất hiện trước trong đầu vào đứng trước.

`k <= 0` trả về `[]`. Các phần tử đầu vào là hashable.
