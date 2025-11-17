#!/usr/bin/env python3
"""
Unified Gradio Web Application for AI-Powered PDF Processing
============================================================

This application integrates three AI-powered backend modules:
1. Translation Module - Translate PDFs to Hindi/Odia
2. Solution Generation Module - Extract and solve questions from PDFs
3. MCQ Generation Module - Generate multiple-choice questions

Features:
- Single PDF upload shared across all modules
- Real-time status updates and error handling
- Professional UI with clear feedback
- Download capabilities for all generated outputs

Author: AI-Powered Education Tools
Version: 1.0.0
"""

import os
import sys
import tempfile
import traceback
import asyncio
from pathlib import Path
from datetime import datetime

import gradio as gr

# --- Port management utilities ---
def _is_port_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _find_free_port(start: int = 7000, end: int = 9000) -> int:
    import socket
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise OSError("No free port found in range.")


# --- Language mapping (Hindi & Odia only) ---
LANG_DISPLAY_TO_CODE = {
    "Hindi": "hi",
    "Odia": "or",
}

LANG_CODE_TO_DISPLAY = {
    "hi": "Hindi",
    "or": "Odia",
}

# For generate.py which expects different format
LANG_DISPLAY_TO_GENERATE_CODE = {
    "Hindi": "hindi",
    "Odia": "odia",
}

# --- Import backend modules with error handling and reload support ---
translate_module = None
solution_module = None
generate_module = None

# Track module reload capability
_module_reload_support = False
try:
    import importlib
    _module_reload_support = True
except ImportError:
    pass


def force_reload_translate_module():
    """
    Aggressively reload translate module, clearing all caches.
    This ensures we always use the latest code, matching CLI behavior.
    """
    global translate_module
    
    try:
        # Step 1: Remove from sys.modules (clear cached import)
        if 'translate' in sys.modules:
            del sys.modules['translate']
            print("🔄 Cleared translate from sys.modules")
        
        # Step 2: Remove any translate submodules
        submodules = [key for key in sys.modules.keys() if key.startswith('translate.')]
        for key in submodules:
            del sys.modules[key]
        
        # Step 3: Invalidate import caches
        importlib.invalidate_caches()
        
        # Step 4: Fresh import
        import translate as fresh_module
        translate_module = fresh_module
        
        # Step 5: Verify and log
        if hasattr(translate_module, '__file__'):
            mod_time = datetime.fromtimestamp(os.path.getmtime(translate_module.__file__))
            print(f"✅ Reloaded translate.py (modified: {mod_time.strftime('%Y-%m-%d %H:%M:%S')})")
            print(f"   Path: {translate_module.__file__}")
        
        return translate_module
        
    except Exception as e:
        print(f"❌ CRITICAL: Failed to reload translate module: {e}")
        import traceback
        traceback.print_exc()
        return None


def reload_backend_modules():
    """
    Reload backend modules to pick up code changes.
    Enhanced to use aggressive reload for translate module.
    """
    global translate_module, solution_module, generate_module
    
    if not _module_reload_support:
        print("⚠️ Module reload not available (importlib not found)")
        return False
    
    reloaded = []
    
    # Use aggressive reload for translate
    try:
        translate_module = force_reload_translate_module()
        if translate_module:
            reloaded.append("translate")
    except Exception as e:
        print(f"⚠️ Failed to reload translate module: {e}")
    
    # Standard reload for solution
    try:
        if solution_module:
            solution_module = importlib.reload(solution_module)
            reloaded.append("solution")
    except Exception as e:
        print(f"⚠️ Failed to reload solution module: {e}")
    
    # Standard reload for generate
    try:
        if generate_module:
            generate_module = importlib.reload(generate_module)
            reloaded.append("generate")
    except Exception as e:
        print(f"⚠️ Failed to reload generate module: {e}")
    
    if reloaded:
        print(f"✅ Reloaded modules: {', '.join(reloaded)}")
        return True
    return False


print("\n" + "="*60)
print("🚀 Loading Backend Modules...")
print("="*60)

try:
    import translate as translate_module
    print("✅ Translation module (translate.py) loaded successfully")
    # Verify key classes/functions exist
    if hasattr(translate_module, "PDFProcessingPipeline"):
        print("   ✓ PDFProcessingPipeline class found")
    else:
        print("   ⚠️ PDFProcessingPipeline class not found")
