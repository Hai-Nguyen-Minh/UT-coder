import csv
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Fix path to allow importing core
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.sandbox.python_sandbox import PythonSandbox

# Increase csv size limit
csv.field_size_limit(10_000_000)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)

def _extract_best_test(raw: str) -> str:
    try:
        entries = json.loads(raw)
        if entries and isinstance(entries, list):
            return entries[0].get("code", "").strip()
    except Exception:
        pass
    return ""

def validate_task(task_id: str, source_code: str, test_code: str):
    sandbox = PythonSandbox()
    
    # FORCE INJECT wildcard import so the tests can access the functions.
    # We do this unconditionally to ensure it's always there.
    injected_test = "from module_under_test import *\n" + test_code
        
    try:
        # We pass task_id as file_name
        result = sandbox.run_test(f"{task_id}.py", source_code, injected_test)
        
        if result.success and result.coverage is not None and result.coverage >= 80.0:
            return {
                "status": "valid", 
                "task_id": task_id, 
                "source": source_code, 
                "tests": injected_test, 
                "coverage": result.coverage
            }
        else:
            # Combine STDOUT and STDERR so we can see the ACTUAL Pytest output
            full_log = f"--- STDOUT ---\n{result.stdout}\n--- STDERR ---\n{result.stderr}"
            return {
                "status": "invalid", 
                "task_id": task_id, 
                "source": source_code, 
                "tests": injected_test, 
                "error": full_log, 
                "coverage": result.coverage if result.coverage is not None else 0.0
            }
    except Exception as e:
        return {"status": "invalid", "task_id": task_id, "source": source_code, "tests": injected_test, "error": str(e), "coverage": 0}

def main():
    dataset_dir = Path(__file__).parent
    csv_files = list(dataset_dir.glob("CodeRM_UnitTest*/*.csv"))
    
    if not csv_files:
        logger.error("No CSV files found in CodeRM_UnitTest* directories.")
        return

    tasks_to_run = []
    
    # Read all tasks
    for csv_path in csv_files:
        logger.info(f"Reading {csv_path.name}...")
        with csv_path.open(encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                task_id = row.get("task_id", "").strip()
                source = row.get("code_ground_truth", "").strip()
                tests = _extract_best_test(row.get("unit_tests", ""))
                
                if source and tests:
                    tasks_to_run.append((task_id, source, tests))
    
    logger.info(f"Found {len(tasks_to_run)} valid entries to validate. Running sandbox tests...")
    
    valid_tasks = []
    invalid_tasks = []
    
    # Run sandbox validations concurrently
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(validate_task, t[0], t[1], t[2]) for t in tasks_to_run]
        
        completed = 0
        for future in as_completed(futures):
            res = future.result()
            if res["status"] == "valid":
                valid_tasks.append(res)
            else:
                invalid_tasks.append(res)
                
            completed += 1
            if completed % 50 == 0:
                logger.info(f"Validated {completed}/{len(tasks_to_run)} tasks. (Valid: {len(valid_tasks)}, Invalid: {len(invalid_tasks)})")

    logger.info(f"Validation complete! Total Valid: {len(valid_tasks)}, Total Invalid: {len(invalid_tasks)}")
    
    # Save results
    valid_file = dataset_dir / "valid_dataset.json"
    invalid_file = dataset_dir / "invalid_dataset.json"
    
    with valid_file.open("w", encoding="utf-8") as f:
        json.dump(valid_tasks, f, indent=2, ensure_ascii=False)
        
    with invalid_file.open("w", encoding="utf-8") as f:
        json.dump(invalid_tasks, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Saved valid tasks to {valid_file.name} and invalid tasks to {invalid_file.name}")

if __name__ == "__main__":
    main()
