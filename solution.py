#!/usr/bin/env python3
# pipeline_no_ocr.py
"""
Unified pipeline (NO OCR):
1) Extract text + images from input PDF (PyMuPDF)
2) Solve equations via SymPy (simple) or fallback to Gemini LLM for MCQs
3) Translate solved items into selected language via Gemini
4) Render final translated JSON -> PDF via Playwright
Notes:
- Final PDF contains translated text (no images embedded).
- Requires GENAI_API_KEY and GENAI_MODEL in a .env file.
"""
import os
import json
import re
import tempfile
import pathlib
import html
import asyncio
import time
from dotenv import load_dotenv
from tqdm import tqdm

# PDF extraction
import fitz  # PyMuPDF

# solving
from sympy import symbols, Eq, solve
import google.generativeai as genai

# pdf rendering
from playwright.async_api import async_playwright
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# -------------------------
# Load environment
# -------------------------
load_dotenv()
API_KEY = os.getenv("GENAI_API_KEY")
MODEL_NAME = os.getenv("GENAI_MODEL", "models/gemini-2.5-flash")

if not API_KEY:
    print("ERROR: Please set GENAI_API_KEY in a .env file in this folder.")
    print("Example .env contents:")
    print("GENAI_API_KEY=your_gemini_api_key_here")
    print("GENAI_MODEL=models/gemini-2.5-flash")
    raise SystemExit(1)

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel(MODEL_NAME)

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
    
    # Try to extract from markdown code blocks first
    match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if match:
        inner = match.group(1)
        try:
            return json.loads(inner)
        except Exception:
            pass
    
    # Try to parse the entire text as JSON (for plain JSON responses)
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    
    # Try to find JSON object in text (fallback)
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    
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
        lhs = re.sub(r"(?<=\d)x", "*x", lhs)
        rhs = re.sub(r"(?<=\d)x", "*x", rhs)
        # attempt to evaluate both sides as Python expressions (works for simple numeric forms)
        eq = Eq(eval(lhs), eval(rhs))
        solution = solve(eq, x)
        return solution
    except Exception:
        return None

# -------------------------
# Extraction (no OCR)
# -------------------------
def extract_pdf(input_pdf, output_json="extracted_data.json", output_image_folder="extracted_images"):
    os.makedirs(output_image_folder, exist_ok=True)
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
                print(f"Failed to save image page{page_number+1}_img{img_index+1}: {ie}")
                continue

        page_data = {
            "page": page_number + 1,
            "text": text.strip(),
            "images": images
        }
        all_pages_data.append(page_data)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(all_pages_data, f, ensure_ascii=False, indent=2)

    print(f"Extraction complete. Saved to '{output_json}'")
    return all_pages_data

