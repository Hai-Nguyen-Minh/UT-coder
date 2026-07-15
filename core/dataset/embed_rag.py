"""
Optimized RAG Ingestion script for UT-Coder.
Extracts only ground_truth code and unit_tests[0] for lean embeddings.
"""

import argparse
import csv
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import chromadb
from langchain_ollama import OllamaEmbeddings

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

def process_file(csv_path: Path, max_rows: int = None):
    logger.info(f"Processing {csv_path.name}...")
    rows = []
    with csv_path.open(encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            if max_rows and len(rows) >= max_rows:
                break
            task_id = row.get("task_id", "").strip()
            source = row.get("code_ground_truth", "").strip()
            tests = _extract_best_test(row.get("unit_tests", ""))
            if source and tests:
                rows.append({"task_id": task_id, "source": source, "tests": tests})
    return rows

def embed_and_store(rows, batch_size=50, max_workers=4):
    client = chromadb.PersistentClient(path="./chroma_db")
    collection = client.get_or_create_collection(name="utcoder_fewshot_examples")
    embeddings = OllamaEmbeddings(base_url="http://ollama:11434", model="nomic-embed-text")

    def embed_row(row):
        # We only embed the source code (lean embedding)
        vector = embeddings.embed_query(row["source"])
        content = (
            f"**Source Code:**\n```python\n{row['source']}\n```\n\n"
            f"**Correct pytest test file:**\n```python\n{row['tests']}\n```"
        )
        return {
            "id": f"coderm_{row['task_id']}",
            "vector": vector,
            "content": content,
            "metadata": {"type": "dataset_example", "task_id": row["task_id"]}
        }

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        logger.info(f"Embedding batch {i//batch_size + 1}/{(len(rows) + batch_size - 1)//batch_size} (size={len(batch)})...")
        
        batch_ids = []
        batch_vectors = []
        batch_contents = []
        batch_metadatas = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(embed_row, row) for row in batch]
            completed = 0
            for future in as_completed(futures):
                try:
                    res = future.result()
                    batch_ids.append(res["id"])
                    batch_vectors.append(res["vector"])
                    batch_contents.append(res["content"])
                    batch_metadatas.append(res["metadata"])
                    completed += 1
                    if completed % 10 == 0:
                        logger.info(f"  ...embedded {completed}/{len(batch)} items")
                except Exception as e:
                    logger.error(f"Failed to embed row: {e}")
                
        if batch_ids:
            collection.upsert(
                ids=batch_ids,
                embeddings=batch_vectors,
                documents=batch_contents,
                metadatas=batch_metadatas
            )
            logger.info(f"Stored {len(batch_ids)} documents to ChromaDB.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-rows", type=int, default=None, help="Max rows total across all files")
    parser.add_argument("--batch-size", type=int, default=25, help="Batch size for Chroma insertion")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent embedding workers")
    args = parser.parse_args()

    dataset_dir = Path(__file__).parent
    train_dir = dataset_dir / "CodeRM_UnitTest"
    val_dir = dataset_dir / "CodeRM_UnitTest (test)"
    
    csv_files = []
    if train_dir.exists():
        csv_files.extend(train_dir.glob("*.csv"))
    if val_dir.exists():
        csv_files.extend(val_dir.glob("*.csv"))

    all_rows = []
    for csv_file in csv_files:
        rem_rows = args.max_rows - len(all_rows) if args.max_rows else None
        if args.max_rows and rem_rows <= 0:
            break
        all_rows.extend(process_file(csv_file, rem_rows))
        
    logger.info(f"Total valid rows extracted: {len(all_rows)}")
    if all_rows:
        embed_and_store(all_rows, batch_size=args.batch_size, max_workers=args.workers)

if __name__ == "__main__":
    main()
