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
1. Write questions and options completely in {language} language
2. Use ONLY English letters A), B), C), D) for option MARKERS
3. Use ONLY "Answer: X" where X is A, B, C, or D - NEVER write answers in local language
4. Keep all mathematical numbers (3, 4, 5, 6, etc.) as digits - DO NOT translate numbers to words
5. Each question MUST follow this EXACT format:

1. [Question text in {language}?]
A) [Option A in {language} - keep numbers as digits]
B) [Option B in {language} - keep numbers as digits] 
C) [Option C in {language} - keep numbers as digits]
D) [Option D in {language} - keep numbers as digits]
Answer: B

2. [Next question text in {language}?]
A) [Option A in {language} - keep numbers as digits]
B) [Option B in {language} - keep numbers as digits]
C) [Option C in {language} - keep numbers as digits]
D) [Option D in {language} - keep numbers as digits]
Answer: C

IMPORTANT:
- Use ONLY English A), B), C), D) for option MARKERS
- Keep mathematical numbers as digits (3, 4, 5, 6) - DO NOT translate numbers to words
- DO NOT use: १) २) ३) ४) or 1) 2) 3) 4) or अ) आ) इ) ई)

EXAMPLE FOR HINDI (note: numbers remain as digits):
1. दो और दो का योग क्या है?
A) 3
B) 4
C) 5
D) 6
Answer: B

EXAMPLE FOR ODIA (note: numbers remain as digits):
1. ଦୁଇ ଏବଂ ଦୁଇର ଯୋଗଫଳ କ'ଣ?
A) 3
B) 4
C) 5
D) 6
Answer: B

Document content:
{pdf_text[:8000]}

Now generate {n} MCQs following the format above EXACTLY. Use ONLY A), B), C), D) for option markers and keep numbers as digits!"""

    model = genai.GenerativeModel("gemini-2.5-pro")
    response = model.generate_content(prompt)
    text = response.text

    if language.lower() in ["hindi", "odia"]:
        text = correct_gemini_output(text, language)

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


def correct_gemini_output(text, language):
    """Post-process Gemini output to fix common formatting issues"""
    if not text:
        return text

    print("=== APPLYING POST-PROCESSING CORRECTIONS ===")

    text = fix_missing_option_markers(text)

    lines = text.split('\n')
    corrected_lines = []

    hindi_to_english = {
        '१': 'A', '२': 'B', '३': 'C', '४': 'D',
        '୧': 'A', '୨': 'B', '୩': 'C', '୪': 'D',
        '1': 'A', '2': 'B', '3': 'C', '4': 'D'
    }

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        line = re.sub(r'^(\d+)\.[\s\u200b]*', r'\1. ', line)

        for marker, letter in hindi_to_english.items():
            line = re.sub(rf'^{marker}\)', f'{letter})', line)
            line = re.sub(rf'\s{marker}\)', f' {letter})', line)

        if re.match(r'^(उत्तर|ଉତ୍ତର|समाधान)\s*[:：]\s*', line):
            answer_part = re.sub(r'^(उत्तर|ଉତ୍ତର|समाधान)\s*[:：]\s*', '', line)
            replaced = False
            for marker, letter in hindi_to_english.items():
                if marker in answer_part:
                    line = f"Answer: {letter}"
                    replaced = True
                    break
            if not replaced:
                letter_match = re.search(r'([A-D])', answer_part, re.IGNORECASE)
                if letter_match:
                    line = f"Answer: {letter_match.group(1).upper()}"

        if corrected_lines:
            prev_line = corrected_lines[-1].strip()
            if (re.match(r'^\d+\.', prev_line) and line and len(line) > 2 and
                    not re.match(r'^[A-D]\)', line) and not re.match(r'^\d+\.', line) and
                    'Answer:' not in line):
                option_count = 0
                for j in range(len(corrected_lines) - 1, -1, -1):
                    if re.match(r'^\d+\.', corrected_lines[j]):
                        break
                    if re.match(r'^[A-D]\)', corrected_lines[j]):
                        option_count += 1
                if option_count < 4:
                    next_letter = chr(65 + option_count)
                    line = f"{next_letter}) {line}"
                    print(f"Corrected missing option marker: {line[:50]}")

        corrected_lines.append(line)
        i += 1

    corrected_text = '\n'.join(corrected_lines)
    corrected_text = re.sub(r'(\d+\.)([^\s])', r'\1 \2', corrected_text)
    corrected_text = re.sub(r'([A-D]\))([^\s])', r'\1 \2', corrected_text)

    print("=== CORRECTIONS APPLIED ===")
    return corrected_text

def generate_topic_mcqs(topic: str, n: int, language: str):
    if not topic:
        raise ValueError("Topic is required for topic-only MCQ generation.")

    prompt = f"""You are an expert exam question generator. Create exactly {n} NEW multiple-choice questions focused strictly on the topic: \"{topic}\".

