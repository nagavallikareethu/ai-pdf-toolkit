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
import unicodedata
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
def generate_mcqs(pdf_path, n, language, topic=None):
    pdf_text = extract_text_from_pdf(pdf_path)

    if not pdf_text:
        raise ValueError("ERROR: No readable text found in the PDF! Make sure it's not just scanned images.")

    topic_instruction = ""
    if topic:
        topic_instruction = f"""

ADDITIONAL TOPIC REQUIREMENT:
- Focus the questions strictly on the topic: "{topic}".
- Prefer PDF content that relates to this topic. If the PDF has limited coverage, craft questions that are still consistent with the document's style while centering the topic."""

    hindi_analogy_example = ""
    if language.lower() == "hindi":
        hindi_analogy_example = """

SPECIFIC EXAMPLE FOR ANALOGY QUESTIONS IN HINDI:
1. पुस्तक : लेखक :: प्रतिमा : ?
A) राजमिस्त्री
B) मूर्तिकार  
C) बढ़ई
D) चित्रकार
Answer: B

2. डॉक्टर : स्टेथोस्कोप :: शिक्षक : ?
A) पुस्तक
B) टेबल
C) कंप्यूटर
D) कक्षा
Answer: A
"""

    special_formatting_block = ""
    if language.lower() in ("hindi", "odia"):
        if language.lower() == "hindi":
            example_block = """
1. दो और दो का योग क्या है?
A) 3
B) 4  
C) 5
D) 6
Answer: B

2. भारत की राजधानी क्या है?
A) मुंबई
B) दिल्ली
C) कोलकाता
D) चेन्नई
Answer: B
"""
        else:
            example_block = """
1. ଦୁଇ ଏବଂ ଦୁଇର ଯୋଗଫଳ କ'ଣ?
A) 3
B) 4  
C) 5
D) 6
Answer: B

2. ଭାରତର ରାଜଧାନୀ କ'ଣ?
A) ମୁମ୍ବାଇ
B) ନୟା ଦିଲ୍ଲୀ
C) କୋଲକାତା
D) ଚେନ୍ନାଇ
Answer: B
"""
        special_formatting_block = f"""
CRITICAL FOR {language.upper()} FORMATTING:
- Write questions and options completely in {language}
- Use ONLY English letters A), B), C), D) for every option
- Use ONLY the phrase \"Answer: X\" where X is A, B, C, or D
- Do NOT translate the option markers or the word \"Answer\"
- Follow this structure exactly:
{example_block}"""

    prompt = f"""You are an expert exam question generator. Read the following document carefully and generate exactly {n} NEW MCQs.{topic_instruction}

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

CRITICAL:
- You MUST use ONLY English letters A), B), C), D) for the option labels
- You MUST use ONLY the English phrase "Answer: X" where X is A, B, C, or D
- DO NOT translate the option markers or the word "Answer" into any other language
- The question text and option text should be in {language}, but the labels must remain in English

EXAMPLE FORMAT - COPY EXACTLY:
1. What is 2+2?
A) 3
B) 4
C) 5
D) 6
Answer: B

2. What is the capital of France?
A) London
B) Berlin
C) Paris
D) Madrid
Answer: C

EXAMPLE FOR HINDI:
1. दो और दो का योग क्या है?
A) 3
B) 4
C) 5
D) 6
Answer: B{hindi_analogy_example}

EXAMPLE FOR ODIA:
1. ଦୁଇ ଏବଂ ଦୁଇର ଯୋଗଫଳ କ'ଣ?
A) 3
B) 4
C) 5
D) 6
Answer: B

{special_formatting_block}

Document content:
{pdf_text[:10000]}

Now generate {n} MCQs following the format above EXACTLY. Remember:
- Use A), B), C), D) for options (NOT just ) or 1), 2), 3), 4))
- Use "Answer: X" format with English label!"""

    model = genai.GenerativeModel("gemini-2.5-pro")
    response = model.generate_content(prompt)
    text = response.text
    print(f"\n=== RAW GEMINI OUTPUT ({language}) ===")
    print(text)
    print("=== END RAW OUTPUT ===\n")
    try:
        outfile = f"gemini_output_{language}.txt"
        with open(outfile, "w", encoding="utf-8") as f:
            f.write(text or "")
        print(f"Saved raw output to: {outfile}")
    except Exception as e:
        print(f"Warning: failed to save raw Gemini output: {e}")
    
    return text