except Exception as e:
    translate_module = None
    print(f"❌ Failed to import translate.py: {e}")
    import traceback
    traceback.print_exc()

try:
    import solution as solution_module
    print("✅ Solution module (solution.py) loaded successfully")
except Exception as e:
    solution_module = None
    print(f"❌ Failed to import solution.py: {e}")

try:
    import generate as generate_module
    print("✅ MCQ Generation module (generate.py) loaded successfully")
except Exception as e:
    generate_module = None
    print(f"❌ Failed to import generate.py: {e}")

print("="*60 + "\n")


# --- Helper Functions ---

def format_file_size(size_bytes):
    """Convert bytes to human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def save_uploaded_file_to_temp(uploaded_file):
    """
    Save uploaded file to a temporary location and return the path.
    Handles various Gradio file upload formats across different versions.
    """
    if uploaded_file is None:
        return None
    
    # Handle string path (already saved)
    if isinstance(uploaded_file, str) and os.path.isfile(uploaded_file):
        return uploaded_file
    
    # Handle file object with name attribute
    try:
        if hasattr(uploaded_file, "name") and os.path.isfile(uploaded_file.name):
            return uploaded_file.name
    except Exception:
        pass
    
    # Handle tuple/list (temp_path, original_name)
    try:
        if isinstance(uploaded_file, (tuple, list)) and len(uploaded_file) >= 2:
            tmp_path = uploaded_file[0]
            if os.path.isfile(tmp_path):
                return tmp_path
    except Exception:
        pass
    
    # Handle file-like objects
    try:
        file_obj = getattr(uploaded_file, "file", None) or getattr(uploaded_file, "fp", None)
        if file_obj:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp.write(file_obj.read())
            tmp.close()
            return tmp.name
    except Exception:
        pass
    
    # Last resort: treat as bytes
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
        print(f"❌ Failed to save uploaded file: {e}")
        return None


def get_file_details(path):
    """Get detailed file information"""
    if not path or not os.path.isfile(path):
        return None
    
    try:
        st = os.stat(path)
        return {
            "name": os.path.basename(path),
            "size_bytes": st.st_size,
            "size_formatted": format_file_size(st.st_size),
            "path": path,
            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        print(f"❌ Error getting file details: {e}")
        return None


# --- Backend Pipeline Wrappers ---

def verify_environment():
    """
    Verify environment variables match CLI execution context.
    Returns True if environment is properly configured.
    """
    from dotenv import load_dotenv
    
    # Force reload .env from script directory
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(env_path, override=True)
    
    # Check critical variables
    api_key = os.getenv('GENAI_API_KEY') or os.getenv('GEMINI_API_KEY')
    model = os.getenv('GENAI_MODEL', 'models/gemini-2.5-flash')
    
    print(f"\n🔐 Environment Verification:")
    if api_key:
        masked = f"{api_key[:10]}...{api_key[-6:]}"
        print(f"   API Key: {masked} ✅")
    else:
        print(f"   API Key: ❌ NOT FOUND")
        return False
    
    print(f"   Model: {model}")
    print(f"   .env loaded from: {env_path}")
    
    return True


def run_translate_pipeline(input_pdf_path: str, target_lang_code: str):
    """
    Execute the translation pipeline from translate.py
    
    Steps:
    1. Extract PDF to JSON (structure + text)
    2. Translate JSON preserving layout
    3. Rebuild translated PDF
    
    Args:
        input_pdf_path: Path to input PDF file
        target_lang_code: Target language code ("hi" or "or")
    
    Returns:
        tuple: (output_path, error_message)
    """
    # Verify environment matches CLI
    if not verify_environment():
        return None, "❌ Environment verification failed. Check API key configuration."
    
    # Validate input file path
    if not input_pdf_path:
        return None, "❌ Error: No PDF file path provided."
    
    input_pdf_path = str(input_pdf_path).strip()
    
    # Check if file exists (with helpful error message)
    if not os.path.exists(input_pdf_path):
        cwd = os.getcwd()
        return None, (
            f"❌ PDF file not found: {os.path.basename(input_pdf_path)}\n\n"
            f"Details:\n"
            f"  - Provided path: {input_pdf_path}\n"
            f"  - Current directory: {cwd}\n"
            f"  - Full path would be: {os.path.abspath(input_pdf_path)}\n\n"
            f"Please check:\n"
            f"  - File exists at the specified location\n"
            f"  - File path is correct (absolute or relative)\n"
            f"  - File has not been moved or deleted"
        )
    
    if not os.path.isfile(input_pdf_path):
        return None, f"❌ Path exists but is not a file: {input_pdf_path}"
    
    if not input_pdf_path.lower().endswith('.pdf'):
        return None, f"❌ File is not a PDF: {input_pdf_path}"
    
    # Calculate input file hash for verification
    import hashlib
    with open(input_pdf_path, 'rb') as f:
        input_hash = hashlib.md5(f.read()).hexdigest()
    file_size = os.path.getsize(input_pdf_path)
    
    print(f"\n📊 Input File Verification:")
    print(f"   Size: {file_size:,} bytes")
    print(f"   MD5: {input_hash}")
    print(f"   (Use this hash to compare with CLI input)")
    
    # CRITICAL: Force fresh module reload (mandatory, not optional)
    print(f"\n🔄 Force reloading translate module (ensuring latest code)...")
    fresh_translate_module = force_reload_translate_module()
    
    if not fresh_translate_module:
        return None, (
            "❌ Translation module not available.\n\n"
            "Possible causes:\n"
            "  - translate.py file is missing or has syntax errors\n"
            "  - Module import failed during app startup\n"
            "  - Check console output for import errors"
        )
    
    if not hasattr(fresh_translate_module, "PDFProcessingPipeline"):
        return None, (
            "❌ PDFProcessingPipeline class not found in translate.py\n\n"
            "Possible causes:\n"
            "  - translate.py has been modified and class renamed/moved\n"
            "  - Module has syntax errors\n"
            "  - Check translate.py file for PDFProcessingPipeline class definition"
        )
    
    try:
        print(f"\n{'='*60}")
        print(f"🌐 Starting Translation Pipeline")
        print(f"📄 Input: {os.path.basename(input_pdf_path)}")
        print(f"📁 Full path: {os.path.abspath(input_pdf_path)}")
        print(f"🗣️  Target Language: {LANG_CODE_TO_DISPLAY.get(target_lang_code, target_lang_code)}")
        print(f"⏰ Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        # Initialize pipeline with freshly reloaded module
        pipeline = fresh_translate_module.PDFProcessingPipeline(working_dir="outputs")
        
        # Run complete pipeline (path validation happens inside)
        result = pipeline.run_complete_pipeline(
            pdf_path=input_pdf_path,
            languages=[target_lang_code],
            include_images=True,
            image_handling="metadata",
        )
        
        # Check for generated PDFs
        generated_pdfs = result.get("generated_pdfs", [])
        if generated_pdfs:
            output_path = str(generated_pdfs[0])
            if os.path.exists(output_path):
                # Verify output file
                output_size = os.path.getsize(output_path)
                with open(output_path, 'rb') as f:
                    output_hash = hashlib.md5(f.read()).hexdigest()
                
                print(f"\n✅ Translation successful!")
                print(f"📊 Output File Verification:")
                print(f"   File: {os.path.basename(output_path)}")
                print(f"   Size: {output_size:,} bytes")
                print(f"   MD5: {output_hash}")
                print(f"   {'='*60}")
                print(f"   💡 Compare this MD5 hash with CLI output to verify match!")
                print(f"   {'='*60}\n")
                
                return output_path, None
            else:
                print(f"⚠️ PDF was generated but file not found at: {output_path}")
        
        # Check for translated JSON (fallback)
        translations = result.get("translations", [])
        if translations:
            output_path = str(translations[0])
            if os.path.exists(output_path):
                print(f"⚠️ Translated JSON created: {os.path.basename(output_path)}")
                return output_path, "Translation completed, but PDF generation may have failed. JSON file provided instead."
            else:
                print(f"⚠️ JSON was generated but file not found at: {output_path}")
        
        # No output produced
        return None, (
            "❌ Pipeline completed but no output files were generated.\n\n"
            "Possible causes:\n"
            "  - Translation process failed silently\n"
            "  - Output directory permissions issue\n"
            "  - Check console output for detailed error messages"
        )
        
    except FileNotFoundError as e:
        error_msg = str(e)
        print(f"\n❌ File not found error:\n{error_msg}")
        return None, f"❌ File not found: {error_msg}"
    
    except ValueError as e:
        error_msg = str(e)
        print(f"\n❌ Validation error:\n{error_msg}")
        return None, f"❌ Validation error: {error_msg}"
    
    except PermissionError as e:
        error_msg = str(e)
        print(f"\n❌ Permission error:\n{error_msg}")
        return None, f"❌ Permission denied: {error_msg}"
    
    except Exception as e:
        error_details = traceback.format_exc()
        error_msg = str(e)
        print(f"\n❌ Translation failed:\n{error_details}")
        return None, (
            f"❌ Translation failed: {error_msg}\n\n"
            f"Full error details have been logged to console.\n"
            f"Check the terminal/console output for more information."
        )


def run_solution_pipeline(input_pdf_path: str, target_lang_code: str):
    """
    Execute the solution generation pipeline from solution.py
    
    Steps:
    1. Extract text and images from PDF
    2. Solve questions using SymPy and/or Gemini LLM
    3. Translate solutions to target language
    4. Render final PDF with solutions
    
    Args:
        input_pdf_path: Path to input PDF file
        target_lang_code: Target language code ("hi" or "or")
    
    Returns:
        tuple: (output_path, error_message)
    """
    if not solution_module:
        return None, "❌ Solution module not available. Please check solution.py import."
    
    try:
        print(f"\n{'='*60}")
        print(f"🧠 Starting Solution Generation Pipeline")
        print(f"📄 Input: {os.path.basename(input_pdf_path)}")
        print(f"🗣️  Output Language: {LANG_CODE_TO_DISPLAY.get(target_lang_code, target_lang_code)}")
        print(f"{'='*60}\n")
        
        # Create temporary output directory
        output_dir = "outputs"
        os.makedirs(output_dir, exist_ok=True)
        
        # Step 1: Extract PDF
        print("📤 Extracting PDF content...")
        if not hasattr(solution_module, "extract_pdf"):
            return None, "❌ extract_pdf function not found in solution.py"
        
        extracted_json = os.path.join(output_dir, "extracted_data.json")
        image_folder = os.path.join(output_dir, "extracted_images")
        
        pages = solution_module.extract_pdf(
            input_pdf_path,
            output_json=extracted_json,
            output_image_folder=image_folder
        )
        print(f"✅ Extracted {len(pages)} pages")
        
        # Step 2: Solve questions
        print("\n🔍 Solving questions...")
        if not hasattr(solution_module, "solve_pages"):
            return None, "❌ solve_pages function not found in solution.py"
        
        solved_items = solution_module.solve_pages(pages)
        print(f"✅ Solved {len(solved_items)} question(s)")
        
        # Step 3: Translate solutions
        print(f"\n🌐 Translating solutions to {LANG_CODE_TO_DISPLAY.get(target_lang_code)}...")
        if not hasattr(solution_module, "translate_items"):
            return None, "❌ translate_items function not found in solution.py"
        
        # Get full language name from code
        lang_map = {"hi": "Hindi", "or": "Odia"}
        target_lang_name = lang_map.get(target_lang_code, "Hindi")
        
        translated_items = solution_module.translate_items(solved_items, target_lang_name)
        print(f"✅ Translated {len(translated_items)} items")
        
        # Step 4: Render PDF
        print("\n📄 Rendering final PDF...")
        if not hasattr(solution_module, "render_pdf_from_data"):
            return None, "❌ render_pdf_from_data function not found in solution.py"
        
        output_pdf = os.path.join(output_dir, f"solved_{target_lang_code}.pdf")
        lang_lower = target_lang_name.lower()
        
        # Call async function
        asyncio.run(solution_module.render_pdf_from_data(
            translated_items,
            lang_lower,
            output_pdf
        ))
        
        if os.path.exists(output_pdf):
            print(f"✅ Solution generation successful: {os.path.basename(output_pdf)}")
            return output_pdf, None
        else:
            return None, "❌ PDF rendering completed but output file not found."
        
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"\n❌ Solution generation failed:\n{error_details}")
        return None, f"Solution generation failed: {str(e)}"


def run_generate_mcqs(input_pdf_path: str, n: int, target_lang_code: str, topic: str = None):
    """
    Execute the MCQ generation pipeline from generate.py
    
    Steps:
    1. Extract text from PDF (if PDF provided)
    2. Generate MCQs using Gemini 2.5 Pro
    3. Post-process and format MCQs
    4. Render final PDF with MCQs
    
    Args:
        input_pdf_path: Path to input PDF file (can be None if topic provided)
        n: Number of MCQs to generate
        target_lang_code: Target language code ("hi" or "or")
        topic: Optional topic for MCQ generation
    
    Returns:
        tuple: (output_path, preview_text, error_message)
    """
    if not generate_module:
        return None, None, "❌ MCQ Generation module not available. Please check generate.py import."
    
    try:
        print(f"\n{'='*60}")
        print(f"📝 Starting MCQ Generation Pipeline")
        if input_pdf_path:
            print(f"📄 Input: {os.path.basename(input_pdf_path)}")
        if topic:
            print(f"🎯 Topic: {topic}")
        print(f"🔢 Number of MCQs: {n}")
        print(f"🗣️  Language: {LANG_CODE_TO_DISPLAY.get(target_lang_code, target_lang_code)}")
        print(f"{'='*60}\n")
        
        # Map language code to format expected by generate.py
        lang_for_generate = LANG_DISPLAY_TO_GENERATE_CODE.get(
            LANG_CODE_TO_DISPLAY.get(target_lang_code, "Hindi"),
            "hindi"
        )
        
        # Generate MCQs
        mcq_text = None
        
        if topic and topic.strip():
            # Generate from topic
            print(f"🎯 Generating MCQs for topic: {topic}")
            if not hasattr(generate_module, "generate_topic_mcqs"):
                return None, None, "❌ generate_topic_mcqs function not found in generate.py"
            
            mcq_text = generate_module.generate_topic_mcqs(topic.strip(), n, lang_for_generate)
        
        elif input_pdf_path:
            # Generate from PDF
            print(f"📄 Generating MCQs from PDF")
            if not hasattr(generate_module, "generate_mcqs"):
                return None, None, "❌ generate_mcqs function not found in generate.py"
            
            mcq_text = generate_module.generate_mcqs(input_pdf_path, n, lang_for_generate, topic=None)
        
        else:
            return None, None, "❌ Either PDF file or topic must be provided for MCQ generation."
        
        if not mcq_text or not mcq_text.strip():
            return None, None, "❌ MCQ generation returned empty result. Please try again."
        
        print(f"✅ Generated MCQ text ({len(mcq_text)} characters)")
        
        # Create output directory
        output_dir = "outputs"
        os.makedirs(output_dir, exist_ok=True)
        
        # Save text preview
        txt_path = os.path.join(output_dir, f"mcqs_{lang_for_generate}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(mcq_text)
        print(f"✅ Saved text file: {os.path.basename(txt_path)}")
        
        # Generate PDF
        print("\n📄 Rendering PDF...")
        if not hasattr(generate_module, "save_pdf"):
            return txt_path, mcq_text[:2000], "⚠️ PDF generation not available, text file provided instead."
        
        pdf_path = os.path.join(output_dir, f"mcqs_{lang_for_generate}.pdf")
        lang_display = LANG_CODE_TO_DISPLAY.get(target_lang_code, "Hindi")
        
        success = generate_module.save_pdf(mcq_text, pdf_path, lang_display)
        
        if success and os.path.exists(pdf_path):
            print(f"✅ MCQ generation successful: {os.path.basename(pdf_path)}")
            # Return PDF path and preview text (first 2000 chars)
            preview = mcq_text[:2000] + ("..." if len(mcq_text) > 2000 else "")
            return pdf_path, preview, None
        else:
            # Fallback to text file
            print(f"⚠️ PDF generation failed, returning text file")
            preview = mcq_text[:2000] + ("..." if len(mcq_text) > 2000 else "")
            return txt_path, preview, "⚠️ PDF generation failed, text file provided instead."
        
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"\n❌ MCQ generation failed:\n{error_details}")
        return None, None, f"MCQ generation failed: {str(e)}"


# --- Gradio UI Callbacks ---

def ui_show_file_info(uploaded):
    """Display detailed file information after upload"""
    path = save_uploaded_file_to_temp(uploaded)
    if not path:
        return "📤 No file uploaded yet."
    
    info = get_file_details(path)
    if not info:
        return "⚠️ Unable to read file information."
    
    details = f"""📄 **File Information**
    
