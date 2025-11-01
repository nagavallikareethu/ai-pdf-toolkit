"""
Unified Gradio Interface for AI PDF Toolkit
Integrates three backend modules: Translation, Solution, and MCQ Generation
"""

import os
import io
import tempfile
import pathlib
import subprocess
import sys
from datetime import datetime
from typing import Tuple, Optional

import gradio as gr
from dotenv import load_dotenv

# Ensure project directory
PROJECT_ROOT = pathlib.Path(__file__).parent.resolve()
os.chdir(PROJECT_ROOT)

# Load environment
load_dotenv()
if os.getenv("GEMINI_API_KEY") and not os.getenv("GENAI_API_KEY"):
    os.environ["GENAI_API_KEY"] = os.getenv("GEMINI_API_KEY")
if os.getenv("GENAI_API_KEY") and not os.getenv("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = os.getenv("GENAI_API_KEY")


# =============================================================================
# Helper Functions
# =============================================================================

def save_uploaded_file(uploaded_file, work_dir: pathlib.Path) -> pathlib.Path:
    """Save uploaded file to working directory"""
    pdf_path = work_dir / f"uploaded_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    
    # Handle binary file type from Gradio (tuple of path and content)
    if isinstance(uploaded_file, tuple):
        # New Gradio format: (temp_path, content)
        if len(uploaded_file) >= 2:
            content = uploaded_file[1]
            with open(pdf_path, "wb") as f:
                f.write(content)
        else:
            # If only path provided, copy from temp
            import shutil
            shutil.copy(uploaded_file[0], pdf_path)
    else:
        # Direct bytes or file path
        if isinstance(uploaded_file, bytes):
            with open(pdf_path, "wb") as f:
                f.write(uploaded_file)
        else:
            # String path
            import shutil
            shutil.copy(uploaded_file, pdf_path)
    
    return pdf_path


def run_translation(pdf_path: str, target_lang: str) -> Tuple[str, Optional[str]]:
    """
    Run translation module
    Returns: (status_message, output_file_path)
    """
    try:
        import translate
        
        # Create output directories
        output_dir = PROJECT_ROOT / "outputs"
        output_dir.mkdir(exist_ok=True)
        translated_dir = output_dir / "translated_jsons"
        translated_dir.mkdir(exist_ok=True)
        
        # Map display name to code
        lang_map = {
            "English": "en", "Telugu": "te", "Hindi": "hi", 
            "Odia": "or", "Tamil": "ta"
        }
        lang_code = lang_map.get(target_lang, "en")
        
        # Step 1: Extract PDF to JSON
        json_output = output_dir / "extracted_pdf.json"
        converter = translate.PDFToJSONConverter()
        
        progress_msg = f"Extracting PDF to JSON...\n"
        data = converter.convert_pdf_to_json_enhanced(
            pdf_path, 
            output_path=str(json_output),
            include_images=True,
            image_handling="metadata"
        )
        progress_msg += f"PDF extraction completed.\n"
        
        # Step 2: Translate
        progress_msg += f"Translating to {target_lang}... This may take a few minutes.\n"
        translator = translate.JSONTranslator()
        translated_json_path = translator.translate_json_file(
            str(json_output), 
            lang_code, 
            target_lang
        )
        
        if not translated_json_path:
            return f"Translation failed. Please check console output.", None
        
        progress_msg += f"Translation completed.\n"
        
        # Step 3: Generate PDF
        progress_msg += f"Rendering translated PDF...\n"
        output_pdf = output_dir / f"translated_{target_lang.lower()}.pdf"
        pdf_gen = translate.PDFGenerator(str(translated_json_path), str(output_pdf))
        pdf_gen.generate_pdf()
        
        if output_pdf.exists():
            progress_msg += f"Translation complete! File saved to: {output_pdf}\n"
            return progress_msg, str(output_pdf)
        else:
            return f"PDF generation failed.", None
            
    except Exception as e:
        import traceback
        error_msg = f"Translation Error:\n{str(e)}\n\n{traceback.format_exc()}"
        return error_msg, None


def run_solution(pdf_path: str, target_lang: str) -> Tuple[str, Optional[str]]:
    """
    Run solution module
    Returns: (status_message, output_file_path)
    """
    try:
        import solution
        
        output_dir = PROJECT_ROOT / "outputs"
        output_dir.mkdir(exist_ok=True)
        
        progress_msg = "Extracting PDF (text + images)...\n"
        pages = solution.extract_pdf(
            pdf_path,
            output_json=str(output_dir / "extracted_data.json"),
            output_image_folder=str(output_dir / "extracted_images")
        )
        progress_msg += "Extraction completed.\n"
        
        progress_msg += "Solving extracted content...\n"
        solved = solution.solve_pages(pages)
        progress_msg += "Solving completed.\n"
        
        progress_msg += f"Translating solutions to {target_lang}...\n"
        translated = solution.translate_items(solved, target_lang)
        progress_msg += "Translation completed.\n"
        
        progress_msg += "Rendering solved PDF...\n"
        output_pdf = output_dir / f"final_solved_{target_lang.lower()}.pdf"
        
        # Run async function with asyncio
        import asyncio
        asyncio.run(solution.render_pdf_from_data(translated, target_lang.lower(), str(output_pdf)))
        
        if output_pdf.exists():
            progress_msg += f"Solution complete! File saved to: {output_pdf}\n"
            return progress_msg, str(output_pdf)
        else:
            return "PDF generation failed.", None
            
    except Exception as e:
        import traceback
        error_msg = f"Solution Error:\n{str(e)}\n\n{traceback.format_exc()}"
        return error_msg, None


def run_mcq_generation(pdf_path: str, num_mcqs: int, target_lang: str) -> Tuple[str, Optional[str]]:
    """
    Run MCQ generation module
    Returns: (status_message, output_file_path)
    """
    try:
        import generate
        
        output_dir = PROJECT_ROOT / "outputs"
        output_dir.mkdir(exist_ok=True)
        
        progress_msg = f"Generating {num_mcqs} MCQs using Gemini...\n"
        mcqs = generate.generate_mcqs(pdf_path, num_mcqs, target_lang)
        
        if not mcqs:
            return "No MCQs were generated.", None
        
        progress_msg += "MCQs generated. Saving to PDF...\n"
        
        output_pdf = output_dir / f"Generated_MCQs_{target_lang}.pdf"
        ok = generate.save_pdf(mcqs, str(output_pdf), target_lang)
        
        if ok and output_pdf.exists():
            progress_msg += f"MCQ generation complete! File saved to: {output_pdf}\n"
            return progress_msg, str(output_pdf)
        else:
            return "Failed to create PDF.", None
            
    except Exception as e:
        import traceback
        error_msg = f"MCQ Generation Error:\n{str(e)}\n\n{traceback.format_exc()}"
        return error_msg, None


# =============================================================================
# Gradio Interface Functions
# =============================================================================

def process_translation(pdf_file, target_lang):
    """Process translation request"""
    if pdf_file is None:
        return "Please upload a PDF file first.", None
    
    # Save uploaded file
    work_dir = PROJECT_ROOT / "temp"
    work_dir.mkdir(exist_ok=True)
    pdf_path = save_uploaded_file(pdf_file, work_dir)
    
    # Run translation
    return run_translation(str(pdf_path), target_lang)


def process_solution(pdf_file, target_lang):
    """Process solution request"""
    if pdf_file is None:
        return "Please upload a PDF file first.", None
    
    # Save uploaded file
    work_dir = PROJECT_ROOT / "temp"
    work_dir.mkdir(exist_ok=True)
    pdf_path = save_uploaded_file(pdf_file, work_dir)
    
    # Run solution
    return run_solution(str(pdf_path), target_lang)


def process_mcq_generation(pdf_file, num_mcqs, target_lang):
    """Process MCQ generation request"""
    if pdf_file is None:
        return "Please upload a PDF file first.", None
    
    # Save uploaded file
    work_dir = PROJECT_ROOT / "temp"
    work_dir.mkdir(exist_ok=True)
    pdf_path = save_uploaded_file(pdf_file, work_dir)
    
    # Run MCQ generation
    return run_mcq_generation(str(pdf_path), num_mcqs, target_lang)


# =============================================================================
# Gradio Interface
# =============================================================================

def create_interface():
    """Create the Gradio interface"""
    
    with gr.Blocks(title="AI PDF Workspace", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            """
            # 🧠 Unified AI PDF Workspace
            **Translate • Solve • Generate MCQs** — All in one place!
            
            Upload a PDF and choose from three powerful AI modules to process your document.
            """
        )
        
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 📤 Upload PDF")
                pdf_input = gr.File(
                    label="Upload your PDF file",
                    file_types=[".pdf"],
                    type="binary"
                )
                gr.Markdown("*All modules will use this uploaded PDF*")
            
            with gr.Column(scale=2):
                with gr.Tabs():
                    # ========== TRANSLATION TAB ==========
                    with gr.Tab("Translation"):
                        gr.Markdown(
                            """
                            ### Translate PDF Content
                            Extract, translate, and regenerate PDF in your chosen language.
                            """
                        )
                        trans_lang = gr.Dropdown(
                            choices=["English", "Telugu", "Hindi", "Odia", "Tamil"],
                            value="Telugu",
                            label="Target Language",
                            info="Select the language for translation"
                        )
                        trans_btn = gr.Button("Translate PDF", variant="primary", size="lg")
                        
                        trans_output_msg = gr.Textbox(
                            label="Status",
                            lines=10,
                            interactive=False
                        )
                        trans_output_file = gr.File(
                            label="📥 Download Translated PDF"
                        )
                        
                        trans_btn.click(
                            fn=process_translation,
                            inputs=[pdf_input, trans_lang],
                            outputs=[trans_output_msg, trans_output_file]
                        )
                    
                    # ========== SOLUTION TAB ==========
                    with gr.Tab("🧩 Solution"):
                        gr.Markdown(
                            """
                            ### Solve and Translate Questions
                            Extract questions, solve them, and translate to your language.
                            """
                        )
                        sol_lang = gr.Dropdown(
                            choices=["Telugu", "Hindi", "Odia", "Tamil", "Kannada", "English"],
                            value="Telugu",
                            label="Output Language",
                            info="Language for solutions and explanations"
                        )
                        sol_btn = gr.Button("Solve PDF", variant="primary", size="lg")
                        
                        sol_output_msg = gr.Textbox(
                            label="Status",
                            lines=10,
                            interactive=False
                        )
                        sol_output_file = gr.File(
                            label="📥 Download Solved PDF"
                        )
                        
                        sol_btn.click(
                            fn=process_solution,
                            inputs=[pdf_input, sol_lang],
                            outputs=[sol_output_msg, sol_output_file]
                        )
                    
                    # ========== MCQ GENERATION TAB ==========
                    with gr.Tab("❓ MCQ Generation"):
                        gr.Markdown(
                            """
                            ### Generate New MCQs
                            Create fresh multiple-choice questions based on your PDF content.
                            """
                        )
                        mcq_lang = gr.Dropdown(
                            choices=["English", "Telugu", "Hindi", "Odia"],
                            value="English",
                            label="Target Language",
                            info="Language for generated questions"
                        )
                        mcq_count = gr.Number(
                            value=10,
                            minimum=1,
                            maximum=100,
                            step=1,
                            label="Number of MCQs",
                            info="How many questions to generate"
                        )
                        mcq_btn = gr.Button("Generate MCQs", variant="primary", size="lg")
                        
                        mcq_output_msg = gr.Textbox(
                            label="Status",
                            lines=10,
                            interactive=False
                        )
                        mcq_output_file = gr.File(
                            label="📥 Download MCQ PDF"
                        )
                        
                        mcq_btn.click(
                            fn=process_mcq_generation,
                            inputs=[pdf_input, mcq_count, mcq_lang],
                            outputs=[mcq_output_msg, mcq_output_file]
                        )
        
    
    return demo


# =============================================================================
# Main Execution
# =============================================================================

if __name__ == "__main__":
    # Check for required environment variables
    if not os.getenv("GEMINI_API_KEY") and not os.getenv("GENAI_API_KEY"):
        print("⚠️  WARNING: No Gemini API key found in environment variables.")
        print("Some features may not work. Please set GEMINI_API_KEY or GENAI_API_KEY.")
    
    # Create and launch the interface
    demo = create_interface()
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))

