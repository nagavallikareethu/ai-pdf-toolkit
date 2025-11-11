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


def normalize_question_content(text):
    """Normalize question text for consistent duplicate detection."""
    if not text:
        return ""
    normalized = re.sub(r"\s+", " ", str(text).strip().lower())
    patterns_to_remove = [
        r"^question\s*\d+[\.:]\s*",
        r"^q\s*\d+[\.:]\s*",
        r"\s*\([^)]*\)\s*",
        r"\s*\[[^\]]*\]\s*",
    ]
    for pattern in patterns_to_remove:
        normalized = re.sub(pattern, " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized

def is_duplicate_question(new_q_text, existing_questions, similarity_threshold=0.8):
    """Check if the provided question text is a duplicate of existing questions."""
    if not existing_questions or not new_q_text:
        return False

    new_q_normalized = normalize_question_content(new_q_text)
    if not new_q_normalized:
        return False

    for existing_q in existing_questions:
        existing_text = existing_q.get("text", "") or existing_q.get("question_text", "")
        existing_normalized = normalize_question_content(existing_text)
        if not existing_normalized:
            continue

        if new_q_normalized == existing_normalized:
            return True

        if (new_q_normalized in existing_normalized or existing_normalized in new_q_normalized) and len(new_q_normalized) > 25 and len(existing_normalized) > 25:
            return True

        new_words = set(new_q_normalized.split())
        existing_words = set(existing_normalized.split())
        if new_words and existing_words:
            overlap = len(new_words.intersection(existing_words))
            similarity = overlap / max(len(new_words), len(existing_words))
            if similarity > similarity_threshold:
                return True

    return False

def solve_pages(pages):
    print(f"=== Starting to process {len(pages)} pages ===")
    results = []
    processed_question_numbers = set()
    for page in tqdm(pages, desc="Solving pages"):
        before_page_results = len(results)
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
        # Extract ALL numbered questions without filtering by range
        question_matches = list(re.finditer(r'\b(\d{1,3})\.\s+', text))

        valid_questions = []
        for match in question_matches:
            q_num_str = match.group(1)
            try:
                q_num_int = int(q_num_str)
                if 1 <= q_num_int <= 999:
                    if q_num_str in processed_question_numbers:
                        print(f"DEBUG: Skipping already processed question {q_num_str}")
                        continue
                    valid_questions.append(match)
            except ValueError:
                continue

        print(f"Page {page['page']}: Found {len(valid_questions)} potential questions")

        if len(valid_questions) > 0:
            page_questions = []
            processed_text_positions = set()
            for i, match in enumerate(valid_questions):
                q_num = match.group(1)
                match_start = match.start()

                if match_start in processed_text_positions:
                    print(f"DEBUG: Skipping duplicate question {q_num} at position {match_start}")
                    continue

                if i + 1 < len(valid_questions):
                    next_match_start = valid_questions[i + 1].start()
                    current_text = text[match_start:next_match_start]
                    question_end = None

                    qmark_match = re.search(r'\?[^\?]*?(?=\d{1,3}\.\s|Answer\s*[:=]|$)', current_text, re.IGNORECASE)
                    if qmark_match:
                        question_end = match_start + qmark_match.end()
                    else:
                        option_match = re.search(r'(?:1\)|2\)|3\)|4\)|5\))', current_text)
                        if option_match:
                            question_end = match_start + option_match.start()
                        else:
                            question_end = next_match_start - 50

                    if question_end and question_end > match_start:
                        end_pos = min(max(question_end, match_start), len(text))
                    else:
                        end_pos = min(next_match_start, len(text))
                else:
                    current_text = text[match_start:]
                    qmark_match = re.search(r'\?[^\?]*?(?=\d{1,3}\.\s|Answer\s*[:=]|$)', current_text, re.IGNORECASE)
                    if qmark_match:
                        end_pos = min(match_start + qmark_match.end(), len(text))
                    else:
                        end_pos = len(text)

                end_pos = max(end_pos, match_start)
                q_text = text[match_start:end_pos].strip()
                processed_text_positions.add(match_start)

                if is_duplicate_question(q_text, page_questions) or is_duplicate_question(q_text, results):
                    print(f"DEBUG: Skipping duplicate content for question {q_num}")
                    continue

                cleaning_patterns = [
                    r"Sreedhar's\s+CCE",
                    r'SBI\s+CLERK',
                    r'LIC\s+Asst\.',
                    r'PRELIMS\s+MT',
                    r'NIACL\s+Asst\.',
                    r'TIER-I',
                    r'NUMERICAL\s+ABILITY',
                    r'Directions\s*\([^)]+\)',
                    r'Study\s+the\s+data\s+carefully',
                    r'answer\s+the\s+following\s+questions',
                    r'The\s+Bar-chart\s+shows',
                    r'Years\s+in\s+Lakhs',
                    r'MODEL\s+TEST',
                ]

                for pattern in cleaning_patterns:
                    q_text = re.sub(pattern, '', q_text, flags=re.IGNORECASE)

                q_text = re.sub(r'\s+', ' ', q_text).strip()

                if not q_text or re.match(r'^\d+\.?\s*$', q_text):
                    continue

                options_text = ""
                full_text_segment = text[match_start:end_pos]

                option_match = re.search(r'1\)\s+([^0-9]+?)\s+2\)\s+([^0-9]+?)(?:\s+3\)\s+([^0-9]+?))?(?:\s+4\)\s+([^0-9]+?))?(?:\s+5\)\s+([^0-9]+?))?', full_text_segment, re.IGNORECASE)

                if option_match:
                    options_parts = []
                    for idx in range(1, (option_match.lastindex or 0) + 1):
                        if option_match.group(idx):
                            opt_text = option_match.group(idx).strip()
                            opt_text = re.sub(r'^\d+\)\s*', '', opt_text)
                            options_parts.append(f"{idx}) {opt_text}")
                    if options_parts:
                        options_text = " ".join(options_parts)
                else:
                    option_lines = re.findall(r'\)\s*([^\n\d\)]+)', full_text_segment, re.IGNORECASE)
                    if len(option_lines) >= 2:
                        options_parts = []
                        for idx, opt_line in enumerate(option_lines[:5], start=1):
                            opt_clean = opt_line.strip()
                            if opt_clean:
                                options_parts.append(f"{idx}) {opt_clean}")
                        if options_parts:
                            options_text = " ".join(options_parts)
                    else:
                        option_pattern = re.findall(r'([1-5]\)\s*[^\n]+)', full_text_segment, re.IGNORECASE)
                        if len(option_pattern) >= 2:
                            options_text = " ".join([opt.strip() for opt in option_pattern[:5]])

                if options_text:
                    options_text = re.sub(r"Sreedhar's\s+CCE[^1-5]*", '', options_text, flags=re.IGNORECASE)
                    options_text = re.sub(r'SBI\s+CLERK[^1-5]*', '', options_text, flags=re.IGNORECASE)
                    options_text = re.sub(r'MODEL\s+TEST[^1-5]*', '', options_text, flags=re.IGNORECASE)
                    options_text = re.sub(r'^\d+\.\s*', '', options_text)
                    options_text = options_text.strip()

                is_data_description = (
                    re.search(r'^(Class\s+[ABC]:|Total\s+no\.\s+of\s+students\s+are)', q_text, re.IGNORECASE) or
                    re.search(r'students\s+are\s+in\s+group\s+[XYZ]', q_text, re.IGNORECASE) or
                    re.search(r'Ratio\s+of\s+the\s+number\s+of\s+students', q_text, re.IGNORECASE) or
                    re.search(r'no\.\s+of\s+students\s+in\s+group', q_text, re.IGNORECASE)
                )

                if is_data_description and '?' not in q_text:
                    continue

                if len(q_text) < 15 and '?' not in q_text:
                    continue

                processed_question_numbers.add(q_num)
                page_questions.append({"num": q_num, "text": q_text, "options": options_text})

            print(f"Page {page['page']}: Processing {len(page_questions)} questions")

            if page_questions:
                page_context = text[:2000]
                batch_size = 5

                for batch_start in range(0, len(page_questions), batch_size):
                    batch = page_questions[batch_start:batch_start + batch_size]

                    batch_question_numbers = {pq['num'] for pq in batch}
                    existing_numbers = {str(q.get('question_number', '')) for q in results if q.get('question_number')}
                    duplicate_numbers = batch_question_numbers.intersection(existing_numbers)
                    if duplicate_numbers:
                        print(f"DEBUG: Skipping batch with duplicate question numbers: {duplicate_numbers}")
                        continue

                    batch_has_duplicates = False
                    for pq in batch:
                        if is_duplicate_question(pq['text'], results):
                            print(f"DEBUG: Skipping batch due to content duplicate: Q{pq['num']}")
                            batch_has_duplicates = True
                            break
                    if batch_has_duplicates:
                        continue

                    if batch_start > 0:
                        time.sleep(0.5)

                    questions_text = ""
                    for pq in batch:
                        options_section = ""
                        if pq.get('options'):
                            options_section = f"\nOPTIONS: {pq['options']}"
                        questions_text += f"\n\nQUESTION {pq['num']}:\n{pq['text']}{options_section}\n"

                    prompt = f"""You are an expert exam solver. Solve these {len(batch)} questions completely.

PAGE CONTEXT (may contain chart/table data):
{page_context}
{questions_text}

IMPORTANT:
1. Use the page context above if the questions reference data, charts, or tables
2. If a question appears incomplete, try to solve it with available information
3. Provide the correct answer option (1, 2, 3, 4, or 5) based on the options provided
4. Provide a complete 2-3 line explanation showing your calculation or reasoning

Return ONLY a JSON array (no markdown, no code blocks). Start with [ and end with ]:
[
  {{"question_number": "31", "question_text": "...", "options": "...", "answer": "1", "explanation": "..."}},
  {{"question_number": "32", "question_text": "...", "options": "...", "answer": "2", "explanation": "..."}}
]

Return ONLY the JSON array:"""
                    try:
                        response = model.generate_content(prompt)
                        raw_output = extract_json_block(response.text)
                        parsed = None
                        try:
                            parsed = json.loads(raw_output)
                        except Exception:
                            parsed = extract_inner_json(raw_output)
                        if parsed and isinstance(parsed, list):
                            existing_numbers = {str(r.get('question_number', '')) for r in results if r.get('question_number')}
                            new_items = []
                            for item in parsed:
                                q_num = str(item.get('question_number') or item.get('question_num') or '')
                                if not q_num:
                                    q_num = str(item.get('num') or '')
                                item['question_number'] = q_num
                                if q_num and q_num in existing_numbers:
                                    print(f"DEBUG: Skipping duplicate question {q_num} in batch results")
                                    continue
                                existing_numbers.add(q_num)
                                new_items.append(item)
                            if new_items:
                                results.extend(new_items)
                            else:
                                print("DEBUG: All batch items were duplicates")
                        else:
                            print(f"Failed to parse model output on page {page['page']}:")
                            print(raw_output)
                    except Exception as e:
                        print(f"Error processing batch on page {page['page']}: {e}")

        added_count = len(results) - before_page_results
        print(f"Page {page['page']}: Added {added_count} questions, total results: {len(results)}")

    # Sort results by question_number to maintain sequence
    def get_qnum(q):
        qnum = q.get("question_number", "")
        try:
            return int(qnum)
        except (ValueError, TypeError):
            # If not a number, try to extract from question_text
            match = re.search(r'^(\d+)\.', str(q.get("question_text", "")))
            if match:
                try:
                    return int(match.group(1))
                except:
                    pass
            return 9999  # Put unnumbered items at the end
    
    results.sort(key=get_qnum)

    unique_results = []
    seen_question_numbers = set()
    seen_question_texts = set()
    seen_combined_signatures = set()
    for item in results:
        q_text = (item.get("question_text") or "").strip().lower()
        q_num = str(item.get("question_number", ""))
        if not q_text or len(q_text) < 10:
            continue
        text_sig = q_text[:150]
        combined_sig = f"{q_num}:{q_text[:100]}"
        if (q_num and q_num in seen_question_numbers) or (text_sig in seen_question_texts) or (combined_sig in seen_combined_signatures):
            print(f"DEBUG: Removing final duplicate - Q{q_num}")
            continue
        if q_num:
            seen_question_numbers.add(q_num)
        seen_question_texts.add(text_sig)
        seen_combined_signatures.add(combined_sig)
        unique_results.append(item)

    print(f"Final duplicate removal: {len(results)} -> {len(unique_results)} questions")
    results = unique_results

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
        opts = item.get("options", "")
        a = item.get("answer", "")
        e = item.get("explanation", "")

        # Add delay between requests to avoid rate limits
        # Free tier is 250 requests/day, so add delays to spread requests out
        if idx > 0:
            time.sleep(1)  # Reduced delay to 1 second between translations

        # Include options in prompt if available
        options_section = ""
        if opts:
            options_section = f"\nOriginal Options: {opts}"

        prompt = f"""Translate the following solved MCQ into {target_lang}. 

IMPORTANT INSTRUCTIONS:
1. Translate the question_text completely into {target_lang} with proper spacing between words
2. Translate the options completely into {target_lang} with proper spacing, keeping the format "1) option1 2) option2 ..."
3. For answer: Keep numbers and option numbers unchanged (e.g., "3", "2", "15%"). Only translate if it's text.
4. Translate the explanation completely into {target_lang} with proper spacing. Include all calculations and reasoning in {target_lang}.

CRITICAL: You MUST return ONLY valid JSON (no markdown, no code blocks, no explanations, no additional text). The response must start with {{ and end with }}.

Required JSON format (copy this structure exactly):
{{
  "question_text_{lang_lower}": "fully translated question in {target_lang} with proper spacing",
  "options_{lang_lower}": "fully translated options in {target_lang} in format '1) option1 2) option2 3) option3 4) option4 5) option5'",
  "answer_{lang_lower}": "{a}",
  "explanation_{lang_lower}": "fully translated explanation in {target_lang} with proper spacing, including all calculations"
}}

DO NOT include any text before or after the JSON object. Start with {{ and end with }}.

Original Question: {q}{options_section}
Original Answer: {a}
Original Explanation: {e}

Return ONLY the JSON object:"""
        
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
                    o_key = f"options_{lang_lower}"
                    a_key = f"answer_{lang_lower}"
                    e_key = f"explanation_{lang_lower}"
                    
                    # Try to find fields in the response text
                    q_match = re.search(rf'"{q_key}"\s*:\s*"([^"]+)"', response_text, re.IGNORECASE)
                    o_match = re.search(rf'"{o_key}"\s*:\s*"([^"]+)"', response_text, re.IGNORECASE)
                    a_match = re.search(rf'"{a_key}"\s*:\s*"([^"]+)"', response_text, re.IGNORECASE)
                    e_match = re.search(rf'"{e_key}"\s*:\s*"([^"]+)"', response_text, re.IGNORECASE)
                    
                    if q_match:
                        fallback_parsed[q_key] = q_match.group(1)
                    if o_match:
                        fallback_parsed[o_key] = o_match.group(1)
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
                        # Translation failed - don't mark as success, retry if attempts remaining
                        if attempt < max_retries - 1:
                            print(f"Warning: Translation extraction failed for question {item.get('question_number', '?')}. Retrying... (Attempt {attempt + 1}/{max_retries})")
                            time.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                        else:
                            # Final attempt failed - save with error but still add to list
                            print(f"Error: Could not extract translation for question {item.get('question_number', '?')} after {max_retries} attempts. Using original text.")
                            merged = {**item, f"translation_error_{lang_lower}": "Failed to extract translation", f"raw_translation_{lang_lower}": response_text}
                            translated.append(merged)
                            success = True  # Mark as processed to continue
                            break
                        
            except Exception as err:
                error_str = str(err)
                # Check if it's a rate limit/quota error
                is_quota_error = "429" in error_str or "quota" in error_str.lower() or "rate limit" in error_str.lower()
                
                if is_quota_error:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)  # Exponential backoff: 2s, 4s, 8s
                        print(f"Quota/Rate limit hit for question {item.get('question_number', '?')}, waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                        retry_delay *= 2
                        continue
                    else:
                        # Max retries exceeded - save with original English text (skip translation)
                        print(f"Quota exceeded for question {item.get('question_number', '?')}. Using original English text.")
                        # Don't add translation_error - just use original text
                        merged = {**item}
                        # Keep original English text instead of failing translation
                        translated.append(merged)
                        success = True
                        break
                else:
                    # Not a rate limit error - retry once more, then give up
                    if attempt < max_retries - 1:
                        print(f"Warning: Translation error for question {item.get('question_number', '?')}: {err}. Retrying... (Attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        # Final attempt failed - save with original English text (skip translation)
                        print(f"Translation failed for question {item.get('question_number', '?')}. Using original English text.")
                        merged = {**item}
                        translated.append(merged)
                        success = True
                        break
        
        if not success and f"translation_error_{lang_lower}" not in item:
            # If translation completely failed, use original English text (don't add error fields)
            merged = {**item}
            translated.append(merged)
            print(f"Translation skipped for question {item.get('question_number', '?')} after all retries. Using original text.")

    # Sort translated results by question_number to maintain sequence
    def get_qnum_translated(q):
        qnum = q.get("question_number", "")
        try:
            return int(qnum)
        except (ValueError, TypeError):
            # If not a number, try to extract from question_text
            match = re.search(r'^(\d+)\.', str(q.get("question_text", "") or q.get(f"question_text_{lang_lower}", "")))
            if match:
                try:
                    return int(match.group(1))
                except:
                    pass
            return 9999  # Put unnumbered items at the end
    
    translated.sort(key=get_qnum_translated)
    
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
        "odia":   ("ଉତ୍ତର", "ବ୍ୟାଖ୍ୟା", "ଓଡ଼ିଆରେ ଅନୁବାଦିତ ପ୍ରశ్ନପତ୍ର"),
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
        opts = clean(item.get(f"options{suffix}", "")) or clean(item.get("options", ""))
        ans = clean(item.get(f"answer{suffix}", "")) or clean(item.get("answer", ""))
        exp = clean(item.get(f"explanation{suffix}", "")) or clean(item.get("explanation", ""))

        if not (q_text or ans or exp):
            continue

        parts.append("<div class='question'>")
        parts.append(f"<h2>Q{q_no}.</h2>")
        if q_text:
            parts.append(f"<p>{q_text}</p>")
        if opts:
            parts.append(f"<p><b>Options:</b> {opts}</p>")
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
        "odia":   ("ଉତ୍ତର", "ବ୍ୟାଖ୍ୟା", "ଓଡ଼ିଆରେ ଅନୁବାଦିତ ପ୍ରశ్ନପତ୍ର"),
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
        opts = clean(item.get(f"options{suffix}", "")) or clean(item.get("options", ""))
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
                    pass
        
        # Options (Use Telugu font with wrapping)
        if opts:
            y -= 10
            c.setFont("Helvetica-Bold", 11)
            c.drawString(70, y, "Options:")
            y -= 15
            try:
                y = draw_wrapped_text(c, opts, 70, y, available_width, font_name, 11)
            except Exception as font_error:
                try:
                    c.setFont("Helvetica", 11)
                    c.drawString(70, y, opts if lang == "english" else "[Font error]")
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