"""
ui/app.py
---------
Gradio-based web interface for UTcoder.

Features:
- Drag-and-drop or click-to-upload source file
- Auto-detected language badge
- Streaming LLM output rendered as a code block
- One-click download of the generated test file
- Live status bar with model name and ChromaDB state
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import gradio as gr

from core.code_parser import LANGUAGE_ICONS, detect_language
from core.config import get_config
from core.generator import generate_unit_tests
from core.llm import get_model_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lang_badge(file_name: str) -> str:
    lang = detect_language(file_name)
    cfg  = get_config().get("languages", {}).get(lang, {})
    icon = LANGUAGE_ICONS.get(lang, "📄")
    display = cfg.get("display", lang.title())
    framework = cfg.get("test_framework", "")
    return f"{icon} **{display}**  ·  framework: `{framework}`"


def _output_filename(original: str) -> str:
    lang = detect_language(original)
    cfg  = get_config().get("languages", {}).get(lang, {})
    suffix = cfg.get("file_suffix", "_test" + Path(original).suffix)
    stem = Path(original).stem
    return f"{stem}{suffix}"


def _write_temp(content: str, filename: str) -> str:
    """Write content to a named temp file and return its path."""
    suffix = Path(filename).suffix
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=Path(filename).stem + "_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def on_file_upload(file_obj):
    """React to file upload: detect language and show info badge."""
    if file_obj is None:
        return gr.update(value="", visible=False), gr.update(interactive=False)
    badge = _lang_badge(Path(file_obj.name).name)
    return gr.update(value=badge, visible=True), gr.update(interactive=True)


def on_generate(file_obj):
    """
    Streaming generator that:
    1. Reads the uploaded file
    2. Calls generate_unit_tests() which indexes to ChromaDB and streams LLM
    3. Yields (accumulated_code, status_text, download_update) progressively
    """
    if file_obj is None:
        yield "", "⚠️ Please upload a source file first.", gr.update(visible=False)
        return

    file_path = Path(file_obj.name)
    file_name = file_path.name

    try:
        source_code = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        yield "", f"❌ Could not read file: {exc}", gr.update(visible=False)
        return

    lang = detect_language(file_name)
    cfg  = get_config().get("languages", {}).get(lang, {})
    framework = cfg.get("test_framework", "")
    model = get_model_name()

    accumulated = ""
    out_filename = _output_filename(file_name)

    yield accumulated, f"⚙️ Indexing `{file_name}` into ChromaDB…", gr.update(visible=False)

    try:
        for token in generate_unit_tests(file_name, source_code):
            accumulated += token
            yield (
                accumulated,
                f"🤖 Generating `{out_filename}` with **{model}** ({framework})…",
                gr.update(visible=False),
            )
    except Exception as exc:
        logger.exception("Generation failed")
        yield accumulated, f"❌ Generation error: {exc}", gr.update(visible=False)
        return

    # Write temp file for download
    tmp_path = _write_temp(accumulated, out_filename)
    yield (
        accumulated,
        f"✅ Done! Generated **{out_filename}** · {len(accumulated.splitlines())} lines",
        gr.update(visible=True, value=tmp_path, label=f"⬇ Download  {out_filename}"),
    )


def on_clear():
    return "", "", gr.update(visible=False), gr.update(visible=False), gr.update(interactive=False)


# ---------------------------------------------------------------------------
# Custom CSS — dark premium theme
# ---------------------------------------------------------------------------

CUSTOM_CSS = """
/* ── Google Font ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Root variables ── */
:root {
    --bg-root:    #0b0d17;
    --bg-panel:   #111320;
    --bg-card:    #161929;
    --bg-input:   #1c2035;
    --border:     #252a45;
    --border-glow:#4f46e5;
    --primary:    #6366f1;
    --primary-h:  #818cf8;
    --accent:     #06b6d4;
    --success:    #10b981;
    --warning:    #f59e0b;
    --danger:     #ef4444;
    --text-1:     #e2e8f0;
    --text-2:     #94a3b8;
    --text-3:     #64748b;
    --radius:     12px;
    --shadow:     0 4px 24px rgba(0,0,0,.5);
}

/* ── Global ── */
body, .gradio-container {
    background: var(--bg-root) !important;
    font-family: 'Inter', sans-serif !important;
    color: var(--text-1) !important;
}

/* ── Header gradient ── */
#utcoder-header {
    background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 50%, #0c1a2e 100%);
    border-bottom: 1px solid var(--border);
    padding: 28px 36px 20px;
    border-radius: var(--radius) var(--radius) 0 0;
    margin-bottom: 4px;
}
#utcoder-header h1 {
    font-size: 2rem;
    font-weight: 700;
    background: linear-gradient(90deg, #818cf8, #06b6d4);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0 0 4px 0;
}
#utcoder-header p {
    color: var(--text-2);
    font-size: 0.9rem;
    margin: 0;
}

/* ── Panels ── */
.panel-card {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    box-shadow: var(--shadow);
}

/* ── Upload area ── */
#upload-box .wrap {
    border: 2px dashed var(--border) !important;
    border-radius: var(--radius) !important;
    background: var(--bg-input) !important;
    transition: border-color .2s, background .2s;
    min-height: 140px !important;
}
#upload-box .wrap:hover {
    border-color: var(--primary) !important;
    background: rgba(99,102,241,.06) !important;
}

/* ── Buttons ── */
#btn-generate {
    background: linear-gradient(135deg, #4f46e5, #06b6d4) !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 1rem !important;
    letter-spacing: .03em;
    transition: opacity .2s, transform .1s !important;
    color: #fff !important;
}
#btn-generate:hover { opacity: .9; transform: translateY(-1px); }
#btn-generate:active { transform: translateY(0); }

