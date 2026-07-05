# UTcoder Setup Guide

**UTcoder** is an AI-powered unit test generator that uses ChromaDB for retrieval-augmented generation (RAG) and Ollama-based large language models to automatically generate comprehensive unit tests for source code.

This guide walks you through building, training, and running the project.

## Table of Contents

1. [Project Overview](#project-overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Building the Project](#building-the-project)
6. [Training the Model](#training-the-model)
7. [Running the Application](#running-the-application)
8. [Troubleshooting](#troubleshooting)
9. [Development Notes](#development-notes)

---

## Project Overview

UTcoder is a web-based application that generates unit tests for source code files using:

- **LLM Backend**: Ollama with models like Deepseek Coder v2 16B
- **Vector Store**: ChromaDB for semantic similarity search and RAG
- **Web UI**: Gradio-based interface for easy interaction
- **Fine-tuning**: Optional LoRA-based model fine-tuning using LangChain, Transformers, and TRL

### Key Features

- **Multi-language Support**: Python, Java, C#, JavaScript
- **RAG Integration**: Indexes code chunks and retrieves relevant context
- **Streaming Output**: Real-time streaming of generated test code
- **Fine-tunable**: Train custom models using the CodeRM dataset
- **Production-Ready Output**: Generates executable, framework-specific unit tests

---

## Prerequisites

### System Requirements

- **OS**: Windows, Linux, or macOS
- **Python**: 3.9 or higher (3.10+ recommended)
- **RAM**: 
  - Minimum: 16 GB (for inference with 16B model)
  - Recommended: 32+ GB (for fine-tuning)
- **GPU** (Optional but strongly recommended):
  - NVIDIA GPU with CUDA support (for faster inference and fine-tuning)
  - 8GB+ VRAM for 16B model inference
  - 24GB+ VRAM for fine-tuning

### Required Software

- **Ollama**: Download and install from https://ollama.ai
  - Required for hosting the Deepseek Coder and embedding models
- **Git**: For version control (optional but recommended)
- **CUDA Toolkit** (if using NVIDIA GPU): Install from https://developer.nvidia.com/cuda-downloads

### Optional Software

- **cuDNN** (for optimized GPU inference)
- **Miniconda or Conda** (for environment management)

---

## Installation

### Step 1: Clone or Download the Project

```powershell
# Clone the repository (if using git)
git clone <repository-url>
cd UTcoder

# Or if already in the project directory
cd C:\Projects\AI\UTcoder
```

### Step 2: Create a Python Virtual Environment

```powershell
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\Activate.ps1

# On Linux/macOS:
source venv/bin/activate
```

If you encounter an execution policy error on Windows, run:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Step 3: Install Dependencies

```powershell
# Upgrade pip, setuptools, and wheel
pip install --upgrade pip setuptools wheel

# Install core dependencies
pip install -r requirements.txt
```

The `requirements.txt` includes:
- **LangChain** (0.2.0+): For LLM orchestration
- **Ollama**: Python client for Ollama
- **ChromaDB** (0.5.0+): Vector store
- **Gradio** (4.36.0+): Web UI framework
- **Torch, Transformers, PEFT, TRL, Datasets**: For optional fine-tuning

### Step 4: Set Up Ollama

1. **Install Ollama**: Download from https://ollama.ai and follow the installation instructions.

2. **Start the Ollama server**:
   ```powershell
   # On Windows, Ollama typically runs as a background service
   # You can verify it's running by checking if it listens on localhost:11434
   
   # On Linux/macOS:
   ollama serve
   ```

3. **Pull the required models**:

   ```powershell
   # Pull the main inference model (Deepseek Coder v2 16B)
   ollama pull deepseek-coder-v2:16b
   
   # Pull the embedding model (used for ChromaDB)
   ollama pull nomic-embed-text
   ```

   This may take 10-30 minutes depending on your internet speed.

4. **Verify models are available**:
   ```powershell
   ollama list
   ```

---

## Configuration

### config.json

The `config.json` file controls all project settings:

```json
{
    "llm": {
        "provider": "ollama",
        "model": "deepseek-coder-v2:16b",
        "temperature": 0.3,
        "available_models": [
            {
                "id": "deepseek-coder-v2:16b",
                "name": "Deepseek Coder v2 16B",
                "pull_cmd": "ollama pull deepseek-coder-v2:16b"
            }
        ]
    },
    "vectorstore": {
        "chroma_dir": "./chroma_db",
        "embedding_model": "nomic-embed-text"
    },
    "languages": {
        "python": {
            "test_framework": "pytest",
            "file_suffix": "_test.py",
            "display": "Python"
        },
        // ... other languages ...
    },
    "server": {
        "host": "0.0.0.0",
        "port": 7860,
        "debug": true,
        "share": false
    }
}
```

### Configuration Options

| Key | Description | Example |
|-----|-------------|---------|
| `llm.model` | Model ID from Ollama | `deepseek-coder-v2:16b` |
| `llm.temperature` | LLM temperature (0.0-1.0) | `0.3` |
| `vectorstore.chroma_dir` | Path to ChromaDB storage | `./chroma_db` |
| `vectorstore.embedding_model` | Embedding model name | `nomic-embed-text` |
| `languages.<lang>.test_framework` | Test framework for language | `pytest`, `JUnit 5`, etc. |
| `server.host` | Server host (0.0.0.0 = all interfaces) | `0.0.0.0` |
| `server.port` | Server port | `7860` |
| `server.debug` | Enable debug mode | `true` / `false` |
| `server.share` | Share link via ngrok (Gradio) | `true` / `false` |

### Customizing Models

To use a different model:

1. Pull it with Ollama:
   ```powershell
   ollama pull <model-name>
   ```

2. Update `config.json`:
   ```json
   "llm": {
       "model": "<model-name>"
   }
   ```

3. Restart the application.

---

## Building the Project

### Verify Dependencies

```powershell
# Activate virtual environment (if not already active)
venv\Scripts\Activate.ps1

# Test imports
python -c "import langchain; import chromadb; import gradio; print('All dependencies OK')"
```

### Initialize ChromaDB

ChromaDB will initialize automatically when you first run the application. To pre-initialize:

```powershell
python -c "from core.vectorstore import _get_embeddings; _get_embeddings()"
```

### Verify LLM Connectivity

```powershell
python -c "from core.llm import get_llm; llm = get_llm(); print('LLM ready:', llm)"
```

---

## Training the Model

UTcoder supports fine-tuning your own model using the CodeRM dataset or your own data.

### Prerequisites for Training

1. Install additional fine-tuning dependencies:
   ```powershell
   pip install accelerate bitsandbytes
   ```

2. Have training data in CSV format with columns:
   - `task_id`: Unique identifier
   - `question`: Problem description
   - `code_ground_truth`: Reference implementation
   - `unit_tests`: JSON array of unit test suites

### Step 1: Prepare Data

Place your training and validation CSVs in `core/dataset/`:
- `CodeRM_UnitTest.csv` (training split)
- `CodeRM_UnitTest (test).csv` (validation split)

### Step 2: Ingest Data (Convert CSV to JSONL)

```powershell
# Convert CSVs to fine-tuning format (JSONL)
python ingest.py ingest --train-csv "CodeRM_UnitTest/CodeRM_UnitTest_1783230463066.csv" --val-csv "CodeRM_UnitTest (test)/CodeRM_UnitTest (test)_1783230535320.csv" --max-rows 100
```

This generates:
- `finetune_output/train.jsonl`
- `finetune_output/val.jsonl`

### Step 3: Fine-tune the Model

```powershell
# Fine-tune a base model with LoRA
python ingest.py train --train-csv "CodeRM_UnitTest/CodeRM_UnitTest_1783230463066.csv" --val-csv "CodeRM_UnitTest (test)/CodeRM_UnitTest (test)_1783230535320.csv" --max-rows 100 
```

#### Recommended HuggingFace Models for Fine-tuning

⚠️ **Important**: Use **instruction-tuned models** for best results. Base models may lack chat templates.

| Model | Size | HuggingFace ID | Type |
|-------|------|----------------|------|
| Deepseek Coder Instruct | 6.7B | `deepseek-ai/deepseek-coder-6.7b-instruct` | ✅ Instruction-tuned |
| Deepseek Coder Base | 6.7B | `deepseek-ai/deepseek-coder-6.7b-base` | ⚠️ Base (no template) |
| CodeLLaMA Instruct | 7B | `meta-llama/CodeLlama-7b-Instruct-hf` | ✅ Instruction-tuned |
| CodeLLaMA Base | 7B | `meta-llama/CodeLlama-7b-hf` | ⚠️ Base (no template) |
| Phi-2 | 2.7B | `microsoft/phi-2` | ✅ Instruction-tuned |
| Mistral Instruct | 7B | `mistralai/Mistral-7B-Instruct-v0.1` | ✅ Instruction-tuned |

**Note**: 
- Models marked with ✅ have built-in chat templates and will train without issues
- Models marked with ⚠️ may encounter `chat_template` errors; use instruction-tuned alternatives
- Larger models (13B+) require more VRAM. Use `--4bit` flag for quantized fine-tuning

**Optional flags**:
- `--4bit`: Use 4-bit quantization (QLoRA) for lower memory usage
- `--bf16`: Use bfloat16 mixed precision
- `--fp16`: Use float16 mixed precision
- `--max-rows N`: Limit rows for testing
- `--logging-steps N`: Log every N steps
- `--save-steps N`: Save checkpoint every N steps

### Step 4: Evaluate the Fine-tuned Model

```powershell
# Run inference on validation set
python ingest.py evaluate \
    --adapter-path finetune_output/final_adapter \
    --output-dir finetune_output \
    --num-samples 10
```

### Output

After fine-tuning, the LoRA adapter is saved to:
```
finetune_output/
├── final_adapter/
│   ├── adapter_config.json
│   ├── adapter_model.bin
│   └── tokenizer files...
├── train.jsonl
├── val.jsonl
└── checkpoint-*/
```

---

## Running the Application

### Start the Ollama Server (if not already running)

```powershell
# Ollama typically runs automatically on Windows
# On Linux/macOS, start it manually:
ollama serve
```

### Run the Web UI

```powershell
# Activate virtual environment
venv\Scripts\Activate.ps1

# Start the Gradio application
python main.py
```

You should see output like:
```
Starting UTcoder on http://0.0.0.0:7860  (share=False)
```

### Access the Application

Open your browser and navigate to:
- **Local**: http://localhost:7860
- **Network**: http://<your-ip>:7860

### Using the Web Interface

1. **Upload Source File**: Drag and drop or click to upload a Python, Java, C#, or JavaScript file
2. **View Language Info**: The detected language and test framework are displayed
3. **Generate Tests**: Click "⚡ Generate Tests"
4. **Monitor Progress**: Watch the status bar for progress updates
5. **Download Results**: Click the download button to save the generated test file

### Configuration Changes

To change server settings, edit `config.json`:
- Change `server.port` for a different port
- Set `server.host` to `"127.0.0.1"` to restrict to localhost access
- Set `server.share` to `true` for a temporary public link

---

## Troubleshooting

### Issue: "Connection refused" or "Cannot connect to Ollama"

**Solution**:
1. Verify Ollama is running: `ollama serve` (on Linux/macOS)
2. Check if Ollama is listening on port 11434:
   ```powershell
   Test-NetConnection -ComputerName localhost -Port 11434
   ```
3. Restart Ollama
4. Check firewall settings

### Issue: "Model not found" error

**Solution**:
```powershell
# Pull the required model
ollama pull deepseek-coder-v2:16b

# Pull the embedding model
ollama pull nomic-embed-text

# Verify they're installed
ollama list
```

### Issue: Out of memory (OOM) errors

**Solutions**:
- Use a smaller model: `ollama pull dolphin-mixtral` or `ollama pull dolphin-2.6-phi`
- Reduce batch size in config
- Use 4-bit quantization during fine-tuning: `--4bit` flag
- Close other applications to free up RAM

### Issue: Very slow inference

**Causes and Solutions**:
- **No GPU**: Inference on CPU is slow. Install CUDA for GPU acceleration.
- **Model too large**: Switch to a smaller model.
- **ChromaDB slow**: Normal on first run or with large collections.
- **Ollama not optimized**: Check Ollama documentation for GPU setup.

### Issue: Fine-tuning runs out of memory

**Solutions**:
1. **Use QLoRA** (4-bit quantization):
   ```powershell
   --4bit --max-seq-len 1024 --batch-size 1 --grad-accum 8
   ```

2. **Reduce batch size and sequence length**:
   ```powershell
   --batch-size 1 --grad-accum 8 --max-seq-len 1024
   ```

3. **Use a smaller base model**:
   ```powershell
   --base-model "deepseek-coder-6.7b"
   ```

### Issue: "ModuleNotFoundError" when running training

**Solution**:
```powershell
pip install transformers peft torch datasets trl accelerate bitsandbytes
```

### Issue: CUDA not detected during training

**Solution**:
1. Verify CUDA is installed: `nvidia-smi`
2. Reinstall PyTorch with CUDA support:
   ```powershell
   pip uninstall torch torchvision torchaudio
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
   ```
3. For CPU-only training, remove `--4bit`, `--bf16`, `--fp16` flags

### Issue: "HFValidationError: Repo id must use alphanumeric chars..." with model IDs containing `:

**Cause**: You're using an **Ollama model ID** (e.g., `deepseek-coder-v2:16b`) for fine-tuning, but training requires a **HuggingFace model ID**.

**Solution**: Replace the Ollama model ID with a valid HuggingFace model ID:

❌ **Wrong** (Ollama format):
```powershell
--base-model deepseek-coder-v2:16b
```

✅ **Correct** (HuggingFace format):
```powershell
--base-model deepseek-ai/deepseek-coder-6.7b-base
```

**Difference**:
- **Ollama IDs** (for inference): `model-name:size` (e.g., `deepseek-coder-v2:16b`)
- **HuggingFace IDs** (for fine-tuning): `organization/model-name` (e.g., `deepseek-ai/deepseek-coder-6.7b-base`)

See the **Recommended HuggingFace Models** table in the [Training section](#step-3-fine-tune-the-model) for valid model IDs.

### Issue: "ValueError: Cannot use chat template functions because tokenizer.chat_template is not set"

**Cause**: The base model you're using is a **base model** (not instruction-tuned) and doesn't have a chat template defined. Chat templates are primarily available on instruction-tuned models.

**Solution**: Use an **instruction-tuned model** instead of a base model:

❌ **Wrong** (Base model, no chat template):
```powershell
--base-model deepseek-ai/deepseek-coder-6.7b-base
```

✅ **Correct** (Instruction-tuned model with chat template):
```powershell
--base-model deepseek-ai/deepseek-coder-6.7b-instruct
```

**Recommended instruction-tuned models**:
| Model | HuggingFace ID |
|-------|----------------|
| Deepseek Coder Instruct | `deepseek-ai/deepseek-coder-6.7b-instruct` |
| CodeLLaMA Instruct | `meta-llama/CodeLlama-7b-Instruct-hf` |
| Phi-2 | `microsoft/phi-2` |
| Mistral Instruct | `mistralai/Mistral-7B-Instruct-v0.1` |

**Note**: UTcoder's code includes a fallback formatter for models without chat templates, but using instruction-tuned models gives better fine-tuning results.

---

## Development Notes

### Project Structure

```
UTcoder/
├── main.py                      # Entry point for web UI
├── config.json                  # Configuration file
├── requirements.txt             # Python dependencies
├── core/
│   ├── __init__.py
│   ├── config.py               # Config loader
│   ├── code_parser.py          # Code parsing and chunking
│   ├── generator.py            # Main generation pipeline
│   ├── llm.py                  # LLM management (Ollama)
│   ├── vectorstore.py          # ChromaDB management
│   └── dataset/
│       ├── ingest.py           # Fine-tuning pipeline
│       ├── CodeRM_UnitTest.csv
│       └── CodeRM_UnitTest (test).csv
├── ui/
│   ├── __init__.py
│   └── app.py                  # Gradio UI
├── finetune_output/            # Fine-tuned models
└── chroma_db/                  # Vector store
```

### Key Modules

- **`core/config.py`**: Loads and caches configuration from `config.json`
- **`core/code_parser.py`**: Detects language, parses code into chunks
- **`core/generator.py`**: Orchestrates indexing, RAG, and LLM streaming
- **`core/llm.py`**: ChatOllama wrapper
- **`core/vectorstore.py`**: ChromaDB interface with OllamaEmbeddings
- **`ui/app.py`**: Gradio web interface
- **`core/dataset/ingest.py`**: Fine-tuning pipeline with CLI

### Adding a New Language

1. **Update `config.json`**:
   ```json
   "languages": {
       "go": {
           "test_framework": "testing",
           "file_suffix": "_test.go",
           "display": "Go"
       }
   }
   ```

2. **Update `core/code_parser.py`**:
   - Add language detection logic
   - Add a parser for the new language

3. **Update `core/generator.py`**:
   - Add language-specific prompting instructions to `_LANG_INSTRUCTIONS`

### Debugging

Enable debug output:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Or set debug mode in config:
```json
"server": {
    "debug": true
}
```

### Running Tests

```powershell
# If test files exist, run with pytest
pytest
```

---

## Performance Optimization

### For Inference

1. **GPU Acceleration**: Ensure CUDA is properly set up
2. **Model Size**: Use smaller models (6.7B) if needed
3. **Batch Processing**: Pre-process multiple files before submission
4. **ChromaDB Indexing**: Embeddings are cached; first generation is slower

### For Training

1. **Gradient Accumulation**: Use `--grad-accum 4` or higher with small batch sizes
2. **Mixed Precision**: Use `--bf16` for faster training on supported GPUs
3. **LoRA Rank**: Increase `--lora-r` for better quality (16, 32, 64)
4. **Learning Rate**: Default `2e-4` works well; adjust based on loss curves

---

## Additional Resources

- **LangChain Docs**: https://python.langchain.com
- **Ollama**: https://ollama.ai
- **ChromaDB**: https://www.trychroma.com
- **Gradio**: https://gradio.app
- **Hugging Face**: https://huggingface.co

---

## Support

For issues, questions, or contributions, please refer to the project repository or contact the development team.

Happy testing! 🧪