**Name:** {info['name']}
**Size:** {info['size_formatted']}
**Modified:** {info['modified']}

✅ File successfully uploaded and ready for processing."""
    
    return details


def ui_translate(uploaded, language_display):
    """Handle translation request"""
    path = save_uploaded_file_to_temp(uploaded)
    if not path:
        return "❌ Error: No file uploaded. Please upload a PDF file first.", None
    
    lang_code = LANG_DISPLAY_TO_CODE.get(language_display, "hi")
    
    # Show processing message
    status_msg = f"🔄 Processing translation to {language_display}...\nThis may take a few minutes."
    
    out_path, error = run_translate_pipeline(path, lang_code)
    
    if error:
        return f"❌ Translation failed:\n{error}", None
    
    filename = os.path.basename(out_path)
    success_msg = f"""✅ **Translation Complete!**

**Output File:** {filename}
**Language:** {language_display}
**Status:** Ready for download

You can download the translated PDF using the button below."""
    
    return success_msg, out_path


def ui_solve(uploaded, language_display):
    """Handle solution generation request"""
    path = save_uploaded_file_to_temp(uploaded)
    if not path:
        return "❌ Error: No file uploaded. Please upload a PDF file first.", None
    
    lang_code = LANG_DISPLAY_TO_CODE.get(language_display, "hi")
    
    # Show processing message
    status_msg = f"🔄 Generating solutions in {language_display}...\nThis may take a few minutes."
    
    out_path, error = run_solution_pipeline(path, lang_code)
    
    if error:
        return f"❌ Solution generation failed:\n{error}", None
    
    filename = os.path.basename(out_path)
    success_msg = f"""✅ **Solution Generation Complete!**