#btn-clear {
    background: transparent !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text-2) !important;
    font-weight: 500 !important;
    transition: border-color .2s, color .2s !important;
}
#btn-clear:hover {
    border-color: var(--primary-h) !important;
    color: var(--primary-h) !important;
}

/* ── Download button ── */
#btn-download {
    background: linear-gradient(135deg, #059669, #10b981) !important;
    border: none !important;
    border-radius: 8px !important;
    color: #fff !important;
    font-weight: 600 !important;
    transition: opacity .2s !important;
}
#btn-download:hover { opacity: .85; }

/* ── Status bar ── */
#status-bar {
    font-size: 0.82rem !important;
    color: var(--text-2) !important;
    background: var(--bg-panel) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    padding: 6px 14px !important;
}

/* ── Language badge ── */
#lang-badge {
    background: rgba(99,102,241,.12) !important;
    border: 1px solid rgba(99,102,241,.35) !important;
    border-radius: 8px !important;
    padding: 6px 14px !important;
    font-size: 0.85rem !important;
    color: var(--primary-h) !important;
}

/* ── Code output ── */
#code-output {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.83rem !important;
    background: #090c18 !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    min-height: 420px !important;
}
#code-output textarea {
    background: transparent !important;
    color: #c9d1d9 !important;
    font-family: 'JetBrains Mono', monospace !important;
}

/* ── Info tiles ── */
.info-tile {
    background: var(--bg-input) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 12px 16px !important;
}

/* ── Labels ── */
label span, .label-wrap span {
    color: var(--text-2) !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: .06em;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-root); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--primary); }
"""


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> gr.Blocks:
    cfg   = get_config()
    model = get_model_name()
    chroma_dir = cfg["vectorstore"]["chroma_dir"]

    _theme = gr.themes.Base(
        primary_hue=gr.themes.colors.indigo,
        neutral_hue=gr.themes.colors.slate,
        font=["Inter", "sans-serif"],
    )

    with gr.Blocks(title="UTcoder — AI Unit Test Generator") as demo:

        # ── Header ────────────────────────────────────────────────────────
        gr.HTML(f"""
        <div id="utcoder-header">
            <h1>🧪 UTcoder</h1>
            <p>AI-powered unit test generator · <strong>{model}</strong> via Ollama · ChromaDB RAG</p>
        </div>
        """)

        # ── Main layout ────────────────────────────────────────────────────
        with gr.Row(equal_height=False):

            # ── Left column: inputs ──────────────────────────────────────
            with gr.Column(scale=1, min_width=320):

                gr.Markdown("### 📂 Source File", elem_classes="panel-label")

                file_input = gr.File(
                    label="Upload source file",
                    file_types=[".py", ".java", ".cs", ".js", ".jsx", ".mjs"],
                    elem_id="upload-box",
                )

                lang_badge = gr.Markdown(
                    value="",
                    visible=False,
                    elem_id="lang-badge",
                )

                with gr.Row():
                    btn_generate = gr.Button(
                        "⚡ Generate Tests",
                        variant="primary",
                        interactive=False,
                        elem_id="btn-generate",
                        scale=3,
                    )
                    btn_clear = gr.Button(
                        "✕ Clear",
                        variant="secondary",
                        elem_id="btn-clear",
                        scale=1,
                    )

                # Model info tiles
                gr.HTML(f"""
                <div style="margin-top:16px; display:flex; flex-direction:column; gap:8px;">
                  <div class="info-tile">
                    <span style="color:#64748b;font-size:.72rem;text-transform:uppercase;letter-spacing:.07em">MODEL</span><br>
                    <span style="color:#818cf8;font-weight:600;font-size:.9rem">{model}</span>
                  </div>
                  <div class="info-tile">
                    <span style="color:#64748b;font-size:.72rem;text-transform:uppercase;letter-spacing:.07em">VECTOR STORE</span><br>
                    <span style="color:#06b6d4;font-weight:600;font-size:.9rem">ChromaDB · {chroma_dir}</span>
                  </div>
                  <div class="info-tile">
                    <span style="color:#64748b;font-size:.72rem;text-transform:uppercase;letter-spacing:.07em">EMBEDDINGS</span><br>
                    <span style="color:#10b981;font-weight:600;font-size:.9rem">{model}</span>
                  </div>
                </div>
                """)

            # ── Right column: output ─────────────────────────────────────
            with gr.Column(scale=2):

                gr.Markdown("### 🧪 Generated Unit Tests", elem_classes="panel-label")

                code_output = gr.Code(
                    label="Test file output",
                    language="python",          # updated dynamically in JS (cosmetic)
                    interactive=False,
                    lines=28,
                    elem_id="code-output",
                )

                with gr.Row():
                    status_bar = gr.Markdown(
                        value=f"Ready · model `{model}` · ChromaDB at `{chroma_dir}`",
                        elem_id="status-bar",
                    )

                btn_download = gr.File(
                    label="⬇ Download Test File",
                    visible=False,
                    elem_id="btn-download",
                )

        # ── Event wiring ───────────────────────────────────────────────────

        file_input.change(
            fn=on_file_upload,
            inputs=[file_input],
            outputs=[lang_badge, btn_generate],
        )

        btn_generate.click(
            fn=on_generate,
            inputs=[file_input],
            outputs=[code_output, status_bar, btn_download],
        )

        btn_clear.click(
            fn=on_clear,
            inputs=[],
            outputs=[code_output, status_bar, btn_download, lang_badge, btn_generate],
        )

    return demo, _theme, CUSTOM_CSS
