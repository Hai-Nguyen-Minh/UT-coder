# 📊 Tiêu chuẩn Đánh giá Chất lượng (Benchmark Guide)

Chạy thử (Pytest pass) và có dòng code được phủ (Line Coverage) là **chưa đủ** để chứng minh AI viết test tốt. Một bài test có thể phủ 80% dòng code nhưng không hề có câu lệnh `assert` nào ra hồn. Ngược lại, một bài test phủ toàn bộ code vẫn có thể bỏ lọt hàng loạt lỗi logic (mutants).

Đó là lý do UT-coder xây dựng một bộ Benchmark cực kỳ khắt khe. Tài liệu này sẽ giải thích cách chúng tôi thực sự chấm điểm AI.

---

## 🎯 1. Triết lý Đánh giá: "Vượt rào" & "Chấm điểm"

Bộ đánh giá giải quyết 2 bài toán:
1. **Generator có làm ra test chạy được không?** (Vượt rào)
2. **Test sinh ra có thực sự bắt được lỗi không?** (Chấm điểm)

Benchmark chính đo lường năng lực trên **50 task Python standalone chưa trùng source/AST với `valid_dataset.json`**. Đây là kiểm tra unseen theo corpus RAG cục bộ, không phải tuyên bố rằng các ý tưởng thuật toán chưa từng xuất hiện trong dữ liệu huấn luyện của model. Bộ task chủ yếu là snippet dễ–trung bình (trung bình khoảng 13 dòng), dùng để so sánh hai model trên cùng một đầu vào; project-context RAG được đánh giá bằng workbench 20 task riêng ở phần dưới.

- **Chủ đề bài toán (Nội dung):** Bao gồm 50 bài tập đa dạng, bám sát các dạng logic thực tế:
  - *Xử lý mảng (Array/List)*: Các bài toán như `max_subarray_sum`, `search_rotated_array`, `sliding_window_max`...
  - *Thuật toán & Đồ thị (Algorithms)*: `topological_sort`, `levenshtein_distance`, `postfix_eval`...
  - *Xử lý chuỗi (String)*: `is_valid_ip`, `parse_semver`, `slugify`, `run_length_encode`...
  - *Ma trận & Hình học (Matrix)*: `matrix_transpose`, `is_valid_sudoku`, `rotate_matrix_clockwise`...
  - *Từ điển & Xử lý dữ liệu (Dict/JSON)*: `flatten_dict`, `group_anagrams`, `deduplicate_records`...
  - *Lập trình hướng đối tượng (OOP & Cache)*: Các class như `BankAccount`, `LRUCache`, `SlidingWindowLimiter`...
  - *Ngoại lệ & Mocking (I/O, DB, Decorators)*: Các hàm phức tạp yêu cầu bắt lỗi hoặc giả lập như `fetch_active_user`, `load_threshold`, `retry` decorator.
- **Độ khó:** Chủ yếu dễ–trung bình ở quy mô unit nhỏ; một số task khó tương đối có stateful class, generator, file I/O hoặc injected protocol. Bộ này không đại diện cho toàn bộ độ phức tạp của một project enterprise đa file.
- **Chất lượng:** Toàn bộ 50 bài code nguồn (source code) được tuyển chọn gắt gao. 100% đều chuẩn cú pháp (không chứa lỗi compile rác gây nhiễu), và đặc biệt là *chắc chắn có thể tiêm lỗi (mutate)* để đo lường độ nhạy bén của test do AI sinh ra.

Quá trình đánh giá được chạy trên hai mô hình:
- `qwen2.5-coder:7b`
- `llama3.1:8b`

Ở mỗi task, mô hình có **1 cơ hội viết test** ban đầu và tối đa **3 cơ hội tự đọc log lỗi để sửa (Reflection)** nếu test bị hỏng.

### Workbench RAG ablation 20 project-task

Sau benchmark model, hệ thống chạy thêm 20 project Python nhỏ, mỗi project có một target file và các support module chứa custom objects, protocol, injected dependency, file/config contract hoặc giao diện Python nâng cao. Cùng `qwen2.5-coder:7b` được chạy ghép cặp ở hai điều kiện:

- `RAG_OFF`: không index/search ChromaDB và không lấy few-shot;
- `RAG_ON`: truy xuất project context (`k=4`) và few-shot candidates từ collection đã embed.

Hai điều kiện dùng cùng source/project hash, temperature, reflection budget, evaluator và sandbox. Project task luôn đi qua full-code generation để Behavioral Probing không bypass RAG. Golden tests chỉ dùng để validate dataset, không được đưa vào prompt.

---

## 🚧 2. Các vòng thi (Evaluation Pipeline)

Khi mô hình nộp bài test cuối cùng, bài test này sẽ phải vượt qua "địa ngục" 5 bước:

1. **Vòng Compile & Collect**: Test có bị lỗi cú pháp không? Pytest có nhận diện được hàm test nào không? 
2. **Vòng Pytest cơ bản**: Test có chạy thành công (Pass) thật sự không? Nếu có bất kỳ lỗi `FAILED` hoặc `ERROR` nào -> Loại.
3. **Vòng Ổn định (Stability check)**: Chạy bài test đó 3 lần độc lập. 
   - Pass 3/3: Test hoàn hảo (`VALID_STABLE`).
   - Pass 2/3: Test hơi chập chờn (`VALID_FLAKY`) -> Bị trừ 20% tổng điểm.
   - Pass 0/3 hoặc 1/3: Test quá rác (`UNSTABLE`) -> Loại, 0 điểm.
