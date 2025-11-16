
"""
Unified pipeline (NO OCR):
1) Extract text + images from input PDF (PyMuPDF)
2) Solve equations via SymPy (simple) or fallback to Gemini LLM for MCQs
3) Translate solved items into selected language via Gemini
4) Render final translated JSON -> PDF via Playwright

Features:
- Secure equation solving (uses sympify instead of eval)
- Automatic retry logic with exponential backoff for API calls
- Comprehensive input validation and error handling
- Font fallback support for multiple Indic languages
- Progress tracking with detailed status messages

Requirements:
- GENAI_API_KEY and GENAI_MODEL in a .env file
- For PDF rendering: run 'playwright install chromium'
- Font files in fonts/ directory (optional, will use fallback if missing)

Notes:
- Final PDF contains translated text (no images embedded)
- Supports Telugu, Hindi, Odia, Tamil, Kannada, Gujarati, Marathi, Bengali, English
"""
import os
import json
import re
import tempfile
import pathlib
import html
import asyncio
from dotenv import load_dotenv
from tqdm import tqdm

# PDF extraction
import fitz  # PyMuPDF

# solving
from sympy import symbols, Eq, solve, sympify, SympifyError
import google.generativeai as genai

# pdf rendering
from playwright.async_api import async_playwright
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pathlib import Path as PathLib

# -------------------------
# Load environment
# -------------------------
load_dotenv()
API_KEY = os.getenv("GENAI_API_KEY")
MODEL_NAME = os.getenv("GENAI_MODEL", "models/gemini-2.5-flash")

if not API_KEY:
    print("❌ Please set GENAI_API_KEY in a .env file in this folder.")
    print("Example .env contents:")
    print("GENAI_API_KEY=your_gemini_api_key_here")
    print("GENAI_MODEL=models/gemini-2.0-flash-exp")
    raise SystemExit(1)

# Validate model name format
if not MODEL_NAME.startswith("models/"):
    print(f"⚠️ Warning: MODEL_NAME '{MODEL_NAME}' doesn't start with 'models/'")
    print("   Common models: models/gemini-2.0-flash-exp, models/gemini-1.5-pro")

genai.configure(api_key=API_KEY)
try:
    model = genai.GenerativeModel(MODEL_NAME)
    print(f"✅ Using model: {MODEL_NAME}")
except Exception as model_error:
    print(f"❌ Failed to initialize model '{MODEL_NAME}': {model_error}")
    print("   Please check your GENAI_MODEL in .env file")
    raise SystemExit(1)

# -------------------------
# Helpers
# -------------------------
def clean(s):
    if not s:
        return ""
    s = html.unescape(str(s))
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").strip()

