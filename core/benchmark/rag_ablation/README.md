# RAG Ablation Workbench

Workbench này đo riêng đóng góp của RAG đối với việc sinh unit test Python có
ngữ cảnh dự án. Nó không dùng lại 20 bài đầu của benchmark chính vì phần lớn
các bài đó là hàm độc lập và không buộc mô hình phải truy xuất module nội bộ.

## Thiết kế thí nghiệm

- Một mô hình cố định: `qwen2.5-coder:7b`.
- 20 project-task, cân bằng thành 5 nhóm, mỗi nhóm 4 bài.
- Mỗi task chạy theo cặp `RAG_OFF` và `RAG_ON` với cùng source, cấu hình sinh,
  evaluator và sandbox.
- Thứ tự hai điều kiện được đảo xen kẽ giữa các task để giảm thiên lệch do
  warm-up hoặc thứ tự chạy.
- `RAG_ON` truy xuất tối đa 4 đoạn ngữ cảnh từ các file hỗ trợ của project;
  `RAG_OFF` không gọi ChromaDB, project index, project search hoặc few-shot
  search.
- Reference tests chỉ dùng để kiểm định dataset và không được đưa vào prompt.

Dataset nằm tại `core/benchmark/rag_ablation/dataset.json`. Có thể kiểm định
toàn bộ 20 project-task trước khi chạy:

```bash
python -m core.benchmark.rag_ablation.validate_dataset
```

## Cách chạy

Benchmark chính tự động nối sang workbench này sau khi hoàn thành cả hai model
và xác nhận đã unload model khỏi Ollama:

```bash
python core/benchmark/evaluate_models.py
```

Nếu benchmark chính đã có kết quả dở dang, lệnh trên dùng cơ chế resume hiện
có, bỏ qua các task đã hoàn thành rồi mới chuyển sang RAG ablation. Chế độ
`--rerun-failed-from` không tự nối vì đó chỉ là một lượt sửa lỗi có phạm vi hẹp.

Chạy độc lập hai điều kiện:

```bash
python -m core.benchmark.rag_ablation.evaluate_rag_ablation
```

Chỉ chạy một nhánh khi cần chẩn đoán:

```bash
python -m core.benchmark.rag_ablation.evaluate_rag_ablation --condition rag
python -m core.benchmark.rag_ablation.evaluate_rag_ablation --condition no-rag
```

Tắt bước nối tự động của benchmark chính:

```bash
python core/benchmark/evaluate_models.py --skip-rag-ablation
```

## Kết quả

- `results.csv`: kết quả chi tiết theo từng task và điều kiện.
- `results.jsonl`: chẩn đoán có cấu trúc phục vụ truy vết.
- `manifest.json`: khóa phiên bản dataset, generator, evaluator, model và cấu
  hình nhằm ngăn resume trên một thí nghiệm không tương thích.
- `results_artifacts/`: artifact evaluator theo task/điều kiện.
- `rag_ablation_table.tex`: bảng tổng hợp LaTeX, chỉ sinh khi đủ 20 cặp.

Khóa resume gồm điều kiện, TaskID, project hash và evaluator version. Vì vậy
một dòng từ dataset hoặc evaluator cũ không thể làm task mới bị bỏ qua hay làm
workbench báo hoàn tất nhầm.
