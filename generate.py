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

CRITICAL FORMATTING RULES - FOLLOW EXACTLY:
1. Write questions and options in {language} language
2. Use ONLY English labels: "Answer:" (NOT "उत्तर:" or "సమాధానం" or any other language label)
3. Each question MUST have exactly 4 options with English letters: A, B, C, D
4. Format each question EXACTLY like this example (copy this format EXACTLY):

1. [Question text in {language}]
A) [Option A text in {language}]
B) [Option B text in {language}]  
C) [Option C text in {language}]
D) [Option D text in {language}]
Answer: B

2. [Next question text in {language}]
A) [Option A text in {language}]
B) [Option B text in {language}]
C) [Option C text in {language}]
D) [Option D text in {language}]
Answer: C

[Continue for all {n} questions...]

MANDATORY REQUIREMENTS:
- Start each question with a number followed by a period (1., 2., 3., etc.)
- EVERY option MUST start with English letter followed by closing parenthesis: A) B) C) D)
- DO NOT use just ")" without A, B, C, D
- DO NOT use numbers 1), 2), 3), 4) - ONLY use A), B), C), D)
- ALWAYS use "Answer: X" format where X is A, B, C, or D (NOT any other format)
- Write only one question per line
- Each option on its own line (A) on one line, B) on next line, etc.)
- Use proper spacing between questions and options
- For Indic languages like Telugu, Hindi, Odia: ensure proper spacing between words
- Keep questions concise and professionally written
- Base questions strictly on the document content below

EXAMPLE FORMAT - COPY EXACTLY:
1. What is 2+2?
A) 3
B) 4
C) 5
D) 6
Answer: B

Document content:
{pdf_text[:10000]}

