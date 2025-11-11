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

EXAMPLE FORMAT - COPY EXACTLY:
1. What is 2+2?
A) 3
B) 4
C) 5
D) 6
Answer: B

2Document content:
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
    text = re.sub(r'^\s*(\d+)\)', r'\n\1)', text, flags=re.MULTILINE)
    
    # Fix concatenated options like "A) 120%B) 135%C) 150%D) 100%" - split them
    # More aggressive splitting to handle all concatenated patterns
    
    # Step 1: Handle "Options:" prefix followed by concatenated options
    # Match "Options:A)textB)textC)textD)text" or "Options: A)textB)textC)textD)text"
    def split_options_in_text(match):
        prefix = match.group(1)
        options_text = match.group(2)
        parts = re.split(option_marker_pattern, options_text, flags=re.IGNORECASE)
        result = []
        for i in range(1, len(parts), 2):
            if i + 1 < len(parts):
                marker = parts[i]
                text = parts[i + 1]
                option_line = build_option_line(marker, text)
                if option_line:
                    result.append(option_line)
        return prefix + "\n".join(result) if result else match.group(0)
    
    # Apply splitting to lines with "Options:" prefix
    text = re.sub(r'(Options?\s*[:：]\s*)([A-E]\)[^\n]+)', split_options_in_text, text, flags=re.IGNORECASE)
    
    # Step 2: Split concatenated options that appear anywhere (not just after "Options:")
    # Match pattern: A)textB)textC)textD)text (anywhere in text)
    def split_concatenated_options(match):
        full_match = match.group(0)
        parts = re.split(option_marker_pattern, full_match, flags=re.IGNORECASE)
        result = []
        for i in range(1, len(parts), 2):
            if i + 1 < len(parts):
                marker = parts[i]
                text = parts[i + 1]
                option_line = build_option_line(marker, text)
                if option_line:
                    result.append(option_line)
        return "\n".join(result) if result else full_match
    
    # Find and split any line that contains multiple option markers without newlines between them
    # This handles cases like "A) 120%B) 135%C) 150%D) 100%" on a single line
    lines = text.split('\n')
    processed_lines = []
    for line in lines:
        # Check if line contains multiple option markers (A), B), C), D) or 1), 2), etc.)
        option_count = len(re.findall(option_marker_pattern, line, re.IGNORECASE))
        if option_count >= 2:  # Multiple options in one line
            parts = re.split(option_marker_pattern, line, flags=re.IGNORECASE)
            split_parts = []
            for i in range(1, len(parts), 2):
                if i + 1 < len(parts):
                    marker = parts[i]
                    text_segment = parts[i + 1]
                    option_line = build_option_line(marker, text_segment)
                    if option_line:
                        split_parts.append(option_line)
            if split_parts:
                processed_lines.extend(split_parts)
            else:
                processed_lines.append(line)
        else:
            processed_lines.append(line)
    
    text = '\n'.join(processed_lines)

    def normalize_option_prefix(match):
        marker = match.group(1).upper()
        remainder = match.group(2)
        if marker.isdigit():
            idx = int(marker)
            if 1 <= idx <= 4:
                marker = ['A', 'B', 'C', 'D'][idx - 1]
        return f"{marker}) {remainder}" if remainder else f"{marker})"

    text = re.sub(r'(?m)^\s*([A-E1-5])[\.\:-]\s*(\S.*)?', lambda m: normalize_option_prefix(m), text)
    text = re.sub(r'(?mi)^(Answer)\s*[-–]\s*', r"\1: ", text)
    
    questions = []
    lines = text.split('\n')
    
    current_q = None
    auto_counter = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check if this is a question number
        match = re.match(r'^(?:Q\s*)?(\d+)[\.\)]\s*(.*)', line, re.IGNORECASE)
        if not match:
            match = re.match(r'^(?:Question|Que|Qn)\s*(\d+)\s*[:\-]?\s*(.*)', line, re.IGNORECASE)
        if match:
            if current_q:
                questions.append(current_q)
            try:
                auto_counter = int(match.group(1))
            except (ValueError, TypeError):
                auto_counter += 1
            current_q = {
                'number': match.group(1) if match.group(1) else str(auto_counter),
                'content': match.group(2),
                'parts': [],
                'options': [],
                'answer': None
            }
            continue
        if current_q is None and re.match(r'^(?:Question|Que|Qn)\b', line, re.IGNORECASE):
            auto_counter += 1
            question_text = re.sub(r'^(?:Question|Que|Qn)\b\s*[:\-]?\s*', '', line, flags=re.IGNORECASE)
            current_q = {
                'number': str(auto_counter),
                'content': question_text,
                'parts': [],
                'options': [],
                'answer': None
            }
            continue
        elif current_q:
            # Check if this line starts with "Options:" followed by concatenated options
            # Handle "Options:A) 120%B) 135%C) 150%D) 100%" format
            if re.match(r'^Options?\s*[:：]\s*', line, re.IGNORECASE):
                options_part = re.sub(r'^Options?\s*[:：]\s*', '', line, flags=re.IGNORECASE).strip()
                split_options = re.split(option_marker_pattern, options_part, flags=re.IGNORECASE)
                if len(split_options) > 3:  # Found multiple options
                    for i in range(1, len(split_options), 2):
                        if i + 1 < len(split_options):
                            opt_marker = split_options[i]
                            opt_text = split_options[i + 1]
                            option_line = build_option_line(opt_marker, opt_text)
                            if option_line:
                                if not current_q.get('options'):
                                    current_q['options'] = []
                                current_q['options'].append(option_line)
                                print(f"DEBUG: Extracted option from 'Options:' line: '{option_line[:30]}'")
                else:
                    option_line = build_option_line(None, options_part)
                    if option_line:
                        if not current_q.get('options'):
                            current_q['options'] = []
                        current_q['options'].append(option_line)
            # Check if this is an answer - handle multiple formats
            # English: "Answer:", "Answer: B", "Answer:B"
            # Hindi: "उत्तर:", "उत्तर: B"
            # Telugu: "సమాధానం:", etc.
            elif (line.startswith('Answer:') or 
                re.match(r'^(Answer|उत्तर|సమాధానం|ଉତ୍ତର|பதில்|ಉತ್ತರ)\s*[:=]\s*([A-Z0-9\(\)\s]+)', line, re.IGNORECASE)):
                # Try to extract answer value (A, B, C, D or 1, 2, 3, 4)
                answer_capture = re.search(r'(?:Answer|उत्तर|సమాధానం|ଉତ୍ତର|பதில்|ಉತ್ತರ)\s*[:=]\s*(.+)', line, re.IGNORECASE)
                normalized_answer = None
                if answer_capture:
                    answer_fragment = answer_capture.group(1).strip()
                    answer_fragment = re.sub(r'^[\-\s]+', '', answer_fragment)
                    letter_match = re.search(r'\b([A-D])\b', answer_fragment, re.IGNORECASE)
                    number_match = re.search(r'\b([1-5])\b', answer_fragment)
                    if letter_match:
                        normalized_answer = letter_match.group(1).upper()
                    elif number_match:
                        normalized_answer = number_match.group(1)
                    else:
                        paren_letter = re.search(r'\(([A-D])\)', answer_fragment, re.IGNORECASE)
                        option_letter = re.search(r'Option\s+([A-D])', answer_fragment, re.IGNORECASE)
                        if paren_letter:
                            normalized_answer = paren_letter.group(1).upper()
                        elif option_letter:
                            normalized_answer = option_letter.group(1).upper()
                if normalized_answer and normalized_answer.isdigit():
                    idx = int(normalized_answer)
                    if 1 <= idx <= 4:
                        normalized_answer = ['A', 'B', 'C', 'D'][idx - 1]
                if normalized_answer:
                    current_q['answer'] = f"Answer: {normalized_answer}"
                elif answer_capture:
                    current_q['answer'] = f"Answer: {answer_capture.group(1).strip()}"
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
            elif re.match(option_line_pattern, line, re.IGNORECASE):
                split_options = re.split(option_marker_pattern, line, flags=re.IGNORECASE)
                if len(split_options) > 3:  # Found multiple options in one line
                    for i in range(1, len(split_options), 2):
                        if i + 1 < len(split_options):
                            opt_marker = split_options[i]
                            opt_text = split_options[i + 1]
                            option_line = build_option_line(opt_marker, opt_text)
                            if option_line:
                                if not current_q.get('options'):
                                    current_q['options'] = []
                                current_q['options'].append(option_line)
                                print(f"DEBUG: Split concatenated option: '{line[:50]}' -> '{option_line[:30]}'")
                else:
                    option_match = re.match(r'^([A-E1-5][\)\.:])\s*(.*)', line, re.IGNORECASE)
                    marker = option_match.group(1) if option_match else None
                    opt_text = option_match.group(2) if option_match else line
                    option_line = build_option_line(marker, opt_text)
                    if option_line:
                        if not current_q.get('options'):
                            current_q['options'] = []
                        current_q['options'].append(option_line)
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
            elif re.search(option_marker_pattern, line, re.IGNORECASE):
                option_parts = re.split(option_marker_pattern, line)
                for i in range(1, len(option_parts), 2):
                    if i < len(option_parts):
                        opt_marker = option_parts[i]
                        opt_text = option_parts[i + 1]
                        option_line = build_option_line(opt_marker, opt_text)
                        if option_line:
                            if not current_q.get('options'):
                                current_q['options'] = []
                            current_q['options'].append(option_line)
                if not re.match(option_line_pattern, line, re.IGNORECASE):
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
        if not current_q.get('number'):
            auto_counter += 1
            current_q['number'] = str(auto_counter)
        if current_q['parts']:
            current_q['content'] += '<br>' + '<br>'.join(current_q['parts'])
        # Try to extract options from content if not found separately
        if not current_q.get('options') or len(current_q['options']) == 0:
            content_text = current_q.get('content', '')
            # Look for options in content - first try A), B), C), D)
            options_in_content = re.findall(r'([A-E1-5][\)\.:])\s*([^\n<]+)', content_text, re.IGNORECASE)
            if options_in_content and len(options_in_content) >= 2:
                formatted_options = []
                for marker, text_segment in options_in_content[:5]:
                    option_line = build_option_line(marker, text_segment)
                    if option_line:
                        formatted_options.append(option_line)
                if formatted_options:
                    current_q['options'] = formatted_options
            else:
                # Fallback: look for lines that start with just ")" - assign letters
                # Remove HTML tags first to get plain text, replace <br> with newline
                plain_text = re.sub(r'<br\s*/?>', '\n', content_text, flags=re.IGNORECASE)
                plain_text = re.sub(r'<[^>]+>', ' ', plain_text)
                # Split by newline and find lines starting with ")"
                lines = plain_text.split('\n')
                just_paren_options = []
                for line in lines:
                    line = line.strip()
                    if re.match(r'\)\s*[^\s)]', line):  # Line starts with ) followed by non-whitespace
                        # Extract text after )
                        opt_text = re.sub(r'^\)\s*', '', line).strip()
                        if opt_text and len(opt_text) > 0:
                            just_paren_options.append(opt_text)
                            if len(just_paren_options) >= 4:
                                break
                
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

