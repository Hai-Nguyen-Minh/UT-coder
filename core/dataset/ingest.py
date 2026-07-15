"""
core/dataset/ingest.py
======================
Fine-tuning pipeline for the UTcoder unit-test generation model (6GB GPU Optimized).

Data layout (core/dataset/):
  CodeRM_UnitTest.csv          → training split
  CodeRM_UnitTest (test).csv   → validation split

CSV columns:
  task_id           – unique integer row identifier
  question          – natural-language problem description
  code_ground_truth – canonical reference implementation (Python)
  code_generate     – JSON array of candidate generated solutions
  unit_tests        – JSON array of candidate unit-test suites

The script converts each row into a chat-style fine-tuning sample:
  system  → expert unit-test writer persona
  user    → question + code_ground_truth
  assistant → best unit-test suite (first entry of unit_tests)

Run with --help for the full list of options.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Iterator

import chromadb
from langchain_core.documents import Document

try:
    from ..config import get_config
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from core.config import get_config

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATASET_DIR = Path(__file__).parent
TRAIN_CSV   = DATASET_DIR / "CodeRM_UnitTest/"
VAL_CSV     = DATASET_DIR / "CodeRM_UnitTest (test)/"

# Default output dir (project root / finetune_output)
DEFAULT_OUTPUT_DIR = DATASET_DIR.parents[1] / "finetune_output"

# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

csv.field_size_limit(10_000_000)  # rows contain large code blobs

SYSTEM_PROMPT = (
    "You are a senior software engineer and expert test writer.\n"
    "Given a programming problem description and its ground-truth solution,\n"
    "your task is to produce a comprehensive, production-quality Python unit-test\n"
    "suite using the `unittest` framework.\n\n"
    "Requirements:\n"
    "- Cover ALL public functions and edge cases.\n"
    "- Include happy-path, boundary, and exception tests.\n"
    "- Write descriptive test method names (snake_case, read like sentences).\n"
    "- Output ONLY the test file source code — no markdown fences, no prose."
)


def _extract_best_unit_test(raw: str) -> str | None:
    """
    Parse the ``unit_tests`` column (JSON array of {ut_id, code} objects)
    and return the code of the first entry, or *None* if parsing fails.
    """
    try:
        entries: list[dict[str, Any]] = json.loads(raw)
        if entries and isinstance(entries, list):
            code = entries[0].get("code", "").strip()
            return code if code else None
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _iter_csv(path: Path, max_rows: int | None = None) -> Iterator[dict[str, str]]:
    """Yield raw rows from *path* up to *max_rows* (None = unlimited)."""
    logger.info("Opening CSV: %s", path)
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        for idx, row in enumerate(reader):
            if max_rows is not None and idx >= max_rows:
                break
            yield row


def build_samples(
    path: Path,
    max_rows: int | None = None,
    skip_empty_tests: bool = True,
) -> list[dict[str, Any]]:
    """
    Convert CSV rows into fine-tuning samples.

    Each sample is a dict with a ``messages`` key containing a list of
    ``{role, content}`` dicts (OpenAI chat format), plus metadata fields:
    ``task_id``, ``split``.
    """
    split = "train" if "test" not in path.stem.lower() else "validation"
    samples: list[dict[str, Any]] = []
    skipped = 0

    for row in _iter_csv(path, max_rows=max_rows):
        task_id          = row.get("task_id", "").strip()
        question         = row.get("question", "").strip()
        code_ground_truth = row.get("code_ground_truth", "").strip()
        unit_tests_raw   = row.get("unit_tests", "")

        best_test = _extract_best_unit_test(unit_tests_raw)
        if skip_empty_tests and not best_test:
            skipped += 1
            continue

        user_content = (
            f"Problem description:\n{question}\n\n"
            f"Ground-truth solution (Python):\n```python\n{code_ground_truth}\n```\n\n"
            "Generate comprehensive unit tests for the solution above."
        )

        assistant_content = best_test or ""

        sample: dict[str, Any] = {
            "task_id": task_id,
            "split": split,
            "messages": [
                {"role": "system",    "content": SYSTEM_PROMPT},
                {"role": "user",      "content": user_content},
                {"role": "assistant", "content": assistant_content},
            ],
        }
        samples.append(sample)

    logger.info(
        "Built %d samples from '%s' (skipped %d empty-test rows)",
        len(samples), path.name, skipped,
    )
    return samples


# ---------------------------------------------------------------------------
# JSONL serialisation
# ---------------------------------------------------------------------------

def save_jsonl(samples: list[dict[str, Any]], out_path: Path) -> None:
    """Write *samples* to *out_path* in JSON-Lines format."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for s in samples:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    logger.info("Saved %d records → %s", len(samples), out_path)


