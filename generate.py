import os
import re
import tempfile
import pathlib
import html
import asyncio
from dotenv import load_dotenv
import google.generativeai as genai
from PyPDF2 import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from playwright.async_api import async_playwright
# ======================================================
# LOAD GEMINI API KEY
# ======================================================
load_dotenv()
# Support both GEMINI_API_KEY and GENAI_API_KEY for compatibility
api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GENAI_API_KEY")

if not api_key:
    raise ValueError("ERROR: GEMINI_API_KEY or GENAI_API_KEY not found in environment variables!")

genai.configure(api_key=api_key)

# ======================================================
# PDF TEXT EXTRACTION FUNCTION
# ======================================================
def extract_text_from_pdf(pdf_path):
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text.strip()

# ======================================================
# GEMINI CALL FUNCTION
# ======================================================
def generate_mcqs(pdf_path, n, language):
    pdf_text = extract_text_from_pdf(pdf_path)

    if not pdf_text:
        raise ValueError("ERROR: No readable text found in the PDF! Make sure it's not just scanned images.")

    prompt = f"""You are an expert exam question generator. Read the following document carefully and generate exactly {n} NEW MCQs.

CRITICAL FORMATTING RULES:
1. Write EVERYTHING in {language} language only - NO English translations or mixed language
2. Each question MUST have exactly 4 options: A, B, C, D
3. Format each question EXACTLY like this example:

1. [Question text here]
A) [Option A text]
B) [Option B text]  
C) [Option C text]
D) [Option D text]
Answer: B

2. [Next question text here]
A) [Option A text]
B) [Option B text]
C) [Option C text]
D) [Option D text]
Answer: C

[Continue for all {n} questions...]

IMPORTANT:
- Start each question with a number followed by a period (1., 2., 3., etc.)
- Use proper spacing between questions and options
- For Indic languages like Telugu, Hindi, Odia: ensure proper spacing between words
- Write only one question per line
- Each option on its own line
- Keep questions concise and professionally written
- Base questions strictly on the document content below

Document content:
{pdf_text[:10000]}

Now generate {n} MCQs following the format above EXACTLY:"""

    model = genai.GenerativeModel("gemini-2.5-pro")
    response = model.generate_content(prompt)
    text = response.text
    
    return text

# ======================================================
# GET SCRIPT DIRECTORY FOR FONTS
# ======================================================
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
FONTS_DIR = SCRIPT_DIR / "fonts"

def clean_text_html(s):
    """Clean text for HTML display"""
    if not s:
        return ""
    s = html.escape(str(s))
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").strip()

def parse_mcq_text(text):
    """Parse MCQ text into structured format - improved version"""
    # Try to add line breaks where questions start
    text = re.sub(r'(\d+)\.', r'\n\1.', text)
    
    questions = []
    lines = text.split('\n')
    
    current_q = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check if this is a question number
        match = re.match(r'^(\d+)\.\s*(.*)', line)
        if match:
            if current_q:
                questions.append(current_q)
            current_q = {
                'number': match.group(1),
                'content': match.group(2),
                'parts': [],
                'options': [],
                'answer': None
            }
        elif current_q:
            # Check if this is an answer
            if line.startswith('Answer:') or re.match(r'^Answer\s*[:=]\s*([A-Z0-9]+)', line, re.IGNORECASE):
                answer_match = re.search(r'Answer\s*[:=]\s*([A-Z0-9]+)', line, re.IGNORECASE)
                if answer_match:
                    current_q['answer'] = f"Answer: {answer_match.group(1)}"
                else:
                    current_q['answer'] = line
                # End this question
                if current_q['parts']:
                    current_q['content'] += '<br>' + '<br>'.join(current_q['parts'])
                questions.append(current_q)
                current_q = None
            # Check if this is an option (A), B), C), D) or 1), 2), 3), 4), 5))
            elif re.match(r'^[A-E]\)|^[1-5]\)', line, re.IGNORECASE):
                # This is an option line
                if not current_q.get('options'):
                    current_q['options'] = []
                current_q['options'].append(line)
            else:
                # Add to current question parts (question text or continuation)
                if line:
                    # If we already have options, this might be more options on the same line
                    if current_q.get('options') and re.search(r'[A-E]\)|[1-5]\)', line, re.IGNORECASE):
                        # Split line by option markers
                        option_parts = re.split(r'([A-E]\)|[1-5]\))', line)
                        for i in range(1, len(option_parts), 2):
                            if i < len(option_parts):
                                opt_marker = option_parts[i]
                                opt_text = option_parts[i+1].strip() if i+1 < len(option_parts) else ""
                                if opt_marker and opt_text:
                                    if not current_q.get('options'):
                                        current_q['options'] = []
                                    current_q['options'].append(f"{opt_marker} {opt_text}")
                    else:
                        current_q['parts'].append(line)
    
    if current_q:
        if current_q['parts']:
            current_q['content'] += '<br>' + '<br>'.join(current_q['parts'])
        if current_q.get('options'):
            # Add options to content
            current_q['content'] += '<br><br>' + '<br>'.join(current_q['options'])
        questions.append(current_q)
    
    return questions if questions else None

