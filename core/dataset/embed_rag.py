"""
Optimized RAG Ingestion script for UT-Coder.
Reads clean data from valid_dataset.json, applies AST parsing,
injects Nomic task prefixes, and hides code in metadata.
"""

import argparse
import ast
import hashlib
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Fix path to allow importing core
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.config import get_config
from core.source_analyzer import analyze_python_source

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)

PYTHON_COLLECTION = "utcoder_python_fewshot_v2"
BUILD_COLLECTION = f"{PYTHON_COLLECTION}_building"

def get_semantic_description(source_code: str) -> str:
    """Describe behavior/structure, not only names, for unseen retrieval."""
    analysis = analyze_python_source(source_code)
    if not analysis.get("valid"):
        first_few_lines = "\\n".join(source_code.splitlines()[:3])
        return f"Python code block:\\n{first_few_lines}"

    descriptions: list[str] = []
    for function in analysis.get("functions", []):
        parameters = ", ".join(
            f"{item['name']}:{item.get('annotation') or 'unknown'}"
            for item in function.get("parameters", [])
        )
        details = [
            f"{'async ' if function.get('async') else ''}function {function['name']}({parameters})",
            f"returns {function.get('return_annotation') or 'unknown'}",
        ]
        branches = [item.get("condition") for item in function.get("branches", [])[:6] if item.get("condition")]
        raises = [item.get("exception") for item in function.get("raises", []) if item.get("exception")]
        if branches:
            details.append("branches " + "; ".join(branches))
        if raises:
            details.append("raises " + ", ".join(raises))
        if function.get("mutated_arguments"):
            details.append("mutates " + ", ".join(function["mutated_arguments"]))
        if function.get("external_dependencies"):
            details.append("dependencies " + ", ".join(function["external_dependencies"]))
        if function.get("parameter_attributes"):
            details.append("injected protocol " + ", ".join(function["parameter_attributes"]))
        if function.get("docstring"):
            details.append("purpose " + function["docstring"])
        descriptions.append(" | ".join(details))

    for class_info in analysis.get("classes", []):
        method_names = [method.get("name") for method in class_info.get("methods", [])]
        descriptions.append(
            f"class {class_info['name']} with methods {', '.join(name for name in method_names if name)}"
        )

    route = analysis.get("behavioral_eligibility", {})
    descriptions.append(
        "strategy " + ("pure behavioral" if route.get("eligible") else "objects or mocking")
    )
    return " ".join(descriptions)[:4000]

def process_valid_dataset():
    dataset_dir = Path(__file__).parent
    valid_file = dataset_dir / "valid_dataset.json"

    if not valid_file.exists():
        logger.error(f"{valid_file.name} not found! Run validation script first.")
        return []

    with open(valid_file, "r", encoding="utf-8") as f:
        rows = json.load(f)

    eligible = [
        row for row in rows
        if row.get("rag_schema_version") == 2
        and row.get("rag_eligible") is True
        and row.get("rag_tests")
    ]
    logger.info("Loaded %d rows; %d meet RAG schema v2 quality gates.", len(rows), len(eligible))
    if rows and not eligible:
        logger.error("No RAG-ready rows. Run: python -m core.dataset.prepare_rag_dataset --write")
    return eligible

def embed_and_store(rows, batch_size=50, max_workers=2, *, activate=True):
    import chromadb
    from langchain_ollama import OllamaEmbeddings

    cfg = get_config()
    chroma_dir = cfg.get("vectorstore", {}).get("chroma_dir", "./chroma_db")
    model_name = cfg.get("vectorstore", {}).get("embedding_model", "nomic-embed-text")
    base_url = cfg.get("llm", {}).get("base_url", "http://ollama:11434")

    client = chromadb.PersistentClient(path=chroma_dir)
    # Build separately. The live Python collection is replaced only after the
    # expected number of rows has been embedded successfully.
    try:
        client.delete_collection(name=BUILD_COLLECTION)
    except Exception:
        pass
    collection = client.create_collection(name=BUILD_COLLECTION)

    embeddings = OllamaEmbeddings(base_url=base_url, model=model_name)

    def embed_row(row):
        semantic_desc = get_semantic_description(row["source"])

        # Nomic specific task prefix for embedding documents
        document_text = f"search_document: {semantic_desc}"

        # We embed the prefixed semantic description
        vector = embeddings.embed_query(document_text)

        dataset_id = row.get("dataset_id") or "py_" + hashlib.sha256(
            f"{row['source']}\0{row['tests']}".encode("utf-8")
        ).hexdigest()[:24]
        return {
            "id": dataset_id,
            "vector": vector,
            "content": document_text, # Lean content for Chroma
            "metadata": {
                "type": "dataset_example",
                "language": "python",
                "dataset_id": dataset_id,
                "task_id": str(row["task_id"]),
                "source": row["source"],
                "tests": row["rag_tests"],
                "coverage": float(row["coverage"]),
                "strategy": row.get("rag_strategy", "unknown"),
                "route_reasons": json.dumps(row.get("rag_route_reasons", [])),
                "rag_schema_version": 2,
            }
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

    actual_count = collection.count()
    if actual_count != len(rows):
        raise RuntimeError(
            f"Incomplete embedding build: expected {len(rows)}, stored {actual_count}. "
            f"Live collection {PYTHON_COLLECTION!r} was not changed."
        )

    if not activate:
        logger.info(
            "Built %d examples in %s without activating a partial collection.",
            actual_count,
            BUILD_COLLECTION,
        )
        return

    try:
        client.delete_collection(name=PYTHON_COLLECTION)
    except Exception:
        pass
    collection.modify(name=PYTHON_COLLECTION)
    final_count = client.get_collection(name=PYTHON_COLLECTION).count()
    if final_count != len(rows):
        raise RuntimeError(f"Post-swap verification failed: expected {len(rows)}, found {final_count}")
    logger.info("Activated %s with %d verified examples.", PYTHON_COLLECTION, final_count)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=None, help="Max rows to embed")
    parser.add_argument("--workers", type=int, default=2, help="Concurrent Ollama embedding calls")
    args = parser.parse_args()

    rows = process_valid_dataset()
    if not rows:
        return

    if args.max is not None:
        rows = rows[:max(0, args.max)]
        if not rows:
            logger.info("No rows selected by --max; nothing was embedded.")
            return

    embed_and_store(
        rows,
        max_workers=max(1, args.workers),
        activate=args.max is None,
    )

if __name__ == "__main__":
    main()