def save_to_chromadb(samples: list[dict[str, Any]], collection_name: str) -> None:
    """
    Store training samples in ChromaDB for vector search and retrieval.
    
    Converts each sample into a LangChain Document where:
    - page_content: concatenation of user and assistant messages
    - metadata: task_id, split, and full messages
    """
    config = get_config()
    chroma_dir = config["vectorstore"]["chroma_dir"]
    
    docs: list[Document] = []
    for sample in samples:
        task_id = sample.get("task_id", "unknown")
        split = sample.get("split", "unknown")
        messages = sample.get("messages", [])
        
        # Extract user and assistant content for the document
        user_content = ""
        assistant_content = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_content = msg.get("content", "")
            elif msg.get("role") == "assistant":
                assistant_content = msg.get("content", "")
        
        # Combine content for semantic search
        page_content = f"User Query:\n{user_content}\n\nExpected Output:\n{assistant_content}"
        
        doc = Document(
            page_content=page_content,
            metadata={
                "task_id": task_id,
                "split": split,
                "messages": json.dumps(messages, ensure_ascii=False),
            }
        )
        docs.append(doc)
    
    # Store documents in ChromaDB
    if not docs:
        logger.warning("No samples to store in ChromaDB")
        return
    
    try:
        client = chromadb.PersistentClient(path=chroma_dir)
        # Delete existing collection if present
        try:
            client.delete_collection(collection_name)
            logger.info("Deleted existing ChromaDB collection: %s", collection_name)
        except Exception:
            pass  # Collection didn't exist — that's fine
        
        # Create new collection
        collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        
        # Add documents with IDs
        for idx, doc in enumerate(docs):
            collection.add(
                ids=[f"{collection_name}_doc_{idx}"],
                documents=[doc.page_content],
                metadatas=[doc.metadata],
            )
        
        logger.info("Stored %d samples in ChromaDB collection '%s'", len(docs), collection_name)
    except Exception as e:
        logger.error("Failed to store samples in ChromaDB: %s", e)
        raise


# ---------------------------------------------------------------------------
# Fine-tuning with HuggingFace Transformers + PEFT (LoRA)
# ---------------------------------------------------------------------------

def _require_packages() -> None:
    """Raise a helpful error if optional fine-tuning deps are missing."""
    missing = []
    for pkg in ("transformers", "peft", "torch", "datasets", "trl", "bitsandbytes", "accelerate"):
        try:
            __import__(pkg)
        except ModuleNotFoundError:
            missing.append(pkg)
    if missing:
        raise ImportError(
            "The following packages are required for 6GB GPU fine-tuning but are missing:\n"
            f"  {', '.join(missing)}\n\n"
            "Install them with:\n"
            "  pip install transformers peft torch datasets trl accelerate bitsandbytes\n"
        )


def _format_messages_fallback(messages: list[dict[str, str]]) -> str:
    """Fallback manual formatting when tokenizer.chat_template is not available."""
    formatted = ""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            formatted += f"<system>\n{content}\n</system>\n\n"
        elif role == "user":
            formatted += f"<user>\n{content}\n</user>\n\n"
        elif role == "assistant":
            formatted += f"<assistant>\n{content}\n</assistant>\n"
    return formatted