option_marker_pattern = r'([A-E][\)\.:]|[1-5][\)\.:])'
option_line_pattern = r'^[A-E1-5][\)\.:]\s*'

def format_option_marker(raw_marker):
    if not raw_marker:
        return None
    marker = raw_marker.strip()
    if not marker:
        return None
    letter_match = re.match(r'([A-E])', marker, re.IGNORECASE)
    if letter_match:
        return f"{letter_match.group(1).upper()})"
    number_match = re.match(r'([1-5])', marker)
    if number_match:
        idx = int(number_match.group(1))
        if 1 <= idx <= 4:
            return f"{['A','B','C','D'][idx-1]})"
        return f"{number_match.group(1)})"
    return None

def build_option_line(marker, text):
    opt_text = (text or "").strip()
    if not opt_text:
        return None
    normalized_marker = format_option_marker(marker)
    if normalized_marker:
        return f"{normalized_marker} {opt_text}"
    return opt_text

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
                    # Debug: print options before rendering
                    print(f"DEBUG: Rendering options for Q{q['number']}: {q['options']}")
                    
                    # First, check if all options are in a single string (concatenated)
                    # If so, split them first
                    all_options_text = ' '.join(str(opt) for opt in q["options"])
                    option_count = len(re.findall(r'[A-E]\)|[1-5]\)', all_options_text, re.IGNORECASE))
                    
                    if option_count >= 2 and len(q["options"]) == 1:
                        # Single string with multiple options - split it
                        print(f"DEBUG: Found concatenated options in single string: {all_options_text[:100]}")
                        split_options = re.split(r'([A-E]\)|[1-5]\))', all_options_text, flags=re.IGNORECASE)
                        for i in range(1, len(split_options), 2):
                            if i + 1 < len(split_options):
                                opt_marker = split_options[i]
                                opt_text = split_options[i + 1].strip() if i + 1 < len(split_options) else ""
                                if opt_marker and opt_text:
                                    # Each option on its own line with proper spacing
                                    options_html += f'<div style="margin: 4px 0;"><span style="font-family: Arial, sans-serif; font-weight: bold;">{opt_marker}</span> {clean_text_html(opt_text)}</div>'
                                    print(f"DEBUG: Rendered option: {opt_marker} {opt_text[:30]}")
                    else:
                        # Options are already separate - render each one
                        for opt in q["options"]:
                            opt_clean = str(opt).strip()
                            # Check if this single option contains multiple concatenated options
                            split_options = re.split(r'([A-E]\)|[1-5]\))', opt_clean, flags=re.IGNORECASE)
                            
                            if len(split_options) > 3:  # Multiple options in one string
                                # Process each split option
                                for i in range(1, len(split_options), 2):
                                    if i + 1 < len(split_options):
                                        opt_marker = split_options[i]
                                        opt_text = split_options[i + 1].strip() if i + 1 < len(split_options) else ""
                                        if opt_marker and opt_text:
                                            # Each option on its own line with proper spacing
                                            options_html += f'<div style="margin: 4px 0;"><span style="font-family: Arial, sans-serif; font-weight: bold;">{opt_marker}</span> {clean_text_html(opt_text)}</div>'
                                            print(f"DEBUG: Split and rendered option: {opt_marker} {opt_text[:30]}")
                            else:
                                # Single option - extract marker and text
                                opt_match = re.match(r'^([A-E]\)|[1-5]\))\s*(.*)', opt_clean, re.IGNORECASE)
                                if opt_match:
                                    opt_marker = opt_match.group(1)
                                    opt_text = opt_match.group(2)
                                    # Each option on its own line (using <div> instead of <span> for proper line breaks)
                                    options_html += f'<div style="margin: 4px 0;"><span style="font-family: Arial, sans-serif; font-weight: bold;">{opt_marker}</span> {clean_text_html(opt_text)}</div>'
                                    print(f"DEBUG: Rendered single option: {opt_marker} {opt_text[:30]}")
                                else:
                                    # Fallback: try to find marker anywhere in option
                                    opt_marker_match = re.search(r'([A-E]\)|[1-5]\))', opt_clean, re.IGNORECASE)
                                    if opt_marker_match:
                                        marker_pos = opt_marker_match.start()
                                        opt_marker = opt_marker_match.group(1)
                                        opt_text = opt_clean[:marker_pos] + opt_clean[marker_pos + len(opt_marker):]
                                        options_html += f'<div style="margin: 4px 0;"><span style="font-family: Arial, sans-serif; font-weight: bold;">{opt_marker}</span> {clean_text_html(opt_text.strip())}</div>'
                                    else:
                                        # No marker found, display as-is but clean HTML
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
                        answer_label_match = re.search(r'(Answer|उत्तर|సమాధానం|ଉତ୍ତର|பதில்|ಉತ್ತರ)\s*[:=]\s*([A-Z0-9]+)', answer_text, re.IGNORECASE)
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