**Output File:** {filename}
**Language:** {language_display}
**Status:** Ready for download

You can download the solved PDF using the button below."""
    
    return success_msg, out_path


def ui_generate_mcqs(uploaded, count, language_display, topic):
    """Handle MCQ generation request"""
    path = save_uploaded_file_to_temp(uploaded)
    
    # Allow either PDF or topic
    if not path and not (topic and topic.strip()):
        return "❌ Error: Please upload a PDF file OR enter a topic for MCQ generation.", "", None
    
    try:
        count_int = int(count)
        if count_int <= 0 or count_int > 100:
            return "❌ Error: Number of MCQs must be between 1 and 100.", "", None
    except:
        return "❌ Error: Please enter a valid number for MCQ count.", "", None
    
    lang_code = LANG_DISPLAY_TO_CODE.get(language_display, "hi")
    
    # Show processing message
    if topic and topic.strip():
        status_msg = f"🔄 Generating {count} MCQs on topic '{topic}' in {language_display}...\nThis may take a few minutes."
    else:
        status_msg = f"🔄 Generating {count} MCQs from PDF in {language_display}...\nThis may take a few minutes."
    
    out_path, preview, error = run_generate_mcqs(path, count_int, lang_code, topic)
    
    if error:
        # Partial success (text file generated but PDF failed)
        if out_path:
            filename = os.path.basename(out_path)
            warning_msg = f"""⚠️ **Partial Success**

