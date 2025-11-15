# gradio_app.py
"""
Gradio UI that unifies translate.py, solution.py, generate.py
Supported languages (UI labels) -> backend codes:
  - English -> "en"
  - Hindi   -> "hi"
  - Odia    -> "or"

Usage:
  - Place this file in the same folder as translate.py, solution.py, generate.py
  - Ensure required env vars (GENAI_API_KEY / GEMINI_API_KEY etc.) are set
  - Run: python gradio_app.py
"""

import os
import tempfile
import shutil
import traceback
from pathlib import Path

import gradio as gr

# --- Language mapping (Option B) ---
LANG_DISPLAY_TO_CODE = {
    "English": "en",
    "Hindi": "hi",
    "Odia": "or",
}

# --- Attempt to import backend modules ---
# If import fails, we still keep UI operational and show errors on use.
translate_module = None
solution_module = None
generate_module = None

try:
    import translate as translate_module  # your translate.py
except Exception as e:
    translate_module = None
    print("Warning: failed to import translate.py:", e)

try:
    import solution as solution_module  # your solution.py
except Exception as e:
    solution_module = None
    print("Warning: failed to import solution.py:", e)

try:
    import generate as generate_module  # your generate.py
except Exception as e:
    generate_module = None
    print("Warning: failed to import generate.py:", e)


# --- Helpers ---
def save_uploaded_file_to_temp(uploaded_file):
    """
    uploaded_file is a tuple from Gradio (tempfile path, original name) or a file-like
    Returns path on disk to saved file.
    """
    if uploaded_file is None:
        return None
    # Gradio file component returns a dict-like or tuple depending on version.
    # We'll handle common patterns:
    if isinstance(uploaded_file, str) and os.path.isfile(uploaded_file):
        return uploaded_file
    try:
        # If it's a dict-like (name, temp_path)
        if hasattr(uploaded_file, "name") and os.path.isfile(uploaded_file.name):
            return uploaded_file.name
    except Exception:
        pass

    # Else, try to write bytes to a temp file
    try:
        file_info = uploaded_file
        # file_info can be a tuple (temp_path, original_name)
        if isinstance(file_info, (tuple, list)) and len(file_info) >= 2:
            tmp_path = file_info[0]
            if os.path.isfile(tmp_path):
                return tmp_path
        # else attempt to read .file or .read
        possible = getattr(uploaded_file, "file", None) or getattr(uploaded_file, "fp", None)
        if possible:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp.write(possible.read())
            tmp.close()
            return tmp.name
    except Exception:
        pass

    # fallback: save raw bytes
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        if hasattr(uploaded_file, "read"):
            data = uploaded_file.read()
        else:
            data = uploaded_file
        tmp.write(data)
        tmp.close()
        return tmp.name
    except Exception as e:
        print("Failed to save uploaded file:", e)
        return None


def file_details(path):
    if not path or not os.path.isfile(path):
        return {}
    st = os.stat(path)
    return {"name": os.path.basename(path), "size_bytes": st.st_size, "path": path}


# --- Wrappers for backends (best-effort) ---


def run_translate_pipeline(input_pdf_path: str, target_lang_code: str):
    """
    Run the real translation pipeline from translate.py (extract → translate → rebuild).
    Returns the generated PDF path (or translated JSON) and an optional error message.
    """
    if not translate_module:
        return None, "translate.py not available (import failed)."

    if not hasattr(translate_module, "PDFProcessingPipeline"):
        return None, "translate.py does not expose PDFProcessingPipeline."

    try:
        pipeline = translate_module.PDFProcessingPipeline()
        result = pipeline.run_complete_pipeline(input_pdf_path)
        generated = result.get("generated_pdfs") or []
        if generated:
            return str(generated[0]), None
        translations = result.get("translations") or []
        if translations:
            return str(translations[0]), "Translated JSON created (no PDF renderer available)."
        return None, "Pipeline completed but no output files were produced."
    except Exception as e:
        tb = traceback.format_exc()
        return None, f"Exception during translate pipeline: {e}\n{tb}"


