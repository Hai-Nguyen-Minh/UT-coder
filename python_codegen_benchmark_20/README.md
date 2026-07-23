# Python Code Generation Benchmark — 20 bài

Bộ dữ liệu này dùng để kiểm tra AI sinh code Python và sinh test.

## Cấu trúc

- `manifest.jsonl`: metadata và prompt của 20 bài.
- Mỗi thư mục `task_xx_*` gồm:
  - `prompt.md`: đề bài.
  - `starter.py`: skeleton để đưa cho model sinh code.
  - `solution.py`: lời giải tham chiếu.
  - `test_solution.py`: test pytest.
- `all_prompts.md`: toàn bộ đề bài trong một file.

## Chạy toàn bộ test tham chiếu

```bash
python -m pip install pytest
python run_all_tests.py
```

## Cách dùng để đánh giá model

1. Đưa nội dung `prompt.md` và `starter.py` cho model.
2. Ghi code model sinh ra vào `solution.py` trong một bản sao của task.
3. Chạy `pytest -q task_xx_name/test_solution.py`.
4. Có thể yêu cầu model tự sinh test rồi so sánh độ bao phủ với test chuẩn.

Lưu ý: `solution.py` là đáp án tham chiếu, nên ẩn file này khỏi model khi benchmark.
