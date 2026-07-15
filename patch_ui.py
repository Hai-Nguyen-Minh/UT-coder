import re

with open("ui/app.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Remove old imports
content = re.sub(r'from core\.compiler import compile_check, quick_assessment\n', '', content)
content = re.sub(r'from core\.coverager import analyse_coverage, coverage_summary\n', '', content)

# 2. Replace HTML builders with Visual Coverage
new_html_fn = '''import html

def generate_coverage_html(source_code: str, missing_lines: list[int], coverage_pct: float) -> str:
    """Build an HTML block to visually show coverage."""
    if not source_code:
        return "<div style='color:var(--text-3);padding:20px;text-align:center;'>No code available for coverage view.</div>"
        
    color = "var(--success)" if coverage_pct >= 80 else ("var(--warning)" if coverage_pct >= 50 else "var(--danger)")
    
    out_html = f"""
    <div style="margin-bottom:16px;">
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:8px;">
        <span style="font-size:2.5rem;font-weight:700;color:{color};">{coverage_pct:.0f}%</span>
        <div style="flex:1;height:10px;background:rgba(0,0,0,0.06);border-radius:5px;overflow:hidden;">
          <div style="width:{coverage_pct}%;height:100%;background:linear-gradient(90deg,{color},var(--accent));border-radius:5px;transition:width 0.5s;"></div>
        </div>
      </div>
    </div>
    """
    
    out_html += "<div style='background: #1e1e1e; padding: 15px; border-radius: 8px; font-family: monospace; overflow-x: auto; line-height: 1.5; font-size: 14px;'>"
    
    lines = source_code.split("\\n")
    for i, line in enumerate(lines, 1):
        is_missing = i in missing_lines
        bg_color = "#3a1c1c" if is_missing else "transparent"
        text_color = "#ffcccc" if is_missing else "#d4d4d4"
        line_num_color = "#fca5a5" if is_missing else "#666666"
        
        escaped_line = html.escape(line)
        if not escaped_line.strip():
            escaped_line = " "
            
        out_html += f"<div style='background: {bg_color}; color: {text_color}; white-space: pre; padding: 0 4px;'><span style='color: {line_num_color}; width: 35px; display: inline-block; user-select: none;'>{i}</span>{escaped_line}</div>"
        
    out_html += "</div>"
    return out_html
'''
content = re.sub(r'def _build_compile_check_html\(.*?(?=\n# -+\n# Event handlers)', new_html_fn + '\n', content, flags=re.DOTALL)

# 3. Update on_generate to accept target_cov and output visual HTML
on_generate_old = r'def on_generate\(file_obj, use_reflection=False\):.*?yield \((.*?)\)\s*return'
def repl_on_generate(m):
    body = m.group(0)
    # Update signature
    body = body.replace('def on_generate(file_obj, use_reflection=False):', 'def on_generate(file_obj, use_reflection=False, target_cov=80.0):')
    
    # 4 yields need to add an empty string for the new visual_coverage_state output
    body = body.replace('gr.update(visible=False),\n        )', 'gr.update(visible=False),\n            "",\n        )')
    
    # modify the reflection generation loop to unpack 3 items and pass target_cov
    body = body.replace('for status_msg, code_so_far in generate_with_reflection(file_name, source_code):', 
                        'for status_msg, code_so_far, result_dict in generate_with_reflection(file_name, source_code, target_coverage=target_cov):')
    
    # Final yield
    final_yield = """    final_cov_html = ""
    if use_reflection and 'result_dict' in locals() and result_dict:
        final_cov_html = generate_coverage_html(source_code, result_dict.get('missing_lines', []), result_dict.get('coverage') or 0.0)

    yield (
        gr.update(value=cleaned, language=file_lang, label="Generated Test File Output"),
        status_text,
        cleaned,
        gr.update(visible=True, value=tmp_path, label=f"⬇ Download  {out_filename}"),
        final_cov_html,
    )"""
    body = re.sub(r'    yield \(\n        gr\.update\(value=cleaned.*?gr\.update\(visible=True, value=tmp_path.*?\),\n    \)', final_yield, body, flags=re.DOTALL)
    
    return body

content = re.sub(r'def on_generate\(file_obj, use_reflection=False\):.*?gr\.update\(visible=True, value=tmp_path.*?\),\n    \)', repl_on_generate, content, flags=re.DOTALL)

# 4. Remove on_compile_check and on_coverage_analysis
content = re.sub(r'def on_compile_check\(.*?def on_clear\(', 'def on_clear(', content, flags=re.DOTALL)

# 5. Update build_ui (tabs, slider, event bindings)
content = content.replace('cb_reflection = gr.Checkbox(', 'with gr.Row():\n                                    cb_reflection = gr.Checkbox(\n')
content = content.replace('label="Enable AI Self-Reflection",\n                                    value=True,\n                                )', 'label="Enable AI Self-Reflection",\n                                        value=True,\n                                    )\n                                    slider_target_cov = gr.Slider(minimum=50, maximum=100, step=1, value=80, label="Target Coverage (%)", interactive=True)')


tabs_old = r'with gr\.Tab\("🔍 Compile Check \(Sandbox\)"\):.*?with gr\.Tab\("📊 Coverage \(Sandbox\)"\):.*?(?=with gr\.Accordion\("Export)'
tabs_new = '''with gr.Tab("📊 Visual Coverage"):
                        visual_coverage_output = gr.HTML(
                            value="<div style='color:var(--text-3);padding:20px;text-align:center;'>No coverage data yet. Enable Self-Reflection and run generation to see coverage.</div>",
                            elem_id="visual-coverage-panel",
                        )
                    '''
content = re.sub(tabs_old, tabs_new, content, flags=re.DOTALL)

# Event bindings updates
content = content.replace('inputs=[file_input, cb_reflection],', 'inputs=[file_input, cb_reflection, slider_target_cov],')
content = content.replace('btn_download_file,\n            ],', 'btn_download_file,\n                visual_coverage_output,\n            ],')

content = re.sub(r'btn_compile_check\.click\(.*?\)\n', '', content, flags=re.DOTALL)
content = re.sub(r'btn_coverage\.click\(.*?\)\n', '', content, flags=re.DOTALL)

# Clear button updates
content = content.replace('btn_compile_check, btn_coverage,\n', '')
content = content.replace('compile_check_output, coverage_output,\n', 'visual_coverage_output,\n')
content = content.replace('btn_compile_check, btn_coverage,', '')
content = content.replace('compile_check_output, coverage_output,', 'visual_coverage_output,')

with open("ui/app.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Patch applied!")