def generate_topic_mcqs(topic: str, n: int, language: str):
    if not topic:
        raise ValueError("Topic is required for topic-only MCQ generation.")

    prompt = f"""You are an expert exam question generator. Create exactly {n} NEW multiple-choice questions focused on the topic: "{topic}".

CRITICAL FORMAT RULES - FOLLOW EXACTLY:
1. Write questions and options in {language} language
2. Use ONLY English option labels A), B), C), D)
3. Use "Answer: X" (English label) for the correct option
4. Follow the format shown below

1. [Question text in {language}]
A) [Option A]
B) [Option B]
C) [Option C]
D) [Option D]
Answer: B

[Continue for all {n} questions.]

ADDITIONAL GUIDELINES:
- Ensure every question is relevant to "{topic}"
- Balance difficulty: mix of easy, moderate, and challenging
- Avoid repeating question stems
- Keep wording concise and exam-appropriate
"""

    model = genai.GenerativeModel("gemini-2.5-pro")
    response = model.generate_content(prompt)
    return response.text

# ======================================================
# GET SCRIPT DIRECTORY FOR FONTS
# ======================================================
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
FONTS_DIR = SCRIPT_DIR / "fonts"

DIGIT_TO_LETTER = {'1': 'A', '2': 'B', '3': 'C', '4': 'D', '5': 'E'}
OPTION_NORMALIZATION_MAP = {
    'A': 'A', 'B': 'B', 'C': 'C', 'D': 'D',
    '1': 'A', '2': 'B', '3': 'C', '4': 'D',
    'अ': 'A', 'आ': 'B', 'इ': 'C', 'ई': 'D',
    'କ': 'A', 'ଖ': 'B', 'ଗ': 'C', 'ଘ': 'D',
    'ଅ': 'A', 'ଆ': 'B', 'ଇ': 'C', 'ଈ': 'D'
}
OPTION_LETTERS = ['A', 'B', 'C', 'D', 'E']

BULLET_PATTERN = r'^[\u2022\u25CF\u25AA\u25AB\u25CB\u25C9\-\–\—\•\●\·]+\s*'

def normalize_unicode_digits(text):
    if text is None:
        return text
    chars = []
    for ch in text:
        if ch.isdigit() and not ch.isascii():
            try:
                chars.append(str(unicodedata.digit(ch)))
                continue
            except (TypeError, ValueError):
                pass
        chars.append(ch)
    return ''.join(chars)

def normalize_number_str(num_str):
    return normalize_unicode_digits(str(num_str or '')).strip()

def normalize_answer_value(answer_fragment):
    if not answer_fragment:
        return None
    fragment = normalize_unicode_digits(answer_fragment).strip()
    letter_match = re.search(r'\b([A-D])\b', fragment, re.IGNORECASE)
    if letter_match:
        return letter_match.group(1).upper()
    digit_match = re.search(r'\b([1-4])\b', fragment)
    if digit_match:
        digit = digit_match.group(1)
        return OPTION_NORMALIZATION_MAP.get(digit)
    for key, value in OPTION_NORMALIZATION_MAP.items():
        if key and key in fragment:
            return value
    fragment_compact = re.sub(r'[\s:]', '', fragment)
    for key, value in OPTION_NORMALIZATION_MAP.items():
        if key and key in fragment_compact:
            return value
    return None

def normalize_option_list(option_list):
    if not option_list:
        return []
    normalized = []
    for opt in option_list:
        opt_str = str(opt or '').strip()
        if not opt_str:
            continue
        if re.match(r'^[A-D]\)\s+', opt_str, re.IGNORECASE):
            normalized.append(opt_str)
            continue
        opt_str = re.sub(BULLET_PATTERN, '', opt_str)
        opt_match = re.match(r'^([^\)]+)\)\s*(.*)', opt_str)
        if opt_match:
            marker_raw = normalize_unicode_digits(opt_match.group(1)).strip()
            body = opt_match.group(2).strip()
            mapped = OPTION_NORMALIZATION_MAP.get(marker_raw.upper()) or OPTION_NORMALIZATION_MAP.get(marker_raw)
            if mapped and body:
                normalized.append(f"{mapped}) {body}")
                continue
        normalized.append(opt_str)
    return normalized

def clean_text_html(s):
    """Clean text for HTML display"""
    if not s:
        return ""
    s = html.escape(str(s))
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").strip()