def extract_json_block(text: str) -> str:
    match = re.search(r"```json\s*(.*?)```", text or "", re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else (text or "").strip()

def extract_inner_json(text):
    if not text:
        return None
    match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if match:
        inner = match.group(1)
        try:
            return json.loads(inner)
        except Exception:
            return None
    return None

# -------------------------
# Math solver helper (naive)
# -------------------------
def solve_math_equation(equation_text: str):
    x = symbols('x')
    try:
        # Keep only characters likely in simple equations (digits, x, ops, =, parentheses, decimal)
        clean_text = re.sub(r"[^\dxX\+\-\*/=\.\(\)\s]", "", equation_text)
        if "=" not in clean_text:
            return None
        lhs, rhs = clean_text.split("=", 1)
        # naive insertion of '*' for things like 2x -> 2*x
        lhs = re.sub(r"(?<=\d)x", "*x", lhs.lower())
        rhs = re.sub(r"(?<=\d)x", "*x", rhs.lower())
        # Use sympify instead of eval for security (prevents code injection)
        eq = Eq(sympify(lhs, locals={'x': x}), sympify(rhs, locals={'x': x}))
        solution = solve(eq, x)
        return solution
    except (SympifyError, Exception):
        return None

# -------------------------
# Extraction (no OCR)
# -------------------------
def extract_pdf(input_pdf, output_json="extracted_data.json", output_image_folder="extracted_images"):
    os.makedirs(output_image_folder, exist_ok=True)
    
    # Validate PDF file
    if not os.path.exists(input_pdf):
        raise FileNotFoundError(f"PDF file not found: {input_pdf}")
    
    # Check file size (warn if > 50MB)
    file_size_mb = os.path.getsize(input_pdf) / (1024 * 1024)
    if file_size_mb > 50:
        print(f"⚠️ Large PDF file ({file_size_mb:.1f} MB) - this may take a while...")
    
    try:
        doc = fitz.open(input_pdf)
    except Exception as e:
        raise RuntimeError(f"Failed to open PDF '{input_pdf}': {e}")

    all_pages_data = []
    for page_number, page in enumerate(doc):
        text = page.get_text() or ""
        images = []
        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            try:
                pix = fitz.Pixmap(doc, xref)
                img_name = f"page{page_number+1}_img{img_index+1}.png"
                img_path = os.path.join(output_image_folder, img_name)
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                pix.save(img_path)
                images.append(img_path)
            except Exception as ie:
                print(f"⚠️ Failed to save image page{page_number+1}_img{img_index+1}: {ie}")
                continue

        page_data = {
            "page": page_number + 1,
            "text": text.strip(),
            "images": images
        }
        all_pages_data.append(page_data)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(all_pages_data, f, ensure_ascii=False, indent=2)

    print(f"✅ Extraction complete. Saved to '{output_json}'")
    return all_pages_data

# -------------------------
# Solver (SymPy first, LLM fallback)
# -------------------------
def call_llm_with_retry(prompt, max_retries=3, timeout=60):
    """Helper function to call LLM with retry logic and timeout"""
    import time
    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                prompt,
                request_options={"timeout": timeout}
            )
            
            # Check if response was blocked by safety filters
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                feedback = str(response.prompt_feedback)
                if 'BLOCK' in feedback.upper():
                    print(f"⚠️ Response blocked by safety filters: {feedback}")
                    return ""
            
            # Check if response has text
            if response and hasattr(response, 'text') and response.text:
                return response.text.strip()
            
            # If response exists but no text, check candidates
            if response and hasattr(response, 'candidates'):
                if response.candidates:
                    print(f"⚠️ Response received but no text. Candidates: {len(response.candidates)}")
                else:
                    print(f"⚠️ Empty response received (no candidates)")
            
            return ""
            
        except AttributeError as e:
            # Handle cases where response.text doesn't exist
            print(f"⚠️ Response structure issue: {e}")
            return ""
            
        except Exception as e:
            error_str = str(e).lower()
            # Check if it's a rate limit error
            if "rate" in error_str or "quota" in error_str or "429" in error_str:
                wait_time = 10 * (attempt + 1)  # Longer wait for rate limits
                print(f"⚠️ Rate limit hit (attempt {attempt+1}/{max_retries}), waiting {wait_time}s...")
            elif "timeout" in error_str:
                print(f"⚠️ Request timeout (attempt {attempt+1}/{max_retries})")
                wait_time = 5
            elif attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"⚠️ API call failed (attempt {attempt+1}/{max_retries}): {str(e)[:100]}")
                print(f"   Retrying in {wait_time}s...")
            else:
                print(f"❌ All retries exhausted. Last error: {str(e)[:200]}")
                raise e
            
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            else:
                raise e
    return ""

