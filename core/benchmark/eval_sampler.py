import os
import sys
import csv
import json
import random
import glob

# Increase the CSV field size limit
maxInt = sys.maxsize
while True:
    try:
        csv.field_size_limit(maxInt)
        break
    except OverflowError:
        maxInt = int(maxInt / 10)

def sample_dataset(input_dir: str, output_file: str, sample_size: int = 50):
    all_rows = []
    
    # Find all CSV files in the input directory
    csv_files = glob.glob(os.path.join(input_dir, "*.csv"))
    if not csv_files:
        print(f"No CSV files found in {input_dir}")
        return

    print(f"Found {len(csv_files)} CSV files. Reading data...")
    
    for file_path in csv_files:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'code_ground_truth' in row and row['code_ground_truth'].strip():
                    all_rows.append({
                        "task_id": row.get("task_id", ""),
                        "source_code": row["code_ground_truth"]
                    })
    
    if len(all_rows) < sample_size:
        print(f"Warning: Only {len(all_rows)} valid rows found. Using all available.")
        sample_size = len(all_rows)
    
    sampled = random.sample(all_rows, sample_size)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(sampled, f, indent=2)
        
    print(f"Successfully sampled {sample_size} snippets and saved to {output_file}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, default="core/dataset/CodeRM_UnitTest (test)")
    parser.add_argument("--output", type=str, default="core/benchmark/eval_dataset.json")
    parser.add_argument("--size", type=int, default=50)
    args = parser.parse_args()
    
    sample_dataset(args.input, args.output, args.size)
