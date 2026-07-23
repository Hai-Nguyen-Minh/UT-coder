import json
import logging
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.sandbox.python_sandbox import PythonSandbox
from core.llm import get_llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)

def extract_python_code(text: str) -> str:
    match = re.search(r'```python(.*?)```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()

def heal_task(task, llm):
    task_id = task["task_id"]
    source = task["source"]
    old_test = task["tests"]
    error_log = task.get("error", "Low coverage")
    
    prompt = f"""You are an expert Python QA Engineer.
A unit test failed or had insufficient coverage.
Source code:
```python
{source}
```

Failing Test code:
```python
{old_test}
```

Error / Coverage issue:
{error_log}

Rewrite the test code using `unittest` to fix the errors and achieve 100% coverage.
Return ONLY valid Python code inside ```python ``` blocks.
"""
    logger.info(f"Task {task_id}: Asking AI to fix...")
    try:
        response = llm.invoke(prompt)
        new_test = extract_python_code(response.content)
        
        # Inject module import
        if "module_under_test" not in new_test:
            new_test = "from module_under_test import *\n" + new_test
            
        sandbox = PythonSandbox()
        result = sandbox.run_test(f"{task_id}.py", source, new_test)
        
        if result.success and result.coverage is not None and result.coverage >= 80.0:
            logger.info(f"Task {task_id}: Fixed successfully! Coverage: {result.coverage}%")
            return {"status": "valid", "task_id": task_id, "source": source, "tests": new_test, "coverage": result.coverage}
        else:
            logger.error(f"Task {task_id}: Still failing. Coverage: {result.coverage}")
            return None
    except Exception as e:
        logger.error(f"Task {task_id}: Exception during healing - {str(e)}")
        return None

def main():
    dataset_dir = Path(__file__).parent
    invalid_file = dataset_dir / "invalid_dataset.json"
    valid_file = dataset_dir / "valid_dataset.json"
    
    if not invalid_file.exists():
        logger.error("invalid_dataset.json not found!")
        return
        
    with open(invalid_file, "r", encoding="utf-8") as f:
        invalid_tasks = json.load(f)
        
    if not invalid_tasks:
        logger.info("No invalid tasks to fix.")
        return
        
    llm = get_llm()
    
    logger.info(f"Loaded {len(invalid_tasks)} invalid tasks to heal. Starting auto-healing...")
    
    fixed_tasks = []
    still_invalid = []
    
    for i, task in enumerate(invalid_tasks):
        fixed = heal_task(task, llm)
        if fixed:
            fixed_tasks.append(fixed)
        else:
            still_invalid.append(task)
            
        logger.info(f"Healed {i+1}/{len(invalid_tasks)} tasks. (Fixed: {len(fixed_tasks)}, Failed: {len(still_invalid)})")
        
    if fixed_tasks:
        # Load existing valid
        if valid_file.exists():
            with open(valid_file, "r", encoding="utf-8") as f:
                valid_tasks = json.load(f)
        else:
            valid_tasks = []
            
        valid_tasks.extend(fixed_tasks)
        
        with open(valid_file, "w", encoding="utf-8") as f:
            json.dump(valid_tasks, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Appended {len(fixed_tasks)} fixed tasks to valid_dataset.json")
        
    with open(invalid_file, "w", encoding="utf-8") as f:
        json.dump(still_invalid, f, indent=2, ensure_ascii=False)
        
    logger.info("Healing process complete!")

if __name__ == "__main__":
    main()