def parse_mcq_text(text):
    """Parse MCQ text into structured format - improved for Indic languages"""
    print(f"\n=== DEBUG: Raw text from Gemini (first 1000 chars) ===")
    preview = (text or "")[:1000]
    print(preview)
    print("=== END DEBUG ===\n")

    if not text:
        return None

    text = normalize_unicode_digits(text)

    # Normalize analogy style constructs
    text = re.sub(r'(\d+)\.\s*([^:?]+)\s*:\s*([^:?]+)\s*::\s*([^:?]+)\s*:\s*\?', r'\1. \2 : \3 :: \4 : ?', text)

    # Encourage line breaks before numbered questions and tidy answer markers
    text = re.sub(r'(\d+)[\.\)]\s+', lambda m: f"\n{normalize_number_str(m.group(1))}. ", text)
    text = re.sub(r'(?mi)^(Answer)\s*[-–]\s*', r"\\1: ", text)

    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]

    questions = []
    current_q = None

    def finalize_current():
        nonlocal current_q
        if not current_q:
            return
        extras = current_q.pop('_extra', [])
        if extras:
            current_q['content'] = (current_q.get('content') or '') + '<br>' + '<br>'.join(extras)
        if current_q.get('options'):
            current_q['options'] = normalize_option_list(current_q['options'])
        answer_val = current_q.get('answer')
        if answer_val and not answer_val.startswith('Answer:'):
            normalized = normalize_answer_value(answer_val)
            current_q['answer'] = f"Answer: {normalized}" if normalized else f"Answer: {answer_val}"
        questions.append(current_q)
        if current_q.get('options'):
            print(f"DEBUG: Question {current_q['number']} has {len(current_q['options'])} options: {current_q['options']}")
        if current_q.get('answer'):
            print(f"DEBUG: Question {current_q['number']} answer: {current_q['answer']}")
        current_q = None

    local_marker_map = {
        '१': 'A', '२': 'B', '३': 'C', '४': 'D',
        'अ': 'A', 'आ': 'B', 'इ': 'C', 'ई': 'D',
        'क': 'A', 'ख': 'B', 'ग': 'C', 'घ': 'D',
        'ଅ': 'A', 'ଆ': 'B', 'ଇ': 'C', 'ଈ': 'D',
        '୧': 'A', '୨': 'B', '୩': 'C', '୪': 'D'
    }

    for line in lines:
        print(f"DEBUG: Processing line: '{line[:60]}'")

        if current_q:
            # Detect answers in multiple languages
            answer_prefix_match = re.match(r'^(Answer|उत्तर|ଉତ୍ତର|ସମାଧାନ|समाधान)\s*[:=]\s*(.+)$', line, re.IGNORECASE)
            if answer_prefix_match:
                answer_fragment = answer_prefix_match.group(2).strip()
                normalized = normalize_answer_value(answer_fragment)
                current_q['answer'] = f"Answer: {normalized}" if normalized else f"Answer: {answer_fragment}"
                print(f"DEBUG: Found answer: {current_q['answer']}")
                finalize_current()
                continue

            if 'Answer' in line and len(line) < 50:
                fallback_match = re.search(r'Answer\s*[:=]\s*([A-D])', line, re.IGNORECASE)
                if fallback_match:
                    answer_letter = fallback_match.group(1).upper()
                    current_q['answer'] = f"Answer: {answer_letter}"
                    print(f"DEBUG: Found fallback answer: {current_q['answer']}")
                    finalize_current()
                    continue

            # English-labelled options
            english_option = re.match(r'^([A-D])\)\s+(.+)$', line, re.IGNORECASE)
            if english_option:
                marker = english_option.group(1).upper()
                option_text = english_option.group(2).strip()
                current_q.setdefault('options', []).append(f"{marker}) {option_text}")
                print(f"DEBUG: Added option {marker}) {option_text[:40]}")
                continue

            # Numeric options (1) -> A) etc.
            digit_option = re.match(r'^([1-4])\)\s+(.+)$', line)
            if digit_option:
                digit_marker = digit_option.group(1)
                option_text = digit_option.group(2).strip()
                mapped = DIGIT_TO_LETTER.get(digit_marker, 'A')
                current_q.setdefault('options', []).append(f"{mapped}) {option_text}")
                print(f"DEBUG: Converted digit option {digit_marker}) to {mapped})")
                continue

            # Hindi/Odia markers that need conversion
            local_option = re.match(r'^([\u0966-\u096f\u0b66-\u0b6fअआइईକଖଗଘଅଆଇଈ])\s*[\)\.:]\s*(.+)$', line)
            if local_option:
                local_marker = local_option.group(1)
                option_text = local_option.group(2).strip()
                normalized_marker = local_marker_map.get(local_marker)
                if not normalized_marker:
                    normalized_marker = DIGIT_TO_LETTER.get(normalize_unicode_digits(local_marker), 'A')
                current_q.setdefault('options', []).append(f"{normalized_marker}) {option_text}")
                print(f"DEBUG: Converted local option {local_marker} to {normalized_marker})")
                continue

            # Fallback bullet/paragraph options
            fallback_option = try_extract_option_line(line, len(current_q.get('options', [])))
            if fallback_option:
                current_q.setdefault('options', []).append(fallback_option)
                print(f"DEBUG: Extracted fallback option: {fallback_option[:40]}")
                continue

            current_q.setdefault('_extra', []).append(line)
            continue

        # No active question - attempt to detect new question lines
        question_match = re.match(r'^(?:प्रश्न|Question)?\s*(\d+)[\.)]\s*(.+)$', line, re.IGNORECASE)
        if question_match:
            q_num = normalize_number_str(question_match.group(1)) or str(len(questions) + 1)
            q_body = question_match.group(2).strip()
            current_q = {
                'number': q_num,
                'content': q_body,
                'options': [],
                'answer': None,
                '_extra': []
            }
            print(f"DEBUG: Found question {q_num}")
            continue

        # Handle question style with explicit word prefix first
        question_word_match = re.match(r'^(?:प्रश्न|Question)\s*(\d+)\s*[:\-]\s*(.+)$', line, re.IGNORECASE)
        if question_word_match:
            q_num = normalize_number_str(question_word_match.group(1)) or str(len(questions) + 1)
            q_body = question_word_match.group(2).strip()
            current_q = {
                'number': q_num,
                'content': q_body,
                'options': [],
                'answer': None,
                '_extra': []
            }
            print(f"DEBUG: Found question {q_num} via word prefix")
            continue

    finalize_current()

    if questions:
        print(f"\n=== DEBUG: Parsed {len(questions)} questions ===")
        for q in questions[:3]:
            print(f"Q{q['number']}: options={len(q.get('options', []))}, answer={q.get('answer')}")
        print("=== END DEBUG ===\n")

    return questions if questions else None

