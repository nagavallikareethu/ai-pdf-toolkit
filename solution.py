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
            response = model.generate_content(prompt)
            parsed = extract_inner_json(response.text.strip())
            if parsed:
                merged = {**item, **parsed}
            else:
                merged = {**item, f"raw_translation_{lang_lower}": response.text.strip()}
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
FONTS = {
    "telugu": "NotoSansTelugu-VariableFont_wdth,wght.ttf",
    "hindi":  "NotoSansDevanagari[wdth,wght].ttf",
    "odia":   "NotoSansOriya[wdth,wght].ttf",
    "tamil":  "NotoSansTamil-VariableFont.ttf",
    "kannada":"NotoSansKannada-VariableFont.ttf",
}

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
            font-weight: 100 900;
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
    html_doc = build_html(data, lang)
    tmpdir = tempfile.mkdtemp()
    html_path = os.path.join(tmpdir, "doc.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    try:
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch()
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
            await page.goto(pathlib.Path(html_path).resolve().as_uri())
            await page.pdf(path=output_pdf, format="A4", margin={"top":"1cm","right":"1cm","bottom":"1cm","left":"1cm"}, print_background=True)
            await browser.close()
            print(f"✅ PDF rendered → {output_pdf}")
            
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
    # Font mapping for ReportLab
    BASE_DIR = PathLib(__file__).parent.resolve()
    FONTS_DIR = BASE_DIR / "fonts"
    
    font_map = {
        "hindi": ("NotoSansDevanagari", str(FONTS_DIR / "NotoSansDevanagari-Regular.ttf")),
        "odia": ("NotoSansOriya", str(FONTS_DIR / "NotoSansOriya-Regular.ttf")),
        "telugu": ("NotoSansTelugu", str(FONTS_DIR / "NotoSansTelugu-Regular.ttf")),
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
    print("\n--- Unified pipeline (NO OCR) ---\n")
    input_pdf = input("Enter path to input PDF (or drag & drop): ").strip()
    if not input_pdf or not os.path.exists(input_pdf):
        print("❌ Invalid PDF path. Exiting.")
        return

    print("\nChoose translation language:")
    for k, v in LANGUAGES.items():
        print(f"{k}. {v}")
    choice = input("Enter language number (default 1 - Telugu): ").strip() or "1"
    target_lang = LANGUAGES.get(choice, "Telugu")
    lang_lower = target_lang.lower()

    # 1) Extract
    print("\n🔍 Extracting PDF (text + images) ...")
    pages = extract_pdf(input_pdf, output_json="extracted_data.json", output_image_folder="extracted_images")

    # 2) Solve
    print("\n🧠 Solving extracted content ...")
    solved = solve_pages(pages)

    # 3) Translate
    print(f"\n🌐 Translating solved content → {target_lang} ...")
    translated = translate_items(solved, target_lang)

    # 4) Render PDF
    print("\n📄 Rendering final PDF ...")
    output_pdf_name = f"final_output_{lang_lower}.pdf"
    asyncio.run(render_pdf_from_data(translated, lang_lower, output_pdf_name))

    print("\n🎉 All done! Check the 'outputs' folder for intermediate JSON files and the final PDF.")
    print("If you want images embedded in the PDF later, tell me and I will add that feature.\n")

if __name__ == "__main__":
    main()