def run_solution_pipeline(input_pdf_path: str, target_lang_code: str):
    """
    Run the solution pipeline. We look for extraction + solving functions observed in solution.py: extract_pdf and solve_pages.
    We'll attempt to call them and then see if any PDF or output is created.
    """
    if not solution_module:
        return None, "solution.py not available (import failed)."

    try:
        base_tmp = tempfile.mkdtemp(prefix="solution_out_")
        # Try extract_pdf -> returns pages (list)
        pages = None
        if hasattr(solution_module, "extract_pdf"):
            try:
                pages = solution_module.extract_pdf(input_pdf_path, output_json=os.path.join(base_tmp, "extracted.json"),
                                                    output_image_folder=os.path.join(base_tmp, "images"))
            except TypeError:
                # maybe extract_pdf signature is different
                pages = solution_module.extract_pdf(input_pdf_path)
        elif hasattr(solution_module, "PDFToJSONConverter"):
            conv = solution_module.PDFToJSONConverter()
            if hasattr(conv, "convert_pdf_to_json"):
                conv.convert_pdf_to_json(input_pdf_path, os.path.join(base_tmp, "extracted.json"))
        else:
            # can't extract; bail with helpful note
            return None, "Could not find an extraction function in solution.py (expected extract_pdf or similar)."

        # Now call solve_pages if available
        results = None
        if hasattr(solution_module, "solve_pages"):
            try:
                results = solution_module.solve_pages(pages)
            except Exception:
                # maybe solve_pages expects different input; try calling a high-level 'solve' function
                try:
                    results = solution_module.solve_pages(pages)
                except Exception as e:
                    pass

        # Some scripts may provide a function to render a solved PDF. Try common names:
        solved_pdf = None
        possible_renderers = ["render_solved_pdf", "write_solutions_pdf", "generate_solved_pdf", "render_pdf_from_json"]
        for name in possible_renderers:
            if hasattr(solution_module, name):
                out_pdf = os.path.join(base_tmp, "solved.pdf")
                try:
                    getattr(solution_module, name)(results or pages, out_pdf, target_lang_code)
                    solved_pdf = out_pdf
                    break
                except Exception:
                    # try alternate parameter orders (out, lang)
                    try:
                        getattr(solution_module, name)(out_pdf, results or pages, target_lang_code)
                        solved_pdf = out_pdf
                        break
                    except Exception:
                        pass

        # If no solved PDF renderer, maybe the module returns a JSON with solutions. Return that.
        if solved_pdf and os.path.exists(solved_pdf):
            return solved_pdf, None

        # Try to write the 'results' into a simple text file and return it
        out_txt = os.path.join(base_tmp, "solutions.txt")
        try:
            with open(out_txt, "w", encoding="utf-8") as f:
                f.write("=== SOLUTION RESULTS ===\n\n")
                import json
                f.write(json.dumps(results, ensure_ascii=False, indent=2))
            return out_txt, None
        except Exception as e:
            return None, f"Pipeline produced results but couldn't write them to disk: {e}"

    except Exception as e:
        tb = traceback.format_exc()
        return None, f"Exception during solution pipeline: {e}\n{tb}"