def solve_pages(pages):
    results = []
    
    # Validate that we have pages with text
    pages_with_text = [p for p in pages if str(p.get("text", "")).strip()]
    if not pages_with_text:
        print("⚠️ No text found in PDF pages. Nothing to solve.")
        return results
    
    for page in tqdm(pages_with_text, desc="Solving pages"):
        text = str(page.get("text", "")).strip()
        if not text:
            continue

        # 1) Try SymPy for simple equations
        sympy_solution = solve_math_equation(text)
        if sympy_solution:
            prompt = f"""
You are a math teacher. Explain in 2 lines how to solve this:
Equation: {text}
Answer: {sympy_solution}
Return only 2-line explanation text.
"""
            try:
                explanation = call_llm_with_retry(prompt)
            except Exception as e:
                explanation = f"Error generating explanation: {e}"

            results.append({
                "question_text": text,
                "answer": str(sympy_solution),
                "explanation": explanation,
                "method": "sympy"
            })
            continue

        # 2) Fallback to LLM for MCQs / textual questions
        prompt = f"""
You are an expert exam solver. Extract and solve all questions and MCQs present in the text below.
For each question:
- Include "question_number" if visible
- Include "question_text" (copy the actual question)
- Include "answer" (correct option number or text)
- Include "explanation" (2-line reasoning)
Return strictly as a JSON array, no markdown or commentary.

TEXT:
{text}
"""
        try:
            response_text = call_llm_with_retry(prompt)
            raw_output = extract_json_block(response_text)
            parsed = None
            try:
                parsed = json.loads(raw_output)
                if isinstance(parsed, dict):
                    parsed = [parsed]
            except Exception:
                # if JSON parsing fails, keep raw_output
                parsed = [{"question_text": text, "raw_output": raw_output}]
            results.extend(parsed)
        except Exception as e:
            results.append({
                "question_text": text,
                "error": str(e),
                "method": "gemini_fallback"
            })

    # Save solved file
    os.makedirs("outputs", exist_ok=True)
    solved_path = os.path.join("outputs", "solved_extracted_data.json")
    with open(solved_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"✅ Solving complete. Saved to '{solved_path}'")
    return results

# -------------------------
# Translation
# -------------------------
LANGUAGES = {
    "1": "Telugu",
    "2": "Hindi",
    "3": "Odia",
    "4": "Tamil",
    "5": "Kannada",
    "6": "Gujarati",
    "7": "Marathi",
    "8": "Bengali",
    "9": "English"
}