async def save_pdf_playwright(text, outpath, lang):
    """Save PDF using Playwright for better Indic font support"""
    try:
        # Build HTML with fonts
        font_file_map = {
            "English": None,
            "Telugu": str(FONTS_DIR / "NotoSansTelugu-Regular.ttf"),
            "Hindi": str(FONTS_DIR / "TiroDevanagariHindi-Regular.ttf"),
            "Odia": str(FONTS_DIR / "NotoSansOriya-Regular.ttf"),
        }
        
        font_file = font_file_map.get(lang, None)
        font_face = ""
        
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
            body_font = "sans-serif"
        
        css = f"""
        {font_face}
        html, body {{
            margin: 0; padding: 20px;
            font-family: {body_font};
            font-size: 12pt;
            line-height: 1.8;
            color: #000;
        }}
        h1 {{ text-align: center; margin-bottom: 30px; font-size: 18pt; }}
        .question {{
            margin-bottom: 25px;
            padding: 15px;
            border-bottom: 1px solid #ddd;
        }}
        .question-number {{
            font-weight: bold;
            font-size: 13pt;
            margin-bottom: 8px;
            color: #003366;
        }}
        .question-content {{
            margin: 8px 0;
        }}
        .answer {{
            color: #006600;
            font-weight: bold;
            margin-top: 8px;
            font-size: 11pt;
        }}
        """
        
        # Parse MCQ text into structured format
        clean_text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        clean_text = clean_text.replace("—", "-").replace("–", "-")
        
        # Parse MCQs properly
        questions = parse_mcq_text(clean_text)
        
        if questions:
            # Build structured HTML for each question
            content_parts = []
            for q in questions:
                q_html = f'<div class="question">'
                # Question number
                q_html += f'<div class="question-number">Q{q["number"]}.</div>'
                # Question content
                q_html += f'<div class="question-content">{q["content"]}</div>'
                # Options (if separate from content)
                if q.get("options") and len(q["options"]) > 0:
                    options_html = '<div style="margin: 8px 0;"><strong>Options:</strong><br>'
                    for opt in q["options"]:
                        options_html += f'<span style="margin-right: 15px;">{opt}</span><br>'
                    options_html += '</div>'
                    q_html += options_html
                # Answer
                if q.get("answer"):
                    # Extract just the answer letter/number
                    answer_match = re.search(r'Answer\s*[:=]\s*([A-Z0-9]+)', q["answer"], re.IGNORECASE)
                    if answer_match:
                        answer_val = answer_match.group(1)
                        q_html += f'<div class="answer">Answer: {answer_val}</div>'
                    else:
                        q_html += f'<div class="answer">{q["answer"]}</div>'
                q_html += '</div>'
                content_parts.append(q_html)
            content_html = '\n'.join(content_parts)
        else:
            # Fallback to plain text if parsing fails
            clean_text_html_output = clean_text_html(clean_text).replace('\n', '<br>')
            content_html = f'<div style="white-space: pre-wrap;">{clean_text_html_output}</div>'
        
        html_content = f"""
        <!doctype html>
        <html>
        <head>
            <meta charset='utf-8'>
            <meta name='viewport' content='width=device-width, initial-scale=1'>
            <style>{css}</style>
        </head>
        <body>
            <h1>Generated MCQs - {lang}</h1>
            {content_html}
        </body>
        </html>
        """
        
        # Save HTML temporarily
        tmpdir = tempfile.mkdtemp()
        html_path = os.path.join(tmpdir, "mcqs.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        # Render PDF with Playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(pathlib.Path(html_path).resolve().as_uri())
            await page.pdf(
                path=outpath,
                format="A4",
                margin={"top": "1cm", "right": "1cm", "bottom": "1cm", "left": "1cm"},
                print_background=True
            )
            await browser.close()
        
        return True
    except Exception as e:
        print(f"Playwright rendering failed: {e}. Trying ReportLab fallback...")
        return False

def save_pdf_reportlab(text, outpath, lang):
    """Fallback to ReportLab for PDF generation"""

    clean_text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    clean_text = clean_text.replace("—", "-").replace("–", "-")

    # Language-wise font mapping
    font_map = {
        "English": ("Helvetica", None),
        "Telugu": ("NotoSansTelugu", "fonts/NotoSansTelugu-Regular.ttf"),
        "Hindi": ("NotoSansDevanagari", "fonts/NotoSansDevanagari-Regular.ttf"),
        "Odia": ("NotoSansOriya", "fonts/NotoSansOriya-Regular.ttf"),
    }

    font_name, font_file = font_map.get(lang, ("Helvetica", None))
    if font_file and os.path.exists(font_file):
        pdfmetrics.registerFont(TTFont(font_name, font_file))
    else:
        font_name = "Helvetica"

    c = canvas.Canvas(outpath, pagesize=A4)
    c.setFont(font_name, 13)
    width, height = A4
    y = height - 80
    max_chars_per_line = 85

    for line in clean_text.split("\n"):
        line = line.strip()
        if not line:
            y -= 15
            continue

        while len(line) > max_chars_per_line:
            part = line[:max_chars_per_line]
            c.drawString(60, y, part)
            y -= 20
            line = line[max_chars_per_line:]
            if y < 60:
                c.showPage()
                c.setFont(font_name, 13)
                y = height - 80

        if line:
            c.drawString(60, y, line)
            y -= 20

        if y < 60:
            c.showPage()
            c.setFont(font_name, 13)
            y = height - 80

    c.save()
    return os.path.exists(outpath)

def save_pdf(text, outpath, lang):
    """Unified PDF generation with Playwright and ReportLab fallback"""
    # Try Playwright first
    try:
        if asyncio.run(save_pdf_playwright(text, outpath, lang)):
            return True
    except Exception as e:
        print(f"Playwright failed: {e}. Using ReportLab fallback...")
    
    # Fallback to ReportLab
    return save_pdf_reportlab(text, outpath, lang)

# ======================================================
# MAIN EXECUTION
# ======================================================
if __name__ == "__main__":
    print("✅ Gemini API Key loaded successfully!\n")
    
    # Get inputs from user
    pdf_path = input("📂 Enter your PDF file path: ").strip()
    if not os.path.exists(pdf_path):
        raise FileNotFoundError("⚠️ File not found! Please enter a valid PDF path.")
    
    num_qs = int(input("🧮 How many MCQs to generate?: ").strip())
    
    languages = ["English", "Telugu", "Hindi", "Odia"]
    print("\n🌐 Available Languages:")
    for i, lang in enumerate(languages, 1):
        print(f"{i}. {lang}")
    
    choice = int(input("\n👉 Enter the number of your language choice: ").strip())
    if choice < 1 or choice > len(languages):
        raise ValueError("Invalid choice! Please select a valid option.")
    
    lang = languages[choice - 1]
    
    print("\n🧠 Generating MCQs using Gemini 2.5 Pro... please wait\n")
    mcqs = generate_mcqs(pdf_path, num_qs, lang)

    if mcqs:
        output_pdf = f"Generated_MCQs_{lang}.pdf"
        ok = save_pdf(mcqs, output_pdf, lang)

        if ok:
            print(f"\n✅ {lang} PDF generated successfully: {output_pdf}")
        else:
            print("\n❌ Failed to create PDF.")
    else:
        print("\n⚠️ No MCQs generated.")