CRITICAL FORMATTING RULES - FOLLOW EXACTLY:
1. Write questions and options completely in {language} language
2. Use ONLY English letters A), B), C), D) for option MARKERS
3. Use ONLY "Answer: X" where X is A, B, C, or D - NEVER write answers in local language
4. Keep all mathematical numbers (3, 4, 5, 6, etc.) as digits - DO NOT translate numbers to words
5. Each question MUST follow this EXACT format:

1. [Question text in {language}?]
A) [Option A in {language} - keep numbers as digits]
B) [Option B in {language} - keep numbers as digits]
C) [Option C in {language} - keep numbers as digits]
D) [Option D in {language} - keep numbers as digits]
Answer: B

2. [Next question text in {language}?]
A) [Option A in {language} - keep numbers as digits]
B) [Option B in {language} - keep numbers as digits]
C) [Option C in {language} - keep numbers as digits]
D) [Option D in {language} - keep numbers as digits]
Answer: C

IMPORTANT:
- Use ONLY English A), B), C), D) for option MARKERS
- Keep numbers as digits (3, 4, 5, 6) - DO NOT translate numbers to words
- DO NOT use १) २) ३) ४) or 1) 2) 3) 4) or अ) आ) इ) ई)

EXAMPLE (numbers stay digits):
1. दो और दो का योग क्या है?
A) 3
B) 4
C) 5
D) 6
Answer: B