def run_generate_mcqs(input_pdf_path: str, n:int, target_lang_code: str):
    """
    Try to call generate.generate_mcqs(pdf_path, n, language, topic=None)
    We observed generate.py defines generate_mcqs and generate_topic_mcqs.
    """
    if not generate_module:
        return None, "generate.py not available (import failed)."

    try:
        # Map code to the strings generate expects. The snippet's ensure_supported_language expects 'hindi'/'odia'
        code_map = {"en": "english", "hi": "hindi", "or": "odia"}
        lang_for_generate = code_map.get(target_lang_code, target_lang_code)

        if hasattr(generate_module, "generate_mcqs"):
            text = generate_module.generate_mcqs(input_pdf_path, n, lang_for_generate)
            # Save to a text file and also try to render PDF via a helper if available
            base_tmp = tempfile.mkdtemp(prefix="mcq_out_")
            txt_path = os.path.join(base_tmp, f"mcqs_{lang_for_generate}.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text or "")
            # If there's a helper to write PDF:
            if hasattr(generate_module, "write_mcq_pdf") or hasattr(generate_module, "mcq_text_to_pdf"):
                renderer = getattr(generate_module, "write_mcq_pdf", None) or getattr(generate_module, "mcq_text_to_pdf", None)
                pdf_path = os.path.join(base_tmp, f"mcqs_{lang_for_generate}.pdf")
                try:
                    renderer(text, pdf_path)
                    return pdf_path, None
                except Exception:
                    pass
            return txt_path, None

        elif hasattr(generate_module, "generate_topic_mcqs"):
            text = generate_module.generate_topic_mcqs(None, n, lang_for_generate)
            base_tmp = tempfile.mkdtemp(prefix="mcq_out_")
            txt_path = os.path.join(base_tmp, f"mcqs_{lang_for_generate}.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text or "")
            return txt_path, None

        else:
            return None, "generate.py does not expose generate_mcqs or generate_topic_mcqs."

    except Exception as e:
        tb = traceback.format_exc()
        return None, f"Exception during MCQ generation: {e}\n{tb}"


# --- Gradio UI Callbacks ---


def ui_show_file_info(uploaded):
    path = save_uploaded_file_to_temp(uploaded)
    if not path:
        return "No file uploaded.", {}
    info = file_details(path)
    size_kb = info["size_bytes"] // 1024
    return f"Uploaded: {info['name']} — {size_kb} KB", info


def ui_translate(uploaded, language_display):
    path = save_uploaded_file_to_temp(uploaded)
    if not path:
        return "Error: no file uploaded.", None
    lang_code = LANG_DISPLAY_TO_CODE.get(language_display, "en")
    out_path, error = run_translate_pipeline(path, lang_code)
    if error:
        return f"Translation failed: {error}", None
    label = os.path.basename(out_path)
    # Provide either file or text content
    return f"Translation complete: {label}", out_path


def ui_solve(uploaded, language_display):
    path = save_uploaded_file_to_temp(uploaded)
    if not path:
        return "Error: no file uploaded.", None
    lang_code = LANG_DISPLAY_TO_CODE.get(language_display, "en")
    out_path, error = run_solution_pipeline(path, lang_code)
    if error:
        return f"Solve failed: {error}", None
    label = os.path.basename(out_path)
    return f"Solving complete: {label}", out_path


def ui_generate_mcqs(uploaded, count, language_display):
    path = save_uploaded_file_to_temp(uploaded)
    if not path:
        return "Error: no file uploaded.", None, None
    lang_code = LANG_DISPLAY_TO_CODE.get(language_display, "en")
    out_path, error = run_generate_mcqs(path, int(count), lang_code)
    if error:
        return f"MCQ generation failed: {error}", None, None
    # Also read a preview (if text)
    preview = ""
    try:
        if out_path and os.path.isfile(out_path) and out_path.lower().endswith(".txt"):
            with open(out_path, "r", encoding="utf-8") as f:
                preview = f.read(4000)
        elif out_path and os.path.isfile(out_path) and out_path.lower().endswith(".pdf"):
            preview = "MCQs written to PDF (download available)."
        else:
            preview = f"Generated file: {out_path}"
    except Exception as e:
        preview = f"Generated file: {out_path} (couldn't read preview: {e})"
    return "MCQ generation complete.", preview, out_path


# --- Build Gradio UI ---
def build_ui():
    with gr.Blocks(title="Unified AI PDF Toolkit (Gradio)", css=".gradio-container {max-width: 1100px;}") as demo:
        gr.Markdown("# Unified AI PDF Toolkit (Translate | Solve | Generate MCQs)\nUpload one PDF and use any module. Languages: English, Hindi, Odia.")
        with gr.Row():
            uploader = gr.File(label="Upload PDF (shared across modules)", file_types=['.pdf'], interactive=True)
            file_info = gr.Textbox(label="File info", interactive=False)
        # Update file info when a file is uploaded
        uploader.change(fn=ui_show_file_info, inputs=[uploader], outputs=[file_info, gr.State()], show_progress=False)

        with gr.Tabs():
            with gr.TabItem("Translate"):
                gr.Markdown("Translate the uploaded PDF into the selected language.")
                lang_translate = gr.Dropdown(list(LANG_DISPLAY_TO_CODE.keys()), value="English", label="Target language")
                translate_btn = gr.Button("Translate")
                translate_status = gr.Textbox(label="Status", interactive=False)
                translate_download = gr.File(label="Download translated output", interactive=False)
                def _translate_exec(file, lang):
                    msg, out = ui_translate(file, lang)
                    # gr.File expects a path; if out is a JSON/text, still pass it as file
                    return msg, out
                translate_btn.click(fn=_translate_exec, inputs=[uploader, lang_translate], outputs=[translate_status, translate_download])

            with gr.TabItem("Solve"):
                gr.Markdown("Extract + Solve questions from uploaded PDF, then translate solutions.")
                lang_solve = gr.Dropdown(list(LANG_DISPLAY_TO_CODE.keys()), value="English", label="Output language for solutions")
                solve_btn = gr.Button("Solve")
                solve_status = gr.Textbox(label="Status", interactive=False)
                solve_download = gr.File(label="Download solved output", interactive=False)
                solve_btn.click(fn=lambda f, l: ui_solve(f, l), inputs=[uploader, lang_solve], outputs=[solve_status, solve_download])

            with gr.TabItem("Generate MCQs"):
                gr.Markdown("Generate MCQs from the uploaded PDF.")
                mcq_count = gr.Number(value=10, precision=0, label="Number of MCQs")
                mcq_lang = gr.Dropdown(list(LANG_DISPLAY_TO_CODE.keys()), value="English", label="Target language")
                mcq_btn = gr.Button("Generate MCQs")
                mcq_status = gr.Textbox(label="Status", interactive=False)
                mcq_preview = gr.Textbox(label="Preview / Generated Text", interactive=False, lines=12)
                mcq_download = gr.File(label="Download MCQ output", interactive=False)
                mcq_btn.click(fn=lambda f, n, l: ui_generate_mcqs(f, n, l), inputs=[uploader, mcq_count, mcq_lang], outputs=[mcq_status, mcq_preview, mcq_download])

        gr.Markdown("### Notes\n- The app calls your backend scripts by name. If a backend function has a non-standard name, please tell me the exact function that produces the final PDF so I can call it directly.\n- Ensure GEMINI/GENAI keys and other env vars are set for backend modules to work.")
    return demo


if __name__ == "__main__":
    demo = build_ui()

    # --- AUTO-DETECTION FOR GRADIO VERSION ---
    try:
        import gradio as gr
        ver = gr.__version__
        print(f"[INFO] Detected Gradio version: {ver}")

        # Convert version string "4.19.2" -> major=4
        major_ver = int(ver.split(".")[0])

        if major_ver >= 4:
            # Newer gradio (4.x and up)
            print("[INFO] Using Gradio 4.x launcher")
            demo.queue().launch(server_name="127.0.0.1", share=False)

        else:
            # Older gradio (3.x or earlier)
            print("[INFO] Using Gradio 3.x launcher (no queue with arguments)")
            demo.queue().launch(server_name="127.0.0.1", share=False)

    except Exception as e:
        # Fallback: safest possible launcher
        print("[WARN] Auto-detection failed, using fallback launcher:", e)
        demo.queue().launch(server_name="127.0.0.1", share=False)