Now generate {n} MCQs following the format above EXACTLY. Remember: 
- Use A), B), C), D) for options (NOT just ) or 1), 2), 3), 4))
- Use "Answer: X" format with English label!"""

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
    # Debug: print raw text to see what Gemini is generating
    print(f"\n=== DEBUG: Raw text from Gemini (first 1000 chars) ===")
    print(text[:1000])
    print("=== END DEBUG ===\n")
    
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
            # Check if this is an answer - handle multiple formats
            # English: "Answer:", "Answer: B", "Answer:B"
            # Hindi: "उत्तर:", "उत्तर: B"
            # Telugu: "సమాధానం:", etc.
            if (line.startswith('Answer:') or 
                re.match(r'^(Answer|उत्तर|సమాధానం|ଉତ୍ତର|பதில்|ಉತ್ತರ)\s*[:=]\s*([A-Z0-9]+)', line, re.IGNORECASE)):
                # Try to extract answer value (A, B, C, D or 1, 2, 3, 4)
                answer_match = re.search(r'(?:Answer|उत्तर|సమాధానం|ଉତ୍ତର|பதில்|ಉತ್ತर)\s*[:=]\s*([A-Z0-9]+)', line, re.IGNORECASE)
                if answer_match:
                    current_q['answer'] = f"Answer: {answer_match.group(1)}"
                else:
                    # Fallback: try to find any letter/number after colon/equals
                    fallback_match = re.search(r'[:=]\s*([A-Z0-9]+)', line)
                    if fallback_match:
                        current_q['answer'] = f"Answer: {fallback_match.group(1)}"
                    else:
                        current_q['answer'] = line
                # End this question
                if current_q['parts']:
                    current_q['content'] += '<br>' + '<br>'.join(current_q['parts'])
                questions.append(current_q)
                current_q = None
            # Check if this is an option (A), B), C), D) or 1), 2), 3), 4), 5))
            # More flexible: allow spaces after marker, handle various formats
            elif re.match(r'^[A-E]\)\s*|^[1-5]\)\s*', line, re.IGNORECASE):
                # This is an option line
                if not current_q.get('options'):
                    current_q['options'] = []
                current_q['options'].append(line)
            # Handle lines that start with just ")" - assign sequential letters A, B, C, D
            # Match ") " with space OR ")180" without space
            elif re.match(r'^\)\s*[^\s]', line):
                # Line starts with just ")" followed by non-whitespace - assign option letter based on count
                opt_count = len(current_q.get('options', []))
                if opt_count < 4:
                    option_letter = ['A', 'B', 'C', 'D'][opt_count]
                    # Remove ")" and any whitespace, get remaining text
                    option_text = re.sub(r'^\)\s*', '', line).strip()
                    if option_text and len(option_text) > 0:  # Only add if there's actual text
                        if not current_q.get('options'):
                            current_q['options'] = []
                        current_q['options'].append(f"{option_letter}) {option_text}")
                        print(f"DEBUG: Assigned letter {option_letter} to option line: '{line[:50]}' -> '{option_letter}) {option_text[:50]}'")
                else:
                    # Already have 4 options, might be content - add to parts
                    current_q['parts'].append(line)
            # Check if line contains option markers anywhere (for mixed content)
            elif re.search(r'\b[A-E]\)\s+|\b[1-5]\)\s+', line, re.IGNORECASE):
                # Line contains option markers - extract them
                # Try to split by option markers
                option_parts = re.split(r'(\b[A-E]\)|\b[1-5]\))', line)
                for i in range(1, len(option_parts), 2):
                    if i < len(option_parts):
                        opt_marker = option_parts[i].strip()
                        opt_text = option_parts[i+1].strip() if i+1 < len(option_parts) else ""
                        if opt_marker and opt_text:
                            if not current_q.get('options'):
                                current_q['options'] = []
                            current_q['options'].append(f"{opt_marker} {opt_text}")
                # Also add to parts if there's other content
                if not re.match(r'^[A-E]\)|^[1-5]\)', line, re.IGNORECASE):
                    current_q['parts'].append(line)
            else:
                # Add to current question parts (question text or continuation)
                if line:
                    # Before adding to parts, check if this might be an option starting with ")"
                    # This catches options that might have been missed above
                    if re.match(r'\)\s*[^\s]', line) and len(current_q.get('options', [])) < 4:
                        # This looks like an option line starting with ")"
                        opt_count = len(current_q.get('options', []))
                        if opt_count < 4:
                            option_letter = ['A', 'B', 'C', 'D'][opt_count]
                            option_text = re.sub(r'^\)\s*', '', line).strip()
                            if option_text:
                                if not current_q.get('options'):
                                    current_q['options'] = []
                                current_q['options'].append(f"{option_letter}) {option_text}")
                                print(f"DEBUG: Caught option in else clause: '{line[:50]}' -> '{option_letter}) {option_text[:50]}'")
                            else:
                                current_q['parts'].append(line)
                        else:
                            current_q['parts'].append(line)
                    else:
                        current_q['parts'].append(line)
    
    if current_q:
        if current_q['parts']:
            current_q['content'] += '<br>' + '<br>'.join(current_q['parts'])
        # Try to extract options from content if not found separately
        if not current_q.get('options') or len(current_q['options']) == 0:
            content_text = current_q.get('content', '')
            # Look for options in content - first try A), B), C), D)
            options_in_content = re.findall(r'(\b[A-E]\)|\b[1-5]\))\s*([^\n<]+)', content_text, re.IGNORECASE)
            if options_in_content and len(options_in_content) >= 2:
                current_q['options'] = [f"{marker.strip()} {text.strip()}" for marker, text in options_in_content[:5]]
            else:
                # Fallback: look for lines that start with just ")" - assign letters
                # Remove HTML tags first to get plain text
                plain_text = re.sub(r'<[^>]+>', ' ', content_text)
                # Find all lines that start with just ")" followed by text
                just_paren_options = re.findall(r'\)\s+([^)\n]+)', plain_text)
                if just_paren_options and len(just_paren_options) >= 2:
                    # Assign sequential letters A, B, C, D
                    option_letters = ['A', 'B', 'C', 'D']
                    current_q['options'] = [f"{option_letters[i]}) {text.strip()}" 
                                          for i, text in enumerate(just_paren_options[:4])]
                    print(f"DEBUG: Extracted {len(current_q['options'])} options from content fallback: {current_q['options']}")
        # Try to extract answer from content if not found separately
        if not current_q.get('answer'):
            content_text = current_q.get('content', '')
            # Look for answer in content
            answer_in_content = re.search(r'(?:Answer|उत्तर|సమాధానం|ଉତ୍ତର|பதில்|ಉತ್ತರ)\s*[:=]\s*([A-Z0-9]+)', content_text, re.IGNORECASE)
            if answer_in_content:
                current_q['answer'] = f"Answer: {answer_in_content.group(1)}"
        questions.append(current_q)
    
    # Debug: print what was parsed
    if questions:
        print(f"\n=== DEBUG: Parsed {len(questions)} questions ===")
        for i, q in enumerate(questions[:2], 1):  # Print first 2 questions for debugging
            print(f"Q{q['number']}: Content length={len(q.get('content', ''))}, Options={len(q.get('options', []))}, Answer={q.get('answer', 'None')}")
            if q.get('options'):
                print(f"  Options: {q['options']}")
            if q.get('answer'):
                print(f"  Answer: {q['answer']}")
        print("=== END DEBUG ===\n")
    
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
        
        # Debug: Print raw text if parsing fails (to check what Gemini is generating)
        if not questions:
            print(f"Warning: MCQ parsing failed. Raw text preview (first 500 chars):\n{clean_text[:500]}")
        
        if questions:
            # Build structured HTML for each question
            content_parts = []
            for q in questions:
                q_html = f'<div class="question">'
                # Question number - use English font for numbers
                q_html += f'<div class="question-number"><span style="font-family: Arial, sans-serif;">Q{q["number"]}.</span></div>'
                # Question content
                q_html += f'<div class="question-content">{q["content"]}</div>'
                # Options (if separate from content) - use English font for markers
                if q.get("options") and len(q["options"]) > 0:
                    options_html = '<div style="margin: 8px 0;"><strong>Options:</strong><br>'
                    for opt in q["options"]:
                        # Ensure option markers (A), B), C), D) or 1), 2), 3), 4)) use English font
                        # Extract marker and text, render marker with English font
                        opt_match = re.match(r'^([A-E]\)|[1-5]\))\s*(.*)', opt, re.IGNORECASE)
                        if opt_match:
                            opt_marker = opt_match.group(1)
                            opt_text = opt_match.group(2)
                            # Marker in English font, text in Indic font
                            options_html += f'<span style="margin-right: 15px;"><span style="font-family: Arial, sans-serif;">{opt_marker}</span> {clean_text_html(opt_text)}</span><br>'
                        else:
                            # Fallback: try to find marker anywhere in option
                            opt_marker_match = re.search(r'([A-E]\)|[1-5]\))', opt, re.IGNORECASE)
                            if opt_marker_match:
                                marker_pos = opt_marker_match.start()
                                opt_marker = opt_marker_match.group(1)
                                opt_text = opt[:marker_pos] + opt[marker_pos + len(opt_marker):]
                                options_html += f'<span style="margin-right: 15px;"><span style="font-family: Arial, sans-serif;">{opt_marker}</span> {clean_text_html(opt_text.strip())}</span><br>'
                            else:
                                # No marker found, display as-is but clean HTML
                                options_html += f'<span style="margin-right: 15px;">{clean_text_html(opt)}</span><br>'
                    options_html += '</div>'
                    q_html += options_html
                else:
                    # Check if options are embedded in content (for fallback)
                    content_text = q.get("content", "")
                    # Look for options in content that weren't parsed separately
                    if re.search(r'[A-E]\)|[1-5]\)', content_text):
                        # Options found in content - try to extract them
                        options_found = re.findall(r'([A-E]\)|[1-5]\))\s*([^<]+)', content_text)
                        if options_found and len(options_found) >= 2:
                            options_html = '<div style="margin: 8px 0;"><strong>Options:</strong><br>'
                            for opt_marker, opt_text in options_found[:5]:
                                opt_text_clean = re.sub(r'<br>|<[^>]+>', '', opt_text).strip()
                                options_html += f'<span style="margin-right: 15px;"><span style="font-family: Arial, sans-serif;">{opt_marker}</span> {clean_text_html(opt_text_clean)}</span><br>'
                            options_html += '</div>'
                            q_html += options_html
                # Answer - handle multiple formats
                if q.get("answer"):
                    # Extract answer value - try multiple patterns
                    answer_val = None
                    # Try English format: "Answer: B"
                    answer_match = re.search(r'Answer\s*[:=]\s*([A-Z0-9]+)', q["answer"], re.IGNORECASE)
                    if answer_match:
                        answer_val = answer_match.group(1)
                    else:
                        # Try Hindi format: "उत्तर: B"
                        answer_match = re.search(r'(?:उत्तर|సమాధానం|ଉତ୍ତର|பதில்|ಉತ್ತರ)\s*[:=]\s*([A-Z0-9]+)', q["answer"], re.IGNORECASE)
                        if answer_match:
                            answer_val = answer_match.group(1)
                        else:
                            # Fallback: find any letter/number after colon/equals
                            fallback_match = re.search(r'[:=]\s*([A-Z0-9]+)', q["answer"])
                            if fallback_match:
                                answer_val = fallback_match.group(1)
                    
                    if answer_val:
                        # Use English font for "Answer:" label and value
                        q_html += f'<div class="answer"><span style="font-family: Arial, sans-serif;">Answer: {answer_val}</span></div>'
                    else:
                        # Display as-is if we can't extract - ensure label uses English font
                        answer_text = q["answer"]
                        # Try to extract label and value separately
                        answer_label_match = re.search(r'(Answer|उत्तर|సమాధానం|ଉତ୍ତର|பதில்|ಉತ್ತर)\s*[:=]\s*([A-Z0-9]+)', answer_text, re.IGNORECASE)
                        if answer_label_match:
                            answer_label = answer_label_match.group(1)
                            answer_value = answer_label_match.group(2)
                            q_html += f'<div class="answer"><span style="font-family: Arial, sans-serif;">Answer: {answer_value}</span></div>'
                        else:
                            q_html += f'<div class="answer"><span style="font-family: Arial, sans-serif;">{clean_text_html(answer_text)}</span></div>'
                else:
                    # No answer found - might be missing, check if it's in content
                    content_text = q.get("content", "")
                    # Try to find answer in content
                    answer_in_content = re.search(r'(?:Answer|उत्तर|సమాధానం|ଉତ୍ତର|பதில்|ಉತ್ತರ)\s*[:=]\s*([A-Z0-9]+)', content_text, re.IGNORECASE)
                    if answer_in_content:
                        q_html += f'<div class="answer">Answer: {answer_in_content.group(1)}</div>'
                    else:
                        # Answer not found at all
                        q_html += f'<div class="answer" style="color: #999;">Answer: Not provided</div>'
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