def _format_chat_with_fallback(sample: dict[str, Any], tokenizer: Any) -> dict[str, Any]:
    """Apply the tokenizer's chat template to the messages list."""
    messages = sample.get("messages", [])

    try:
        text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
        )
    except ValueError as e:
        if "chat_template" in str(e):
            logger.warning(
                "Model '%s' has no chat_template. Using fallback formatting.",
                tokenizer.name_or_path,
            )
            text = _format_messages_fallback(messages)
        else:
            raise

    return {"text": text}


def finetune(
    base_model: str,
    output_dir: Path,
    train_jsonl: Path,
    val_jsonl: Path,
    *,
    lora_r: int = 16,
    lora_alpha: int = 32,
    lora_dropout: float = 0.05,
    max_seq_length: int = 512,  # Lowered default for 6GB VRAM
    num_train_epochs: int = 3,
    per_device_train_batch_size: int = 1,
    gradient_accumulation_steps: int = 4,
    learning_rate: float = 2e-4,
    warmup_ratio: float = 0.05,
    fp16: bool = True,  # Enabled by default for GPU speed/memory
    bf16: bool = False,
    logging_steps: int = 10,
    save_steps: int = 200,
    eval_steps: int = 200,
    load_in_4bit: bool = True, # Enabled by default for 6GB VRAM
) -> None:

    if ":" in base_model and not Path(base_model).exists():
        raise ValueError(
            f"Invalid base_model format: '{base_model}'\n\n"
            "It looks like you're using an Ollama model ID (contains ':').\n"
            "For fine-tuning, you MUST use a HuggingFace model ID."
        )

    _require_packages()

    import torch
    from datasets import load_dataset
    from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig
    )
    from trl import SFTTrainer, SFTConfig

    logger.info("Loading tokenizer from '%s'", base_model)
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # ── Model loading (6GB GPU Optimization) ───────────────────────────────
    quant_cfg = None
    if load_in_4bit:
        logger.info("Preparing 4-bit Quantization Config (QLoRA) for VRAM conservation.")
        quant_cfg = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )

    logger.info("Loading base model '%s' on GPU (device_map='auto')", base_model)
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=quant_cfg,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.float16 if fp16 else torch.float32,
    )

    # Required for gradient checkpointing and memory reduction
    model.config.use_cache = False
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()

    # Prepare model for 4-bit training (CRITICAL FOR QLoRA)
    if load_in_4bit:
        model = prepare_model_for_kbit_training(model)

    # ── LoRA configuration ─────────────────────────────────────────────────
    lora_cfg = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        bias="none",
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_cfg)
    model.print_trainable_parameters()

    # ── Dataset loading ────────────────────────────────────────────────────
    logger.info("Loading datasets from JSONL files")
    raw_datasets = load_dataset(
        "json",
        data_files={"train": str(train_jsonl), "validation": str(val_jsonl)},
    )

    def apply_template(batch: dict) -> dict:
        texts = []
        for msgs in batch["messages"]:
            sample = {"messages": msgs}
            formatted = _format_chat_with_fallback(sample, tokenizer)
            texts.append(formatted["text"])
        return {"text": texts}

    logger.info("Applying chat template to datasets")
    try:
        tokenized = raw_datasets.map(apply_template, batched=True, remove_columns=raw_datasets["train"].column_names)
    except ValueError as e:
        if "chat_template" in str(e):
            raise ValueError(f"Failed to apply chat template to the model.") from e
        raise

    # ── Training arguments (6GB GPU Optimization) ──────────────────────────
    training_args = SFTConfig(
        output_dir=str(output_dir),
        max_length=max_seq_length,  # <-- Moved here!
        dataset_text_field="text",  # <-- Added for newer trl compatibility
        num_train_epochs=num_train_epochs,
        per_device_train_batch_size=per_device_train_batch_size,
        per_device_eval_batch_size=per_device_train_batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        learning_rate=learning_rate,
        warmup_ratio=warmup_ratio,
        lr_scheduler_type="cosine",
        fp16=fp16,
        bf16=bf16,
        logging_steps=logging_steps,
        save_steps=save_steps,
        eval_steps=eval_steps,
        eval_strategy="steps",
        save_strategy="steps",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to="none",
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
        dataloader_pin_memory=False,
    )

    # ── Trainer ────────────────────────────────────────────────────────────
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["validation"],
        # Pass explicit max sequence to SFTTrainer
    )

    logger.info("Starting fine-tuning on GPU with 6GB optimizations...")
    trainer.train()

    # ── Save adapter ───────────────────────────────────────────────────────
    final_adapter_dir = output_dir / "final_adapter"
    logger.info("Saving LoRA adapter → %s", final_adapter_dir)
    trainer.model.save_pretrained(str(final_adapter_dir))
    tokenizer.save_pretrained(str(final_adapter_dir))
    logger.info("Fine-tuning complete.")


