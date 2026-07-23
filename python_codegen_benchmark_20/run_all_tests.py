from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
tasks = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("task_"))
failed = []

for task in tasks:
    print(f"\n=== {task.name} ===")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_solution.py"],
        cwd=task,
        text=True
    )
    if result.returncode != 0:
        failed.append(task.name)

if failed:
    print("\nFAILED:", ", ".join(failed))
    raise SystemExit(1)

print(f"\nAll {len(tasks)} tasks passed.")