def translate_items(items, target_lang):
    if not items:
        print("⚠️ No items to translate.")
        return []
    
    lang_lower = target_lang.lower()
    translated = []
    for item in tqdm(items, desc=f"Translating → {target_lang}"):
        q = item.get("question_text", "")
        a = item.get("answer", "")
        e = item.get("explanation", "")

        prompt = f"""
Translate the following solved MCQ into {target_lang}.
Keep all numbers, symbols, and math expressions unchanged.

Return output strictly as JSON like:
{{
  "question_text_{lang_lower}": "...",
  "answer_{lang_lower}": "...",
  "explanation_{lang_lower}": "..."
}}

Question: {q}
Answer: {a}
Explanation: {e}
"""
        try:
            response_text = call_llm_with_retry(prompt)
            parsed = extract_inner_json(response_text)
            if parsed:
                merged = {**item, **parsed}
            else:
                merged = {**item, f"raw_translation_{lang_lower}": response_text}
            translated.append(merged)
        except Exception as err:
            item[f"translation_error_{lang_lower}"] = str(err)
            translated.append(item)

    out_file = os.path.join("outputs", f"translated_{lang_lower}_auto.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)
    print(f"✅ Translation complete. Saved to '{out_file}'")
    return translated

# -------------------------
# JSON -> PDF (Playwright rendering)
# -------------------------
# Set up font directory
BASE_DIR = PathLib(__file__).parent.resolve()
FONTS_DIR = BASE_DIR / "fonts"

# Create fonts directory if it doesn't exist
FONTS_DIR.mkdir(exist_ok=True)

# Font file mapping with correct filenames
FONTS = {
    "telugu": str(FONTS_DIR / "NotoSansTelugu-Regular.ttf"),
    "hindi":  str(FONTS_DIR / "TiroDevanagariHindi-Regular.ttf"),
    "odia":   str(FONTS_DIR / "NotoSansOriya-Regular.ttf"),
    "tamil":  str(FONTS_DIR / "NotoSansTamil-Regular.ttf"),
    "kannada": str(FONTS_DIR / "NotoSansKannada-Regular.ttf"),
}

def check_fonts():
    """Check if font files exist and warn if missing"""
    missing_fonts = []
    for lang, font_path in FONTS.items():
        if not os.path.exists(font_path):
            missing_fonts.append(f"  - {lang}: {font_path}")
    
    if missing_fonts:
        print("⚠️ Some font files are missing:")
        print("\n".join(missing_fonts))
        print("Note: PDF will use fallback fonts (Arial/Helvetica) which may not render all characters correctly.")
        print(f"Place font files in: {FONTS_DIR}\n")

def detect_language_sample(data):
    if not data:
        return "telugu"
    sample = json.dumps(data[:5], ensure_ascii=False).lower()
    if "telugu" in sample:
        return "telugu"
    elif "hindi" in sample:
        return "hindi"
    elif "odia" in sample or "oriya" in sample:
        return "odia"
    elif "tamil" in sample:
        return "tamil"
    elif "kannada" in sample:
        return "kannada"
    else:
        return "telugu"

def build_html(pages, lang):
    # Get font file path
    font_file = FONTS.get(lang, None)
    
    # Check if font exists (with fallback to hindi if not found)
    if not font_file or not os.path.exists(font_file):
        # Try Hindi font as fallback
        font_file = FONTS.get("hindi", None)
    
    if font_file and os.path.exists(font_file):
        font_path = pathlib.Path(font_file).resolve().as_uri()
        font_face = f"""
        @font-face {{
            font-family: 'LangFont';
            src: url('{font_path}') format('truetype');
            font-weight: normal;
            font-style: normal;
        }}
        """
        body_font = "Arial, LangFont, sans-serif"
        print(f"✅ Using font: {font_file}")
    else:
        font_face = ""
        body_font = "Arial, sans-serif"
        print(f"⚠️ Font file not found for {lang}, using Arial fallback")

    lang_labels = {
        "telugu": ("సమాధానం", "వివరణ", "తెలుగులో అనువదించిన ప్రశ్నపత్రం"),
        "hindi":  ("उत्तर", "व्याख्या", "हिंदी में अनुवादित प्रश्नपत्र"),
        "odia":   ("ଉତ୍ତର", "ବ୍ୟାଖ୍ୟା", "ଓଡ଼ିଆରେ ଅନୁବାଦିତ ପ୍ରଶ୍ନପତ୍ର"),
        "tamil":  ("பதில்", "விரிவுரை", "தமிழில் மொழிபெயர்த்த கேள்வித்தாள்"),
        "kannada":("ಉತ್ತರ", "ವಿವರಣೆ", "ಕನ್ನಡದಲ್ಲಿ ಅನುವಾದಿತ ಪ್ರಶ್ನೆ ಪತ್ರಿಕೆ")
    }
    ans_label, exp_label, title_label = lang_labels.get(lang, lang_labels["telugu"])

    css = f"""
    {font_face}
    html, body {{
        margin: 0; padding: 0;
        font-family: {body_font};
        font-size: 13pt;
        line-height: 1.6;
        color: #111;
    }}
    h1 {{ text-align:center; color:#003366; font-size:18pt; margin-bottom:20px; }}
    h2 {{ color:#001c80; font-size:15pt; margin:10px 0 5px 0; }}
    p {{ margin: 0 0 6pt 0; white-space: pre-wrap; }}
    .question {{ margin-bottom: 18pt; border-bottom:1px solid #ccc; padding-bottom:8pt; }}
    """

    parts = ["<!doctype html><html><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width, initial-scale=1'>",
             f"<style>{css}</style></head><body>",
             f"<h1>{title_label}</h1>"]

    suffix = f"_{lang}"
    for i, item in enumerate(pages, start=1):
        q_no = clean(item.get("question_number", str(i)))
        q_text = clean(item.get(f"question_text{suffix}", "")) or clean(item.get("question_text", ""))
        ans = clean(item.get(f"answer{suffix}", "")) or clean(item.get("answer", ""))
        exp = clean(item.get(f"explanation{suffix}", "")) or clean(item.get("explanation", ""))

        if not (q_text or ans or exp):
            continue

        parts.append("<div class='question'>")
        parts.append(f"<h2>Q{q_no}.</h2>")
        if q_text:
            parts.append(f"<p>{q_text}</p>")
        if ans:
            parts.append(f"<p><b>{ans_label}:</b> {ans}</p>")
        if exp:
            parts.append(f"<p><b>{exp_label}:</b> {exp}</p>")
        parts.append("</div>")

    parts.append("</body></html>")
    return "\n".join(parts)

async def render_pdf_from_data(data, lang, output_pdf):
    print(f"📊 Rendering {len(data)} items to PDF...")
    html_doc = build_html(data, lang)
    print(f"📝 HTML generated: {len(html_doc)} characters")
    
    tmpdir = tempfile.mkdtemp()
    html_path = os.path.join(tmpdir, "doc.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"✅ HTML saved to temp file: {html_path}")

    try:
        print("🌐 Starting Playwright PDF rendering...")
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch()
                print("✅ Chromium browser launched")
            except Exception as launch_error:
                error_msg = str(launch_error)
                if "Executable doesn't exist" in error_msg or "playwright install" in error_msg.lower():
                    print("⚠️ Playwright Chromium browser not found. Attempting to install...")
                    try:
                        import subprocess
                        import sys
                        # Try to install Playwright browsers
                        result = subprocess.run(
                            [sys.executable, "-m", "playwright", "install", "chromium"],
                            capture_output=True,
                            text=True,
                            timeout=300  # 5 minute timeout
                        )
                        if result.returncode == 0:
                            print("✅ Playwright Chromium installed successfully. Retrying...")
                            browser = await p.chromium.launch()
                        else:
                            raise Exception(
                                f"Failed to install Playwright Chromium.\n"
                                f"Error: {result.stderr}\n"
                                f"Please run 'playwright install chromium' manually.\n"
                                f"On Render, ensure your build command includes: playwright install chromium"
                            )
                    except subprocess.TimeoutExpired:
                        raise Exception(
                            "Playwright Chromium installation timed out.\n"
                            "Please run 'playwright install chromium' manually."
                        )
                    except Exception as install_error:
                        raise Exception(
                            f"Failed to install Playwright Chromium: {install_error}\n"
                            f"Original error: {launch_error}\n"
                            f"Please ensure Playwright browsers are installed:\n"
                            f"  - Run: playwright install chromium\n"
                            f"  - Or check Render build command includes: playwright install chromium"
                        )
                else:
                    # Re-raise if it's a different error
                    raise
            
            page = await browser.new_page()
            print("✅ New page created")
            
            html_uri = pathlib.Path(html_path).resolve().as_uri()
            print(f"📄 Loading HTML from: {html_uri}")
            await page.goto(html_uri)
            print("✅ HTML loaded in browser")
            
            # Wait for fonts to load
            await page.wait_for_timeout(1000)
            print("✅ Waited for fonts to load")
            
            await page.pdf(path=output_pdf, format="A4", margin={"top":"1cm","right":"1cm","bottom":"1cm","left":"1cm"}, print_background=True)
            print(f"✅ PDF generated")
            
            await browser.close()
            print(f"✅ Browser closed")
            
            # Verify PDF was created
            if os.path.exists(output_pdf):
                pdf_size = os.path.getsize(output_pdf)
                print(f"✅ PDF rendered → {output_pdf} ({pdf_size} bytes)")
                
                if pdf_size < 50000:
                    print(f"⚠️ Warning: PDF is quite small ({pdf_size} bytes) - might be incomplete")
            else:
                print(f"❌ Warning: PDF file not found at {output_pdf}")
            
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Playwright PDF rendering failed: {error_msg}")
        print("⚠️ Falling back to ReportLab (limited font support)...")
        
        # Try ReportLab fallback
        try:
            render_pdf_reportlab_fallback(data, lang, output_pdf)
            print(f"✅ PDF rendered using ReportLab fallback → {output_pdf}")
            return
        except Exception as fallback_error:
            print(f"❌ ReportLab fallback also failed: {fallback_error}")
            raise Exception(
                f"Failed to render PDF with both Playwright and ReportLab.\n\n"
                f"Playwright error: {error_msg}\n"
                f"ReportLab error: {fallback_error}\n\n"
                f"Troubleshooting:\n"
                f"  1. Ensure your Render build command includes: playwright install chromium\n"
                f"  2. Or run locally: playwright install chromium\n"
                f"  3. Check that fonts exist in fonts/ directory"
            ) from fallback_error


def render_pdf_reportlab_fallback(data, lang, output_pdf):
    """Fallback PDF rendering using ReportLab (limited Indic font support)"""
    # Font mapping for ReportLab (use same FONTS_DIR as defined above)
    font_map = {
        "hindi": ("TiroDevanagariHindi", str(FONTS_DIR / "TiroDevanagariHindi-Regular.ttf")),
        "odia": ("NotoSansOriya", str(FONTS_DIR / "NotoSansOriya-Regular.ttf")),
        "telugu": ("NotoSansTelugu", str(FONTS_DIR / "NotoSansTelugu-Regular.ttf")),
        "tamil": ("NotoSansTamil", str(FONTS_DIR / "NotoSansTamil-Regular.ttf")),
        "kannada": ("NotoSansKannada", str(FONTS_DIR / "NotoSansKannada-Regular.ttf")),
    }
    
    font_name, font_file = font_map.get(lang.lower(), ("Helvetica", None))
    
    # Register font if available
    if font_file and os.path.exists(font_file):
        try:
            pdfmetrics.registerFont(TTFont(font_name, font_file))
            print(f"✅ Registered font: {font_name}")
        except Exception as font_error:
            print(f"⚠️ Failed to register font {font_name}: {font_error}")
            font_name = "Helvetica"
    else:
        font_name = "Helvetica"
        print(f"⚠️ Font file not found for {lang}, using Helvetica")
    
    # Create PDF with ReportLab
    c = canvas.Canvas(output_pdf, pagesize=A4)
    c.setFont(font_name, 13)
    width, height = A4
    y = height - 80
    
    # Labels
    lang_labels = {
        "telugu": ("సమాధానం", "వివరణ", "తెలుగులో అనువదించిన ప్రశ్నపత్రం"),
        "hindi":  ("उत्तर", "व्याख्या", "हिंदी में अनुवादित प्रश्नपत्र"),
        "odia":   ("ଉତ୍ତର", "ବ୍ୟାଖ୍ୟା", "ଓଡ଼ିଆରେ ଅନୁବାଦିତ ପ୍ରଶ୍ନପତ୍ର"),
    }
    ans_label, exp_label, title_label = lang_labels.get(lang.lower(), lang_labels.get("hindi", ("Answer", "Explanation", "Translated Question Paper")))
    
    # Title
    c.setFont(font_name, 18)
    c.drawCentredString(width / 2, y, title_label)
    y -= 40
    
    # Render each item
    suffix = f"_{lang.lower()}"
    for i, item in enumerate(data, start=1):
        if y < 100:  # New page if needed
            c.showPage()
            c.setFont(font_name, 13)
            y = height - 80
        
        q_no = clean(item.get("question_number", str(i)))
        q_text = clean(item.get(f"question_text{suffix}", "")) or clean(item.get("question_text", ""))
        ans = clean(item.get(f"answer{suffix}", "")) or clean(item.get("answer", ""))
        exp = clean(item.get(f"explanation{suffix}", "")) or clean(item.get("explanation", ""))
        
        if not (q_text or ans or exp):
            continue
        
        # Question number
        c.setFont(font_name, 14)
        c.drawString(60, y, f"Q{q_no}.")
        y -= 25
        
        # Question text
        if q_text:
            c.setFont(font_name, 12)
            lines = q_text.split('\n')
            for line in lines:
                if y < 80:
                    c.showPage()
                    c.setFont(font_name, 12)
                    y = height - 80
                c.drawString(80, y, line[:85])  # Limit line length
                y -= 18
        
        # Answer
        if ans:
            c.setFont(font_name, 12)
            if y < 80:
                c.showPage()
                c.setFont(font_name, 12)
                y = height - 80
            c.drawString(80, y, f"{ans_label}: {ans[:80]}")
            y -= 18
        
        # Explanation
        if exp:
            c.setFont(font_name, 11)
            exp_lines = exp.split('\n')
            for line in exp_lines:
                if y < 80:
                    c.showPage()
                    c.setFont(font_name, 11)
                    y = height - 80
                c.drawString(80, y, f"{exp_label}: {line[:75]}")
                y -= 16
        
        y -= 10  # Spacing between questions
    
    c.save()

# -------------------------
# Main CLI flow
# -------------------------
def main():
    print("\n" + "="*60)
    print("   Unified PDF Question Solver & Translator (NO OCR)")
    print("="*60 + "\n")
    
    # Check fonts at startup
    check_fonts()
    
    # Get and validate input PDF path
    input_pdf = input("Enter path to input PDF (or drag & drop): ").strip()
    # Remove quotes that might be added from drag-and-drop on Windows
    input_pdf = input_pdf.strip('"').strip("'")
    
    if not input_pdf:
        print("❌ No file path provided. Exiting.")
        return
    
    if not os.path.exists(input_pdf):
        print(f"❌ File not found: {input_pdf}")
        print("   Please check the path and try again.")
        return
    
    if not input_pdf.lower().endswith('.pdf'):
        print(f"⚠️ Warning: File doesn't have .pdf extension: {input_pdf}")
        proceed = input("Continue anyway? (y/n): ").strip().lower()
        if proceed != 'y':
            return

    print("\nChoose translation language:")
    for k, v in LANGUAGES.items():
        print(f"  {k}. {v}")
    choice = input("Enter language number (default 1 - Telugu): ").strip() or "1"
    target_lang = LANGUAGES.get(choice, "Telugu")
    lang_lower = target_lang.lower()
    
    print(f"\n✅ Selected language: {target_lang}")
    print(f"✅ Input PDF: {input_pdf}\n")

    try:
        # 1) Extract
        print("="*60)
        print("STEP 1/4: Extracting PDF (text + images)")
        print("="*60)
        pages = extract_pdf(input_pdf, output_json="extracted_data.json", output_image_folder="extracted_images")
        
        if not pages:
            print("❌ No pages extracted from PDF. Exiting.")
            return

        # 2) Solve
        print("\n" + "="*60)
        print("STEP 2/4: Solving extracted content")
        print("="*60)
        solved = solve_pages(pages)
        
        if not solved:
            print("⚠️ No questions were solved. Please check if the PDF contains solvable questions.")
            return

        # 3) Translate
        print("\n" + "="*60)
        print(f"STEP 3/4: Translating to {target_lang}")
        print("="*60)
        translated = translate_items(solved, target_lang)
        
        if not translated:
            print("⚠️ Translation failed. Using original solved data.")
            translated = solved

        # 4) Render PDF
        print("\n" + "="*60)
        print("STEP 4/4: Rendering final PDF")
        print("="*60)
        output_pdf_name = f"final_output_{lang_lower}.pdf"
        asyncio.run(render_pdf_from_data(translated, lang_lower, output_pdf_name))

        print("\n" + "="*60)
        print("🎉 SUCCESS! Pipeline completed.")
        print("="*60)
        print(f"📁 Final PDF: {output_pdf_name}")
        print("📁 Intermediate files: outputs/ folder")
        print("📁 Extracted images: extracted_images/ folder")
        print("\nIf you want images embedded in the PDF, let me know!\n")
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Process interrupted by user. Exiting...")
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        print("\nTroubleshooting:")
        print("  1. Check your GENAI_API_KEY in .env file")
        print("  2. Ensure PDF is not corrupted")
        print("  3. Check internet connection for API calls")
        print("  4. Run: playwright install chromium")
        import traceback
        print("\nFull error details:")
        traceback.print_exc()

if __name__ == "__main__":
    main()