# ---------------------------------------------------------------------------
# Validation-only evaluation
# ---------------------------------------------------------------------------

def evaluate_only(
    adapter_path: str,
    val_jsonl: Path,
    base_model: str | None = None,
    max_new_tokens: int = 512,
    num_samples: int = 10,
) -> None:
    _require_packages()

    import torch
    from peft import PeftModel, PeftConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

    peft_cfg = PeftConfig.from_pretrained(adapter_path)
    resolved_base = base_model or peft_cfg.base_model_name_or_path
    logger.info("Loading base model '%s' for GPU evaluation", resolved_base)

    tokenizer = AutoTokenizer.from_pretrained(resolved_base, trust_remote_code=True)
    base = AutoModelForCausalLM.from_pretrained(
        resolved_base,
        device_map="auto", # Use GPU
        trust_remote_code=True,
        torch_dtype=torch.float16,
    )
    model = PeftModel.from_pretrained(base, adapter_path)
    model.eval()

    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )

    with val_jsonl.open(encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]

    rows = rows[:num_samples]
    separator = "=" * 70

    from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
    from core.sandbox import get_sandbox
    
    sandbox = get_sandbox("python") # Assuming dataset is python as per prompt

    total_bleu = 0.0
    exact_matches = 0
    passed_sandbox = 0
    valid_sandbox_runs = 0

    for i, row in enumerate(rows, 1):
        messages       = row["messages"]
        task_id        = row.get("task_id", "?")
        expected_code  = messages[-1]["content"]
        prompt_msgs    = messages[:-1]

        # Extract source code from user message
        user_msg = next((m["content"] for m in prompt_msgs if m["role"] == "user"), "")
        source_code = ""
        import re
        code_match = re.search(r"Ground-truth solution \(Python\):\n```python\n(.*?)\n```", user_msg, re.DOTALL)
        if code_match:
            source_code = code_match.group(1).strip()

        try:
            prompt_text = tokenizer.apply_chat_template(
                prompt_msgs, tokenize=False, add_generation_prompt=True
            )
        except ValueError as e:
            if "chat_template" in str(e):
                logger.warning("No chat template; using fallback format")
                prompt_text = _format_messages_fallback(prompt_msgs)
            else:
                raise

        output = pipe(prompt_text)[0]["generated_text"]
        generated = output[len(prompt_text):].strip()
        
        # Clean markdown fences
        fence_match = re.search(r"```(?:\w+)?\s*\n(.*?)\n```", generated, re.DOTALL)
        if fence_match:
            clean_code = fence_match.group(1).strip()
        else:
            clean_code = generated.strip()

        # 1. Exact Match
        is_exact = clean_code == expected_code.strip()
        if is_exact:
            exact_matches += 1

        # 2. BLEU Score
        expected_tokens = expected_code.split()
        generated_tokens = clean_code.split()
        chencherry = SmoothingFunction()
        bleu = sentence_bleu([expected_tokens], generated_tokens, smoothing_function=chencherry.method1)
        total_bleu += bleu

        # 3. Sandbox Evaluation
        sandbox_success = False
        if source_code:
            valid_sandbox_runs += 1
            result = sandbox.run_test(f"task_{task_id}.py", source_code, clean_code)
            if result.success:
                sandbox_success = True
                passed_sandbox += 1

        print(f"\n{separator}")
        print(f"Sample {i}/{num_samples}  |  task_id={task_id}")
        print(f"Metrics: Exact Match = {is_exact}, BLEU = {bleu:.4f}, Sandbox Pass = {sandbox_success}")
        print(f"{separator}")
        print("── EXPECTED ──")
        print(expected_code[:600] + (" …" if len(expected_code) > 600 else ""))
        print("── GENERATED ──")
        print(clean_code[:600] + (" …" if len(clean_code) > 600 else ""))

    avg_bleu = total_bleu / len(rows) if rows else 0
    exact_match_rate = exact_matches / len(rows) if rows else 0
    sandbox_pass_rate = passed_sandbox / valid_sandbox_runs if valid_sandbox_runs else 0

    print(f"\n{separator}")
    print(f"FINAL EVALUATION METRICS (N={len(rows)}):")
    print(f"- Exact Match Rate: {exact_match_rate * 100:.2f}%")
    print(f"- Average BLEU: {avg_bleu * 100:.2f}")
    print(f"- Sandbox Pass Rate: {sandbox_pass_rate * 100:.2f}% ({passed_sandbox}/{valid_sandbox_runs})")
    print(f"{separator}")
    logger.info("Evaluation complete for %d samples.", len(rows))


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m core.dataset.ingest",
        description="UTcoder fine-tuning pipeline: ingest CSVs, train, and evaluate.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ── ingest ─────────────────────────────────────────────────────────────
    ingest_p = sub.add_parser("ingest", help="Convert CSVs to JSONL fine-tuning datasets only.")
    ingest_p.add_argument("--train-csv",   required=True,  help="Path to training CSV.")
    ingest_p.add_argument("--val-csv",     required=True,    help="Path to validation CSV.")
    ingest_p.add_argument("--output-dir",  default=str(DEFAULT_OUTPUT_DIR), help="Directory to write JSONL files.")
    ingest_p.add_argument("--max-rows",    type=int, default=None,  help="Limit rows (for testing).")

    # ── train ──────────────────────────────────────────────────────────────
    train_p = sub.add_parser("train", help="Ingest CSVs and fine-tune a model with LoRA on GPU.")
    train_p.add_argument("--base-model",   default=str("deepseek-ai/deepseek-coder-6.7b-instruct"), help="HuggingFace model ID or local path.")
    train_p.add_argument("--train-csv",    required=True,  help="Path to training CSV.")
    train_p.add_argument("--val-csv",      required=True,    help="Path to validation CSV.")
    train_p.add_argument("--output-dir",   default=str(DEFAULT_OUTPUT_DIR), help="Output directory for adapter.")
    train_p.add_argument("--max-rows",     type=int, default=None,  help="Limit rows.")
    train_p.add_argument("--lora-r",       type=int, default=16,    help="LoRA rank.")
    train_p.add_argument("--lora-alpha",   type=int, default=32,    help="LoRA alpha.")
    train_p.add_argument("--lora-dropout", type=float, default=0.05,help="LoRA dropout.")
    train_p.add_argument("--max-seq-len",  type=int, default=512,   help="Max sequence length (Keep <= 512 for 6GB).")
    train_p.add_argument("--epochs",       type=int, default=3,     help="Training epochs.")
    train_p.add_argument("--batch-size",   type=int, default=1,     help="Batch size (Keep at 1 for 6GB).")
    train_p.add_argument("--grad-accum",   type=int, default=4,     help="Gradient accumulation steps.")
    train_p.add_argument("--lr",           type=float, default=2e-4,help="Learning rate.")
    train_p.add_argument("--warmup-ratio", type=float, default=0.05,help="Warmup ratio.")
    train_p.add_argument("--fp16",         action="store_true",     default=True, help="Use fp16 (Enabled by default for GPU).")
    train_p.add_argument("--bf16",         action="store_true",     help="Use bf16 instead of fp16.")
    train_p.add_argument("--4bit",         dest="load_in_4bit", action="store_true", default=True, help="Load model in 4-bit (Enabled by default).")
    train_p.add_argument("--logging-steps",type=int, default=10,    help="Log every N steps.")
    train_p.add_argument("--save-steps",   type=int, default=200,   help="Save every N steps.")
    train_p.add_argument("--eval-steps",   type=int, default=200,   help="Evaluate every N steps.")

    # ── evaluate ───────────────────────────────────────────────────────────
    eval_p = sub.add_parser("evaluate", help="Run inference with a saved LoRA adapter.")
    eval_p.add_argument("--adapter-path",  required=True,           help="Path to saved adapter.")
    eval_p.add_argument("--val-csv",       required=True,    help="Path to validation CSV.")
    eval_p.add_argument("--base-model",    default=None,            help="Override base model ID.")
    eval_p.add_argument("--output-dir",    default=str(DEFAULT_OUTPUT_DIR), help="Directory with JSONL files.")
    eval_p.add_argument("--max-rows",      type=int, default=None,  help="Limit rows.")
    eval_p.add_argument("--num-samples",   type=int, default=10,    help="Samples to evaluate.")
    eval_p.add_argument("--max-new-tokens",type=int, default=512,   help="Max tokens to generate.")

    return p


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args   = parser.parse_args(argv)

    output_dir = Path(args.output_dir)

    if args.command == "ingest":
        train_samples = build_samples(Path(args.train_csv), max_rows=args.max_rows)
        val_samples   = build_samples(Path(args.val_csv),   max_rows=args.max_rows)
        save_jsonl(train_samples, output_dir / "train.jsonl")
        save_jsonl(val_samples,   output_dir / "val.jsonl")
        save_to_chromadb(train_samples, "training_samples")
        save_to_chromadb(val_samples, "validation_samples")
        logger.info("Ingest complete. Files written to: %s", output_dir)

    elif args.command == "train":
        train_jsonl = output_dir / "train.jsonl"
        val_jsonl   = output_dir / "val.jsonl"

        train_samples = build_samples(Path(args.train_csv), max_rows=args.max_rows)
        val_samples   = build_samples(Path(args.val_csv),   max_rows=args.max_rows)
        save_jsonl(train_samples, train_jsonl)
        save_jsonl(val_samples,   val_jsonl)
        save_to_chromadb(train_samples, "training_samples")
        save_to_chromadb(val_samples, "validation_samples")

        finetune(
            base_model=args.base_model,
            output_dir=output_dir,
            train_jsonl=train_jsonl,
            val_jsonl=val_jsonl,
            lora_r=args.lora_r,
            lora_alpha=args.lora_alpha,
            lora_dropout=args.lora_dropout,
            max_seq_length=args.max_seq_len,
            num_train_epochs=args.epochs,
            per_device_train_batch_size=args.batch_size,
            gradient_accumulation_steps=args.grad_accum,
            learning_rate=args.lr,
            warmup_ratio=args.warmup_ratio,
            fp16=args.fp16,
            bf16=args.bf16,
            load_in_4bit=args.load_in_4bit,
            logging_steps=args.logging_steps,
            save_steps=args.save_steps,
            eval_steps=args.eval_steps,
        )

    elif args.command == "evaluate":
        val_jsonl = output_dir / "val.jsonl"
        if not val_jsonl.exists():
            val_samples = build_samples(Path(args.val_csv), max_rows=args.max_rows)
            save_jsonl(val_samples, val_jsonl)
            save_to_chromadb(val_samples, "validation_samples")

        evaluate_only(
            adapter_path=args.adapter_path,
            val_jsonl=val_jsonl,
            base_model=args.base_model,
            num_samples=args.num_samples,
            max_new_tokens=args.max_new_tokens,
        )


if __name__ == "__main__":
    main()