Generate {n} questions now following the instructions exactly."""

    model = genai.GenerativeModel("gemini-2.5-pro")
    response = model.generate_content(prompt)
    text = response.text

    if language.lower() in ["hindi", "odia"]:
        text = correct_gemini_output(text, language)

    return text

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


def fix_missing_option_markers(text):
    """Fix options that have just ")" without A,B,C,D markers"""
    lines = (text or "").split('\n')
    corrected_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(')') and len(stripped) > 1:
            option_count = 0
            for prev in reversed(corrected_lines):
                prev_stripped = prev.strip()
                if re.match(r'^\d+\.', prev_stripped):
                    break
                if re.match(r'^[A-D]\)', prev_stripped):
                    option_count += 1
            if option_count < 4:
                next_letter = chr(65 + option_count)
                corrected_line = f"{next_letter}{stripped}"
                print(f"Fixed missing option marker: '{stripped}' -> '{corrected_line}'")
                corrected_lines.append(corrected_line)
                continue
        corrected_lines.append(line)

    return '\n'.join(corrected_lines)

def clean_text_html(s):
    """Clean text for HTML display"""
    if not s:
        return ""
    s = html.escape(str(s))
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").strip()

def parse_mcq_text(text):
    """Parse MCQ text into structured format - completely rewritten for Hindi/Odia support"""
    print(f"\n=== DEBUG: Raw Gemini Output ===")
    print((text or "")[:1500])
    print("=== END DEBUG ===\n")

    if not text or text.strip() == "":
        print("ERROR: Empty text received from Gemini")
        return []

    hindi_char_count = len(re.findall(r'[\u0900-\u097F]', text))
    if hindi_char_count > len(text) * 0.3:
        print("Detected Hindi text with potential formatting issues, applying enhanced parsing...")
        text = re.sub(r'(\d+)\.\s*', r'\n\1. ', text)
        text = re.sub(r'([A-D])\)\s*', r'\n\1) ', text)

    text = normalize_unicode_digits(text)

    text = re.sub(r'(\d+)\.\s*([^:\n?]+)\s*:\s*([^:\n?]+)\s*::\s*([^:\n?]+)\s*:\s*\?', r'\1. \2 : \3 :: \4 : ?', text)
    text = re.sub(r'Options?\s*[:：]\s*', 'Options: ', text, flags=re.IGNORECASE)
    text = re.sub(r'Answer\s*[:：]\s*', 'Answer: ', text, flags=re.IGNORECASE)

    questions = []
    lines = text.split('\n')

    current_q = None
    question_counter = 0

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        print(f"DEBUG Line {i}: '{line[:60]}'")

        question_found = False
        match = re.match(r'^(\d+)[\.\)]\s*(.*\?)\s*$', line)
        if match:
            question_found = True
            q_num = match.group(1)
            q_text = match.group(2)

        if not match:
            match = re.match(r'^Q\s*(\d+)[\.\)]\s*(.*\?)\s*$', line, re.IGNORECASE)
            if match:
                question_found = True
                q_num = match.group(1)
                q_text = match.group(2)

        if not match and re.match(r'^\d+\.', line) and '?' in line:
            parts = line.split('?', 1)
            if len(parts) > 1:
                q_text = parts[0] + '?'
                q_num = re.match(r'^(\d+)\.', line).group(1)
                question_found = True

        if question_found:
            if current_q:
                questions.append(current_q)

            question_counter += 1
            current_q = {
                'number': str(question_counter),
                'content': q_text.strip(),
                'options': [],
                'answer': None,
                'raw_number': q_num
            }
            print(f"DEBUG: Started question {q_num}: {q_text[:50]}...")
            i += 1
            continue

        if current_q:
            option_match = re.match(r'^([A-D])\)\s*(.+)$', line, re.IGNORECASE)
            if option_match:
                marker = option_match.group(1).upper()
                option_text = option_match.group(2).strip()
                current_q['options'].append(f"{marker}) {option_text}")
                print(f"DEBUG: Added option {marker})")
                i += 1
                continue

            alt_option_match = re.match(r'^\(([A-D])\)\s*(.+)$', line, re.IGNORECASE)
            if alt_option_match:
                marker = alt_option_match.group(1).upper()
                option_text = alt_option_match.group(2).strip()
                current_q['options'].append(f"{marker}) {option_text}")
                print(f"DEBUG: Added alt option {marker})")
                i += 1
                continue

            if re.search(r'[A-D]\)\s*[^A-D]', line) and len(current_q['options']) < 4:
                options_found = re.findall(r'([A-D])\)\s*([^A-D\)]+)', line)
                for marker, opt_text in options_found:
                    if len(current_q['options']) < 4:
                        current_q['options'].append(f"{marker.upper()}) {opt_text.strip()}")
                        print(f"DEBUG: Split option {marker}) from concatenated line")
                i += 1
                continue

            if re.match(r'^(Answer|उत्तर|ଉତ୍ତର|समाधान)\s*[:=]\s*', line, re.IGNORECASE):
                answer_text = re.sub(r'^(Answer|उत्तर|ଉତ୍ତର|समाधान)\s*[:=]\s*', '', line, flags=re.IGNORECASE).strip()

                answer_letter = None
                letter_match = re.search(r'([A-D])', answer_text, re.IGNORECASE)
                if letter_match:
                    answer_letter = letter_match.group(1).upper()
                else:
                    hindi_map = {'१': 'A', '२': 'B', '३': 'C', '४': 'D',
                                 '1': 'A', '2': 'B', '3': 'C', '4': 'D'}
                    for num, letter in hindi_map.items():
                        if num in answer_text:
                            answer_letter = letter
                            break

                if answer_letter:
                    current_q['answer'] = f"Answer: {answer_letter}"
                    print(f"DEBUG: Found answer: {current_q['answer']}")
                else:
                    current_q['answer'] = f"Answer: {answer_text}"

                questions.append(current_q)
                current_q = None
                i += 1
                continue

            if line and len(current_q['options']) < 4 and not re.match(r'^\d+\.', line):
                next_letter = chr(65 + len(current_q['options']))
                current_q['options'].append(f"{next_letter}) {line}")
                print(f"DEBUG: Added fallback option {next_letter})")

        i += 1

    if current_q:
        questions.append(current_q)

    for q in questions:
        q['options'] = [opt.strip() for opt in q.get('options', []) if opt.strip()]
        if q.get('answer') and not q['answer'].startswith('Answer:'):
            q['answer'] = 'Answer: ' + q['answer']

    print(f"\n=== FINAL PARSED {len(questions)} QUESTIONS ===")
    for q in questions:
        print(f"Q{q['number']}: {q['content'][:60]}...")
        print(f"  Options: {len(q.get('options', []))}")
        for opt in q.get('options', []):
            print(f"    {opt[:40]}...")
        print(f"  Answer: {q.get('answer', 'None')}")
        print()

    if not questions and re.search(r'[\u0900-\u097F]', text or ''):
        print("Main parser failed, trying emergency Hindi parser...")
        questions = emergency_parse_hindi_mcqs(text)

    return questions if questions else []


def emergency_parse_hindi_mcqs(text):
    """Emergency parser for when the main parser fails with Hindi/Odia text"""
    print("=== USING EMERGENCY PARSER ===")

    questions = []
    lines = (text or '').split('\n')

    current_question = None
    question_number = 1

    marker_map = {'1': 'A', '2': 'B', '3': 'C', '4': 'D',
                  '१': 'A', '२': 'B', '३': 'C', '४': 'D',
                  '୧': 'A', '୨': 'B', '୩': 'C', '୪': 'D'}

    for line in lines:
        clean = line.strip()
        if not clean:
            continue

        if re.match(r'^\d+\.', clean) and '?' in clean:
            if current_question:
                questions.append(current_question)
            current_question = {
                'number': str(question_number),
                'content': clean,
                'options': [],
                'answer': None
            }
            question_number += 1
            continue

        if current_question and len(current_question['options']) < 4:
            option_match = re.match(r'^([A-D1-4१२३४୧୨୩୪])[\)\.\-]\s*(.+)', clean)
            if option_match:
                marker = option_match.group(1)
                option_text = option_match.group(2)
                normalized = marker_map.get(normalize_unicode_digits(marker), 'A')
                current_question['options'].append(f"{normalized}) {option_text}")
                continue

        if current_question and re.search(r'(Answer|उत्तर|ଉତ୍ତର)\s*[:=]', clean, re.IGNORECASE):
            answer_match = re.search(r'[:=]\s*([A-D1-4१२३४୧୨୩୪])', clean)
            if answer_match:
                marker = answer_match.group(1)
                normalized = marker_map.get(normalize_unicode_digits(marker), 'A')
                current_question['answer'] = f"Answer: {normalized}"
            continue

    if current_question:
        questions.append(current_question)

    print(f"Emergency parser found {len(questions)} questions")
    return questions

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