{error}

**Text File:** {filename}
**Preview available below**"""
            return warning_msg, preview or "", out_path
        else:
            return f"❌ MCQ generation failed:\n{error}", "", None
    
    filename = os.path.basename(out_path)
    success_msg = f"""✅ **MCQ Generation Complete!**

**Output File:** {filename}
**Number of MCQs:** {count}
**Language:** {language_display}
{"**Topic:** " + topic if topic else "**Source:** Uploaded PDF"}
**Status:** Ready for download

Preview shown below. Download the full PDF using the button below."""
    
    return success_msg, preview or "", out_path


# --- Build Gradio UI ---
def build_ui():
    """Build the complete Gradio interface with all three modules"""
    
    # Custom CSS for better styling
    custom_css = """
    .gradio-container {
        max-width: 1200px !important;
        margin: auto;
    }
    .main-title {
        text-align: center;
        color: #1f2937;
        margin-bottom: 20px;
    }
    .subtitle {
        text-align: center;
        color: #6b7280;
        margin-bottom: 30px;
    }
    .tab-content {
        padding: 20px;
    }
    .status-box {
        min-height: 100px;
    }
    """
    
    with gr.Blocks(
        title="AI-Powered PDF Processing Toolkit",
        css=custom_css,
        theme=gr.themes.Soft()
    ) as demo:
        
        # Header
        gr.Markdown(
            """
            <div class="main-title">
            <h1>🎓 AI-Powered PDF Processing Toolkit</h1>
            </div>
            <div class="subtitle">
            <p><b>Unified interface for Translation, Solution Generation, and MCQ Creation</b></p>
            <p>Powered by Google Gemini 2.5 Flash/Pro | Supporting Hindi & Odia</p>
            <p><small>Note: Translation module uses GoogleTranslator (not Gemini). Solution/MCQ modules use Gemini 2.5 Flash/Pro.</small></p>
            </div>
            """,
            elem_classes=["main-title", "subtitle"]
        )
        
        # File Upload Section
        gr.Markdown("## 📤 Step 1: Upload Your PDF")
        with gr.Row():
            with gr.Column(scale=3):
                uploader = gr.File(
                    label="Upload PDF File",
                    file_types=['.pdf'],
                    interactive=True,
                    type="filepath"
                )
            with gr.Column(scale=2):
                file_info = gr.Markdown(
                    value="📤 No file uploaded yet.",
                    label="File Information"
                )
        
        # Connect file upload to info display
        uploader.change(
            fn=ui_show_file_info,
            inputs=[uploader],
            outputs=[file_info]
        )
        
        gr.Markdown("---")
        gr.Markdown("## 🔧 Step 2: Choose Your Processing Module")
        
        # Module Tabs
        with gr.Tabs():
            
            # ========== TRANSLATION MODULE ==========
            with gr.TabItem("🌐 Translation"):
                gr.Markdown(
                    """
                    ### Translation Module
                    Translate your PDF document into Hindi or Odia while preserving the original layout, formatting, and mathematical expressions.
                    
                    **Features:**
                    - Layout-preserving translation
                    - Math expression handling
                    - Image metadata preservation
                    """
                )
                
                with gr.Row():
                    lang_translate = gr.Dropdown(
                        choices=list(LANG_DISPLAY_TO_CODE.keys()),
                        value="Hindi",
                        label="Target Language",
                        info="Select the language for translation"
                    )
                    translate_btn = gr.Button(
                        "🌐 Translate PDF",
                        variant="primary",
                        size="lg"
                    )
                
                translate_status = gr.Markdown(
                    value="",
                    label="Translation Status",
                    elem_classes=["status-box"]
                )
                
                translate_download = gr.File(
                    label="📥 Download Translated PDF",
                    interactive=False
                )
                
                translate_btn.click(
                    fn=ui_translate,
                    inputs=[uploader, lang_translate],
                    outputs=[translate_status, translate_download]
                )
            
            # ========== SOLUTION MODULE ==========
            with gr.TabItem("🧠 Solution Generation"):
                gr.Markdown(
                    """
                    ### Solution Generation Module
                    Extract questions from your PDF, solve them using AI, and generate a comprehensive solution document.
                    
                    **Features:**
                    - Automatic question extraction
                    - SymPy symbolic math solving
                    - AI-powered explanation generation
                    - Multilingual solution output
                    """
                )
                
                with gr.Row():
                    lang_solve = gr.Dropdown(
                        choices=list(LANG_DISPLAY_TO_CODE.keys()),
                        value="Hindi",
                        label="Solution Language",
                        info="Select the language for solutions"
                    )
                    solve_btn = gr.Button(
                        "🧠 Generate Solutions",
                        variant="primary",
                        size="lg"
                    )
                
                solve_status = gr.Markdown(
                    value="",
                    label="Solution Generation Status",
                    elem_classes=["status-box"]
                )
                
                solve_download = gr.File(
                    label="📥 Download Solution PDF",
                    interactive=False
                )
                
                solve_btn.click(
                    fn=ui_solve,
                    inputs=[uploader, lang_solve],
                    outputs=[solve_status, solve_download]
                )
            
            # ========== MCQ GENERATION MODULE ==========
            with gr.TabItem("📝 MCQ Generation"):
                gr.Markdown(
                    """
                    ### MCQ Generation Module
                    Generate multiple-choice questions either from your uploaded PDF or on a custom topic.
                    
                    **Features:**
                    - PDF-based MCQ generation
                    - Topic-based MCQ creation
                    - AI-powered question crafting (Gemini 2.5 Pro)
                    - Formatted PDF output with answers
                    """
                )
                
                gr.Markdown("**📝 MCQ Configuration**")
                
                with gr.Row():
                    mcq_count = gr.Number(
                        value=10,
                        minimum=1,
                        maximum=100,
                        precision=0,
                        label="Number of MCQs",
                        info="Enter a number between 1-100"
                    )
                    mcq_lang = gr.Dropdown(
                        choices=list(LANG_DISPLAY_TO_CODE.keys()),
                        value="Hindi",
                        label="MCQ Language",
                        info="Select output language"
                    )
                
                mcq_topic = gr.Textbox(
                    label="Topic (Optional)",
                    placeholder="e.g., Indian History, Mathematics, Science...",
                    info="Leave empty to generate from uploaded PDF, or enter a topic for custom MCQs",
                    lines=2
                )
                
                mcq_btn = gr.Button(
                    "📝 Generate MCQs",
                    variant="primary",
                    size="lg"
                )
                
                mcq_status = gr.Markdown(
                    value="",
                    label="MCQ Generation Status",
                    elem_classes=["status-box"]
                )
                
                with gr.Accordion("📄 MCQ Preview", open=True):
                    mcq_preview = gr.Textbox(
                        label="Generated MCQs Preview",
                        placeholder="MCQ preview will appear here...",
                        interactive=False,
                        lines=15,
                        max_lines=20
                    )
                
                mcq_download = gr.File(
                    label="📥 Download MCQ PDF",
                    interactive=False
                )
                
                mcq_btn.click(
                    fn=ui_generate_mcqs,
                    inputs=[uploader, mcq_count, mcq_lang, mcq_topic],
                    outputs=[mcq_status, mcq_preview, mcq_download]
                )
        
        # Version info
        gr.Markdown(
            """
            <div style="text-align: center; color: #9ca3af; margin-top: 20px;">
            <small>AI-Powered PDF Processing Toolkit v1.0.0 | Built with Gradio & Google Gemini</small>
            </div>
            """
        )
    
    return demo


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 Launching AI-Powered PDF Processing Toolkit")
    print("="*60)
    
    # Check for API keys
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GENAI_API_KEY")
    if not api_key:
        print("\n⚠️  WARNING: No API key found!")
        print("Please set GEMINI_API_KEY or GENAI_API_KEY in your environment.")
        print("Example: export GEMINI_API_KEY='your-api-key-here'")
        print("\nThe application will launch, but backend modules may not work without an API key.\n")
    else:
        print("✅ API key found")
    
    # Create outputs directory
    os.makedirs("outputs", exist_ok=True)
    print("✅ Output directory ready: ./outputs")
    
    # Build the UI
    demo = build_ui()
    
    # Determine port
    port = int(os.environ.get("PORT", "7860"))
    if not _is_port_free(port):
        print(f"⚠️  Port {port} is already in use, finding alternative...")
        port = _find_free_port()
    
    print(f"\n{'='*60}")
    print(f"🌐 Starting Gradio server on port {port}")
    print(f"📱 Local URL: http://localhost:{port}")
    print(f"🌍 Network URL: http://0.0.0.0:{port}")
    print(f"{'='*60}\n")
    
    # Launch with error handling
    try:
        ver = gr.__version__
        print(f"ℹ️  Gradio version: {ver}")
        
        # Launch the application
        demo.queue().launch(
            server_name="0.0.0.0",
            server_port=port,
            share=False,
            show_error=True,
            quiet=False
        )
        
    except KeyboardInterrupt:
        print("\n\n👋 Application stopped by user")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Error launching application: {e}")
        print(f"\n{traceback.format_exc()}")
        print("\n💡 Trying fallback launch...")
        
        try:
            demo.launch(server_name="0.0.0.0", server_port=port, share=False)
        except Exception as e2:
            print(f"❌ Fallback also failed: {e2}")
            print("\nPlease check your Gradio installation and try again.")
            sys.exit(1)