# -------------------------
# Solver (SymPy first, LLM fallback)
# -------------------------
def solve_pages(pages):
    results = []
    for page in tqdm(pages, desc="Solving pages"):
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
                response = model.generate_content(prompt)
                explanation = (response.text or "").strip()
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
        prompt = f"""You are an expert exam solver. Extract and solve ALL questions and MCQs from the text below.

For each question found:
- question_number: The question number if present
- question_text: The complete question text as written
- answer: The correct answer (option letter like A, B, C, D or the answer text)
- explanation: A concise 2-line explanation of why this answer is correct

CRITICAL: Return ONLY a JSON array (no markdown, no code blocks, no other text).
Example format:
[
  {{"question_number": "1", "question_text": "...", "answer": "A", "explanation": "..."}},
  {{"question_number": "2", "question_text": "...", "answer": "B", "explanation": "..."}}
]

Input text:
{text}
"""
        try:
            response = model.generate_content(prompt)
            raw_output = extract_json_block(response.text)
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
    print(f"Solving complete. Saved to '{solved_path}'")
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
    lang_lower = target_lang.lower()
    translated = []
    for idx, item in enumerate(tqdm(items, desc=f"Translating → {target_lang}")):
        q = item.get("question_text", "")
        a = item.get("answer", "")
        e = item.get("explanation", "")

        # Add small delay between requests to avoid rate limits (except first request)
        if idx > 0:
            time.sleep(0.5)

        prompt = f"""Translate the following solved MCQ into {target_lang}. Keep all numbers, symbols, and math expressions unchanged.

IMPORTANT: For Indic languages ({target_lang}), ensure proper spacing between words.

CRITICAL: You must return ONLY valid JSON (no markdown, no code blocks, no explanations). The response must start with {{ and end with }}.

Required JSON format (copy this structure exactly):
{{
  "question_text_{lang_lower}": "translated question with proper spacing",
  "answer_{lang_lower}": "translated answer with proper spacing",  
  "explanation_{lang_lower}": "translated explanation with proper spacing"
}}

Original Question: {q}
Original Answer: {a}
Original Explanation: {e}

Return the translation as JSON only:"""
        
        # Retry logic for rate limits
        max_retries = 3
        retry_delay = 2
        success = False
        
        for attempt in range(max_retries):
            try:
                response = model.generate_content(prompt)
                response_text = response.text.strip()
                parsed = extract_inner_json(response_text)
                
                if parsed:
                    # Successfully parsed JSON
                    merged = {**item, **parsed}
                    translated.append(merged)
                    success = True
                    break
                else:
                    # JSON parsing failed, try to extract fields from raw response
                    print(f"Warning: Failed to parse JSON for question {item.get('question_number', '?')}. Attempting fallback extraction...")
                    
                    # Try to extract translated fields using regex patterns
                    fallback_parsed = {}
                    q_key = f"question_text_{lang_lower}"
                    a_key = f"answer_{lang_lower}"
                    e_key = f"explanation_{lang_lower}"
                    
                    # Try to find fields in the response text
                    q_match = re.search(rf'"{q_key}"\s*:\s*"([^"]+)"', response_text, re.IGNORECASE)
                    a_match = re.search(rf'"{a_key}"\s*:\s*"([^"]+)"', response_text, re.IGNORECASE)
                    e_match = re.search(rf'"{e_key}"\s*:\s*"([^"]+)"', response_text, re.IGNORECASE)
                    
                    if q_match:
                        fallback_parsed[q_key] = q_match.group(1)
                    if a_match:
                        fallback_parsed[a_key] = a_match.group(1)
                    if e_match:
                        fallback_parsed[e_key] = e_match.group(1)
                    
                    if fallback_parsed:
                        merged = {**item, **fallback_parsed}
                        translated.append(merged)
                        success = True
                        print(f"Successfully extracted translation fields using fallback method.")
                        break
                    else:
                        # Store raw response for debugging
                        merged = {**item, f"raw_translation_{lang_lower}": response_text}
                        translated.append(merged)
                        print(f"Error: Could not extract translation for question {item.get('question_number', '?')}. Raw response stored.")
                        success = True  # Mark as processed to avoid retry
                        break
                        
            except Exception as err:
                error_str = str(err)
                # Check if it's a rate limit error
                if "429" in error_str or "quota" in error_str.lower():
                    if attempt < max_retries - 1:
                        print(f"Rate limit hit for question {item.get('question_number', '?')}, waiting {retry_delay}s before retry...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        item[f"translation_error_{lang_lower}"] = "Max retries exceeded for rate limit"
                        translated.append(item)
                        print(f"Error: Translation failed for question {item.get('question_number', '?')} after {max_retries} retries due to rate limit.")
                        break
                else:
                    # Not a rate limit error, don't retry
                    item[f"translation_error_{lang_lower}"] = str(err)
                    translated.append(item)
                    print(f"Error: Translation failed for question {item.get('question_number', '?')}: {err}")
                    break
        
        if not success and f"translation_error_{lang_lower}" not in item:
            item[f"translation_error_{lang_lower}"] = "Translation failed after retries"
            translated.append(item)
            print(f"Error: Translation failed for question {item.get('question_number', '?')} after all retries.")

    out_file = os.path.join("outputs", f"translated_{lang_lower}_auto.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(translated, f, ensure_ascii=False, indent=2)
    print(f"Translation complete. Saved to '{out_file}'")
    return translated

# -------------------------
# JSON -> PDF (Playwright rendering)
# -------------------------
# Get script directory for relative font paths
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
FONTS_DIR = SCRIPT_DIR / "fonts"

FONTS = {
    "telugu": str(FONTS_DIR / "NotoSansTelugu-Regular.ttf"),
    "hindi":  str(FONTS_DIR / "TiroDevanagariHindi-Regular.ttf"),
    "odia":   str(FONTS_DIR / "AnekOdia-Regular.ttf"),
    "tamil":  str(FONTS_DIR / "NotoSansTamil-Regular.ttf"),
    "kannada": str(FONTS_DIR / "NotoSansKannada-Regular.ttf"),
}

# FONT REGISTRATION FUNCTION - ADDED
def register_reportlab_fonts():
    """Register all fonts with ReportLab"""
    for lang, font_path in FONTS.items():
        if os.path.exists(font_path):
            try:
                font_name = lang.capitalize()
                pdfmetrics.registerFont(TTFont(font_name, font_path))
                print(f"Registered font: {font_name}")
            except Exception as e:
                print(f"Failed to register {lang}: {e}")

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
    font_file = FONTS.get(lang, None)
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
        body_font = "LangFont, sans-serif"
    else:
        font_face = ""
        body_font = "sans-serif"

    lang_labels = {
        "telugu": ("సమాధానం", "వివరణ", "తెలుగులో అనువదించిన ప్రశ్నపత్రం"),
        "hindi":  ("उत्तर", "व्याख्या", "हिंदी में अनुवादित प्रश्नपत्र"),
        "odia":   ("ଉତ୍ତର", "ବ୍ୟାଖ୍ୟା", "ଓଡ଼ିଆରେ ଅନୁବାଦିତ ପ୍ରଶ୍ନପତ୍ର"),
        "tamil":  ("பதில்", "விரிவுரை", "தமிழில் மொழிபெயர்த்த கேள்வித்தாள்"),
        "kannada":("ಉತ್ತರ", "ವಿವರಣೆ", "ಕನ್ನಡದಲ್ಲಿ ಅನುವಾದಿತ ಪ್ರಶ್ನೆ ಪತ್ರಿಕೆ"),
        "english": ("Answer", "Explanation", "Translated Question Paper in English")
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

async def render_pdf_from_data_playwright(data, lang, output_pdf):
    """Render PDF using Playwright"""
    html_doc = build_html(data, lang)
    tmpdir = tempfile.mkdtemp()
    html_path = os.path.join(tmpdir, "doc.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(pathlib.Path(html_path).resolve().as_uri())
        await page.pdf(path=output_pdf, format="A4", margin={"top":"1cm","right":"1cm","bottom":"1cm","left":"1cm"}, print_background=True)
        await browser.close()

    return True

def draw_wrapped_text(c, text, x, y, width, font_name, font_size):
    """Draw text with automatic wrapping"""
    words = text.split()
    lines = []
    current_line = []
    current_width = 0
    
    # Use regular font for width calculation
    width_font = font_name if font_name else "Helvetica"
    c.setFont(width_font, font_size)
    
    for word in words:
        # Calculate width of word with space
        word_width = c.stringWidth(word + " ", width_font, font_size)
        if current_width + word_width <= width:
            current_line.append(word)
            current_width += word_width
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            current_width = word_width
    
    if current_line:
        lines.append(" ".join(current_line))
    
    # Draw each line
    current_y = y
    for line in lines:
        c.drawString(x, current_y, line)
        current_y -= font_size + 5
    
    return current_y

def render_pdf_from_data_reportlab(data, lang, output_pdf):
    """Fallback to ReportLab for PDF generation"""
    output_path = pathlib.Path(output_pdf)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Register fonts first - FIXED
    register_reportlab_fonts()
    
    # Get correct font name
    font_name = None
    font_file = FONTS.get(lang, None)
    if font_file and os.path.exists(font_file):
        font_name = lang.capitalize()
    
    # Language labels
    lang_labels = {
        "telugu": ("సమాధానం", "వివరణ", "తెలుగులో అనువదించిన ప్రశ్నపత్రం"),
        "hindi":  ("उत्तर", "व्याख्या", "हिंदी में अनुवादित प्रश्नपत्र"),
        "odia":   ("ଉତ୍ତର", "ବ୍ୟାଖ୍ୟା", "ଓଡ଼ିଆରେ ଅନୁବାଦିତ ପ୍ରଶ୍ନପତ୍ର"),
        "tamil":  ("பதில்", "விரிவுரை", "தமிழில் மொழிபெயர்த்த கேள்வித்தாள்"),
        "kannada":("ಉತ್ತರ", "ವಿವರಣೆ", "ಕನ್ನಡದಲ್ಲಿ ಅನುವಾದಿತ ಪ್ರಶ್ನೆ ಪತ್ರಿಕೆ"),
        "english": ("Answer", "Explanation", "Translated Question Paper in English")
    }
    ans_label, exp_label, title_label = lang_labels.get(lang, lang_labels["telugu"])
    
    # Create PDF
    c = canvas.Canvas(str(output_pdf), pagesize=A4)
    width, height = A4
    available_width = width - 140  # Left margin + right margin
    
    # Title with Telugu font for Indic languages
    y = height - 50
    if font_name:
        try:
            c.setFont(font_name, 18)
        except:
            c.setFont("Helvetica-Bold", 18)
    else:
        c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, y, title_label)
    y -= 30
    
    # Process data with proper font handling - FIXED
    suffix = f"_{lang}"
    for i, item in enumerate(data, start=1):
        q_no = clean(item.get("question_number", str(i)))
        q_text = clean(item.get(f"question_text{suffix}", "")) or clean(item.get("question_text", ""))
        ans = clean(item.get(f"answer{suffix}", "")) or clean(item.get("answer", ""))
        exp = clean(item.get(f"explanation{suffix}", "")) or clean(item.get("explanation", ""))
        
        if not (q_text or ans or exp):
            continue
        
        # Check if we need a new page
        if y < 100:
            c.showPage()
            y = height - 50
        
        # Question number (English font)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, f"Q{q_no}.")
        y -= 20
        
        # Question text (Use Telugu font with wrapping)
        if q_text:
            try:
                y = draw_wrapped_text(c, q_text, 70, y, available_width, font_name, 12)
            except Exception as font_error:
                print(f"Font error for question: {font_error}")
                # Fallback to simple rendering
                try:
                    c.setFont("Helvetica", 12)
                    c.drawString(70, y, q_text if lang == "english" else "[Font error]")
                    y -= 15
                except:
                    y -= 15
        
        # Answer (use Telugu font with wrapping)
        if ans:
            try:
                answer_text = f"{ans_label}: {ans}"
                y = draw_wrapped_text(c, answer_text, 70, y - 10, available_width, font_name, 11)
            except Exception as font_error:
                print(f"Font error for answer: {font_error}")
                try:
                    c.setFont("Helvetica-Bold", 11)
                    c.drawString(70, y - 10, f"{ans_label}: {ans}")
                    y -= 15
                except:
                    y -= 15
        
        # Explanation (use Telugu font with wrapping)
        if exp:
            try:
                exp_text = f"{exp_label}: {exp}"
                y = draw_wrapped_text(c, exp_text, 70, y - 10, available_width, font_name, 10)
            except Exception as font_error:
                print(f"Font error for explanation: {font_error}")
                try:
                    c.setFont("Helvetica", 10)
                    c.drawString(70, y - 10, f"{exp_label}: {exp}")
                    y -= 20
                except:
                    y -= 20
        
        y -= 10
    
    c.save()
    return True

async def render_pdf_from_data(data, lang, output_pdf):
    """Unified PDF generation with Playwright and ReportLab fallback"""
    # Register fonts at the start - ADDED
    register_reportlab_fonts()
    
    try:
        # Try Playwright first
        if await render_pdf_from_data_playwright(data, lang, output_pdf):
            print(f"PDF rendered with Playwright → {output_pdf}")
            return
    except Exception as e:
        print(f"Playwright rendering failed: {e}. Trying ReportLab fallback...")
    
    # Fallback to ReportLab
    if render_pdf_from_data_reportlab(data, lang, output_pdf):
        print(f"PDF rendered with ReportLab → {output_pdf}")
    else:
        print(f"PDF rendering failed for {output_pdf}")

# -------------------------
# Main CLI flow
# -------------------------
def main():
    print("\n--- Unified pipeline (NO OCR) ---\n")
    input_pdf = input("Enter path to input PDF (or drag & drop): ").strip()
    if not input_pdf or not os.path.exists(input_pdf):
        print("ERROR: Invalid PDF path. Exiting.")
        return

    print("\nChoose translation language:")
    for k, v in LANGUAGES.items():
        print(f"{k}. {v}")
    choice = input("Enter language number (default 1 - Telugu): ").strip() or "1"
    target_lang = LANGUAGES.get(choice, "Telugu")
    lang_lower = target_lang.lower()

    # 1) Extract
    print("\nExtracting PDF (text + images) ...")
    pages = extract_pdf(input_pdf, output_json="extracted_data.json", output_image_folder="extracted_images")

    # 2) Solve
    print("\nSolving extracted content ...")
    solved = solve_pages(pages)

    # 3) Translate
    print(f"\nTranslating solved content → {target_lang} ...")
    translated = translate_items(solved, target_lang)

    # 4) Render PDF
    print("\nRendering final PDF ...")
    output_pdf_name = f"final_output_{lang_lower}.pdf"
    asyncio.run(render_pdf_from_data(translated, lang_lower, output_pdf_name))

    print("\nAll done! Check the 'outputs' folder for intermediate JSON files and the final PDF.")
    print("If you want images embedded in the PDF later, tell me and I will add that feature.\n")

if __name__ == "__main__":
    main()