4. **Vòng Đo lường Coverage**: Đo chính xác bao nhiêu phần trăm Dòng (Line) và Nhánh (Branch) của code nguồn đã được chạy qua.
5. **Vòng Sinh tồn (Mutation Testing)**: Dùng công cụ `mutmut` để cố tình "tiêm" lỗi vào code nguồn. Test tốt là test **phải fail** khi code nguồn bị lỗi (tức là tiêu diệt được mutant).

---

## 🏆 3. Công thức Tính Điểm (Scoring)

Nếu một bài test sống sót qua 5 vòng trên, nó sẽ được chấm theo thang điểm 100:

- **55% Điểm**: Dành cho Tỉ lệ tiêu diệt Mutant (Mutation Score). Đây là minh chứng rõ nhất cho việc test có ý nghĩa.
- **30% Điểm**: Dành cho Độ phủ Nhánh (Branch Coverage). Bắt AI phải test các luồng `if/else`, không chỉ đi đường thẳng.
- **15% Điểm**: Dành cho Độ phủ Dòng (Line Coverage).

> *Lưu ý: Nếu test thuộc diện `VALID_FLAKY` (chập chờn 2/3), tổng điểm cuối cùng sẽ bị nhân với hệ số **0.8**.*

**Phân loại Band điểm:**
- `EXCELLENT`: >= 85 điểm
- `GOOD`: 70 - 84 điểm
- `FAIR`: 50 - 69 điểm
- `WEAK`: < 50 điểm

---

## 🚦 4. Bảng Trạng Thái Dễ Hiểu

Báo cáo kết quả sẽ không chỉ có `Pass` hay `Fail`, mà sẽ cực kỳ chi tiết:

| Trạng thái | Ý nghĩa thực tế |
|---|---|
| `VALID_STABLE` | Tuyệt vời! Test chạy ổn định cả 3/3 lần. Được tính full điểm. |
| `VALID_FLAKY` | Test chạy được nhưng chập chờn (2/3 lần). Vẫn có điểm nhưng bị phạt. |
| `NO_GENERATED_TEST` | AI "bó tay", không viết được test nào dùng được. |
| `SOURCE_COMPILE_FAILED` | File source bị lỗi cú pháp gốc, không phải do AI. |
| `TEST_COMPILE_FAILED` | AI viết ra đoạn code không thể biên dịch. |
| `COLLECTION_FAILED` | Lỗi framework, pytest không nhận diện được test. |
| `NO_TESTS` / `ALL_SKIPPED`| AI viết test nhưng không có assert nào chạy, hoặc bị skip toàn bộ. |
| `UNSTABLE` | Chạy 3 lần thì tịt mất 2 hoặc cả 3. |

---

## 🛠️ 5. Môi trường Cô lập (Sandbox & Limits)

Vì chúng ta đang chạy code sinh ra từ AI, nó hoàn toàn có thể treo máy hoặc ngốn RAM. UT-coder đã bọc chúng trong Sandbox:
- Giới hạn RAM khắt khe (ví dụ: Mutation test tối đa 1.5GB).
- Timeout chặt chẽ (vd: Mỗi lượt chạy test tối đa 30s, Mutation tối đa 3 phút).
- Xóa sạch rác (Ghost coverage files) giữa các lượt chạy.
- Chạy bằng tài khoản UID/GID riêng (`utcoder-sandbox`).

---

## 🚀 6. Hướng dẫn Chạy Benchmark

Nếu bạn là Developer muốn tự đo lường lại AI, hãy làm theo các bước sau:

**Bước 1: Chạy Preflight (Rất Quan Trọng)**
Đảm bảo hệ thống Sandbox và thư viện đánh giá không bị hỏng trước khi chạy 50 task:
```bash
docker compose -f docker-compose.yml exec utcoder python -m core.sandbox.preflight
```
*(Yêu cầu: Coverage phải 100% và Evaluator score = 100.0).*

**Bước 2: Bắt đầu Benchmark chính và RAG ablation**
```bash
docker compose -f docker-compose.yml exec utcoder python core/benchmark/evaluate_models.py
```
Lệnh có khả năng resume: các `Model + TaskID + SourceHash` đã hoàn tất sẽ được bỏ qua. Sau khi benchmark hai model kết thúc và unload thành công, hệ thống tự chạy workbench RAG 20 task × 2 điều kiện. Workbench RAG resume theo `Condition + TaskID + ProjectHash + EvaluatorVersion` và ghi kết quả riêng tại `core/benchmark/rag_ablation/results.csv`.

Chỉ chạy benchmark chính, không chain RAG:

```bash
docker compose -f docker-compose.yml exec utcoder python core/benchmark/evaluate_models.py --skip-rag-ablation
```

Chạy hoặc resume workbench RAG độc lập:

```bash
docker compose -f docker-compose.yml exec utcoder python -m core.benchmark.rag_ablation.evaluate_rag_ablation --condition both
```

Validator 20 project-task:

```bash
docker compose -f docker-compose.yml exec utcoder python -m core.benchmark.rag_ablation.validate_dataset
```

Failed-only mode của benchmark chính không tự chain RAG để tránh mở rộng ngoài tập cặp lỗi được yêu cầu.

**Bước 3: Xem báo cáo (Plot Results)**
```bash
docker compose -f docker-compose.yml exec utcoder python core/benchmark/plot_eval_results.py
```
Reporter chính tạo các hình/bảng so sánh model. Khi workbench RAG đủ 40 dòng ghép cặp, runner tự sinh `core/benchmark/rag_ablation/rag_ablation_table.tex` và file CSV tóm tắt đi kèm.
