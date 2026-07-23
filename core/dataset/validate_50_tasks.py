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
    
    injected_test = "from module_under_test import *\n" + test_code
        
    try:
        result = sandbox.run_test(f"{task_id}.py", source_code, injected_test)
        
        if result.success and result.coverage is not None and result.coverage >= 80.0:
            return {"status": "valid", "task_id": task_id, "coverage": result.coverage}
        else:
            full_log = f"--- STDOUT ---\n{result.stdout}\n--- STDERR ---\n{result.stderr}"
            return {"status": "invalid", "task_id": task_id, "error": full_log, "coverage": result.coverage if result.coverage is not None else 0.0}
    except Exception as e:
        return {"status": "invalid", "task_id": task_id, "error": str(e), "coverage": 0}

def main():
    dataset_dir = Path(__file__).parent
    csv_files = list(dataset_dir.glob("CodeRM_UnitTest*/*.csv"))
    
    tasks_to_run = []
    
    for csv_path in csv_files:
        with csv_path.open(encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                task_id = row.get("task_id", "").strip()
                source = row.get("code_ground_truth", "").strip()
                tests = _extract_best_test(row.get("unit_tests", ""))
                
                if source and tests:
                    tasks_to_run.append((task_id, source, tests))
                
                if len(tasks_to_run) >= 50:
                    break
        if len(tasks_to_run) >= 50:
            break
            
    tasks_to_run = tasks_to_run[:50]
    logger.info(f"Running sandbox tests for {len(tasks_to_run)} tasks...")
    
    valid_tasks = []
    invalid_tasks = []
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(validate_task, t[0], t[1], t[2]) for t in tasks_to_run]
        for future in as_completed(futures):
            res = future.result()
            if res["status"] == "valid":
                valid_tasks.append(res)
            else:
                invalid_tasks.append(res)

    logger.info(f"Validation complete! Valid: {len(valid_tasks)}, Invalid: {len(invalid_tasks)}")
    
    # Save a quick debug report
    debug_file = dataset_dir / "debug_50_tasks.json"
    with debug_file.open("w", encoding="utf-8") as f:
        json.dump(invalid_tasks[:5], f, indent=2, ensure_ascii=False) # save first 5 invalid for inspection
        
    logger.info(f"Saved first 5 invalid task details to {debug_file.name}")

if __name__ == "__main__":
    main()