option_marker_pattern = r'(([A-D]|[1-4])\))'
option_line_pattern = r'^[A-D1-4][\)\.:]\s+'

def format_option_marker(raw_marker):
    if not raw_marker:
        return None
    marker = normalize_unicode_digits(str(raw_marker)).strip()
    marker_clean = re.sub(r'[\)\.:]', '', marker)
    marker_upper = marker_clean.upper()
    mapped = OPTION_NORMALIZATION_MAP.get(marker_upper) or OPTION_NORMALIZATION_MAP.get(marker_clean)
    if mapped:
        return f"{mapped})"
    if re.match(r'^[A-D]$', marker_upper):
        return f"{marker_upper})"
    return None

def build_option_line(marker, text):
    opt_text = (text or "").strip()
    if not opt_text:
        return None
    normalized_marker = format_option_marker(marker)
    if normalized_marker:
        return f"{normalized_marker} {opt_text}"
    return opt_text

def try_extract_option_line(line, existing_count):
    """Try to extract option from a line that doesn't match standard patterns"""
    if not line:
        return None
    line = line.replace('â€¢', '•')
    stripped = re.sub(BULLET_PATTERN, '', line.strip()).strip()
    if not stripped or re.match(r'^(Answer|उत्तर|ସମାଧାନ|ଉତ୍ତର|பதில்|ಉತ್ತರ)', stripped, re.IGNORECASE):
        return None
    if len(stripped) > 2 and not re.match(r'^\d+\.', stripped):
        fallback = OPTION_LETTERS[existing_count] if existing_count < len(OPTION_LETTERS) else OPTION_LETTERS[0]
        return f"{fallback}) {stripped}"
    return None

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
                    print(f"DEBUG: Rendering options for Q{q['number']}: {q['options']}")
                    for opt in q["options"]:
                        opt_clean = str(opt).strip()
                        opt_match = re.match(r'^([A-D])\)\s*(.*)', opt_clean, re.IGNORECASE)
                        if opt_match:
                            opt_marker = opt_match.group(1).upper() + ")"
                            opt_text = opt_match.group(2)
                            options_html += f'<div style="margin: 4px 0;"><span style="font-family: Arial, sans-serif; font-weight: bold;">{opt_marker}</span> {clean_text_html(opt_text)}</div>'
                            print(f"DEBUG: Rendered option: {opt_marker} {opt_text[:30]}")
                        else:
                            options_html += f'<div style="margin: 4px 0;">{clean_text_html(opt_clean)}</div>'
                    options_html += '</div>'
                    q_html += options_html
                else:
                    # Check if options are embedded in content (for fallback)
                    content_text = q.get("content", "")
                    # Look for options starting with just ")" in content
                    plain_content = re.sub(r'<br\s*/?>', '\n', content_text, flags=re.IGNORECASE)
                    plain_content = re.sub(r'<[^>]+>', ' ', plain_content)
                    lines = plain_content.split('\n')
                    options_found = []
                    for line in lines:
                        line = line.strip()
                        if re.match(r'\)\s*[^\s)]', line):
                            opt_text = re.sub(r'^\)\s*', '', line).strip()
                            if opt_text:
                                options_found.append(opt_text)
                                if len(options_found) >= 4:
                                    break
                    
                    if options_found and len(options_found) >= 2:
                        # Assign letters and display
                        option_letters = ['A', 'B', 'C', 'D']
                        options_html = '<div style="margin: 8px 0;"><strong>Options:</strong><br>'
                        for i, opt_text in enumerate(options_found[:4]):
                            opt_letter = option_letters[i]
                            # Each option on its own line (using <div> for proper line breaks)
                            options_html += f'<div style="margin: 4px 0;"><span style="font-family: Arial, sans-serif; font-weight: bold;">{opt_letter})</span> {clean_text_html(opt_text)}</div>'
                        options_html += '</div>'
                        q_html += options_html
                        # Also update the question dict so it's saved
                        if not q.get("options"):
                            q["options"] = [f"{option_letters[i]}) {text.strip()}" 
                                          for i, text in enumerate(options_found[:4])]
                # Answer - handle multiple formats
                if q.get("answer"):
                    answer_val = None
                    answer_match = re.search(r'Answer\s*[:=]\s*([A-D])', q["answer"], re.IGNORECASE)
                    if not answer_match:
                        answer_match = re.search(r'[:=]\s*([A-D])', q["answer"], re.IGNORECASE)
                    if answer_match:
                        answer_val = answer_match.group(1).upper()
                        q_html += f'<div class="answer"><span style="font-family: Arial, sans-serif;">Answer: {answer_val}</span></div>'
                    else:
                        answer_text = q["answer"]
                        if not answer_text.startswith('Answer:'):
                            answer_text = 'Answer: ' + answer_text
                        q_html += f'<div class="answer"><span style="font-family: Arial, sans-serif;">{clean_text_html(answer_text)}</span></div>'
                else:
                    content_text = q.get("content", "")
                    answer_in_content = re.search(r'(?:Answer|उत्तर|సమాధానం|ଉత్తర|பதில்|ಉತ್ತರ)\s*[:=]\s*(.+)', content_text, re.IGNORECASE)
                    if answer_in_content:
                        ans_val = normalize_answer_value(answer_in_content.group(1))
                        mapped = ans_val or answer_in_content.group(1)
                        q_html += f'<div class="answer"><span style="font-family: Arial, sans-serif;">Answer: {mapped}</span></div>'
                    else:
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
    
    choice = int(input("\n Enter the number of your language choice: ").strip())
    if choice < 1 or choice > len(languages):
        raise ValueError("Invalid choice! Please select a valid option.")
    
    lang = languages[choice - 1]
    topic = input("\n🎯 Enter a topic to focus on (leave blank for general questions): ").strip()
    topic = topic if topic else None
    
    print("\n🧠 Generating MCQs using Gemini 2.5 Pro... please wait\n")
    mcqs = generate_mcqs(pdf_path, num_qs, lang, topic=topic)

    if mcqs:
        output_pdf = f"Generated_MCQs_{lang}.pdf"
        ok = save_pdf(mcqs, output_pdf, lang)

        if ok:
            print(f"\n✅ {lang} PDF generated successfully: {output_pdf}")
        else:
            print("\n❌ Failed to create PDF.")
    else:
        print("\n⚠️ No MCQs generated.")
