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
        # First, try to split text by question numbers BEFORE sending to Gemini
        # This helps ensure we extract questions individually
        # Match question numbers (typically 31-65, 2 digits, or single/double digit in some contexts)
        question_matches = list(re.finditer(r'\b(\d{1,2})\.\s+(?!\d+\s+[A-Z])', text))
        
        # Filter out invalid question numbers (too large to be question numbers like 136800, etc.)
        valid_questions = []
        for match in question_matches:
            q_num_str = match.group(1)
            try:
                q_num_int = int(q_num_str)
                # Question numbers should typically be 1-100 range for exam questions
                if 1 <= q_num_int <= 100:
                    valid_questions.append(match)
            except ValueError:
                continue
        
        if len(valid_questions) > 1:
            # Found multiple valid questions - process each separately
            page_questions = []
            for i, match in enumerate(valid_questions):
                q_num = match.group(1)
                start_pos = match.start()
                # Find end position (next question number or end of text)
                if i + 1 < len(valid_questions):
                    end_pos = valid_questions[i + 1].start()
                else:
                    end_pos = len(text)
                
                q_text = text[start_pos:end_pos].strip()
                # Clean the question text immediately to remove unwanted content
                q_text = re.sub(r'^\d+\.\s*\d+\s+[A-Z][^?]*?Sreedhar\'s\s+CCE[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'Sreedhar\'s\s+CCE[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'SBI\s+CLERK[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'LIC\s+Asst\.[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'PRELIMS\s+MT[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'NIACL\s+Asst\.[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'TIER-I[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'NUMERICAL\s+ABILITY[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'Directions\s*\([^)]+\)[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'Study\s+the\s+data\s+carefully[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'answer\s+the\s+following\s+questions[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'The\s+Bar-chart\s+shows[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'\d+\s+\d{4}\s+\d{4}[^?]*?', '', q_text)  # Remove chart axis
                q_text = re.sub(r'Years\s+in\s+Lakhs[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'MTS\s+CGL\s+CHSL[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                q_text = re.sub(r'MODEL\s+TEST[^?]*?', '', q_text, flags=re.IGNORECASE | re.DOTALL)
                
                # Find the actual question (starts with a meaningful word)
                question_start = re.search(r'(Find|Calculate|What|How|Which|Total|Average|Out\s+of|In\s+\d{4})', q_text, re.IGNORECASE)
                if question_start:
                    q_text = q_text[question_start.start():]
                
                # Extract complete question - should end with ? and have options or be complete
                # First, try to find a complete question ending with ?
                q_match = re.search(r'([^?]*\?)', q_text)
                if q_match:
                    q_text = q_match.group(1).strip()
                else:
                    # If no ?, the question might be incomplete - skip it or try to complete it
                    # Look for option markers (1), 2), 3), 4), 5)) or "Answer:" to mark end
                    option_match = re.search(r'1\)\s+[^0-9]+2\)\s+[^0-9]+3\)\s+[^0-9]+4\)\s+[^0-9]+5\)', q_text)
                    if option_match:
                        # Question continues to options, extract everything up to options
                        q_text = q_text[:option_match.start()].strip()
                    else:
                        # If question doesn't have ? and no options, it's likely incomplete
                        # Skip questions that are too short or don't look complete
                        if len(q_text) < 30 or not re.search(r'\?|Find|Calculate|What|How|Which|Total|Average', q_text, re.IGNORECASE):
                            continue  # Skip incomplete questions
                
                # Clean up: remove leading question number and any whitespace
                q_text = re.sub(rf'^{re.escape(q_num)}\.\s*', '', q_text).strip()
                
                # Validate question completeness - look for actual question content
                # Must have meaningful question text (not just numbers or metadata)
                has_question_words = re.search(r'(Find|Calculate|What|How|Which|Total|Average|Out\s+of|In\s+\d{4}|ratio|percent|number|students|amount|value|time|days|speed|probability|gain|loss)', q_text, re.IGNORECASE)
                
                # Check if it's a number series or pattern question
                is_pattern_question = re.search(r'^\d+\s+\d+\s+\d+\s+\?', q_text) or re.search(r'^\d+\s+\d+\s+\d+', q_text)
                
                # Check if question is complete (ends with ? or has options)
                has_question_mark = '?' in q_text
                has_options = re.search(r'1\)\s+|2\)\s+|3\)\s+|4\)\s+|5\)\s+', q_text)
                
                is_valid = (
                    has_question_words or 
                    is_pattern_question or
                    (has_question_mark and len(q_text) > 30) or
                    (has_options and len(q_text) > 40)
                )
                
                # Skip if too short, has no question content, or looks like data/metadata
                if not is_valid or len(q_text) < 20:
                    continue
                
                # Skip if it looks like a data value or metadata (e.g., "136800", "Total no. of students are")
                if re.search(r'^(Total\s+no\.|The\s+ratio|No\.\s+of)', q_text, re.IGNORECASE) and not has_question_mark:
                    # Only include if it has a question mark
                    if not has_question_mark:
                        continue
                
                page_questions.append({"num": q_num, "text": q_text})
            
            # Process each question individually with Gemini
            for pq in page_questions:
                prompt = f"""You are an expert exam solver. Solve this question completely.

Question {pq['num']}: {pq['text']}

IMPORTANT:
1. If the question appears incomplete or truncated, indicate that in the explanation
2. Provide the answer based on the data available
3. Provide a complete 2-3 line explanation of how to solve it

Return ONLY a JSON object (no array, no markdown, no code blocks):
{{
  "question_number": "{pq['num']}",
  "question_text": "{pq['text']}",
  "answer": "option_number_1_to_5",
  "explanation": "Complete 2-3 line explanation of the solution"
}}

Return the JSON object now:"""
                try:
                    response = model.generate_content(prompt)
                    raw_output = extract_json_block(response.text)
                    try:
                        parsed = json.loads(raw_output)
                        if isinstance(parsed, dict):
                            results.append(parsed)
                    except Exception:
                        # If JSON parsing fails, create a structured question from cleaned text
                        results.append({
                            "question_number": pq['num'],
                            "question_text": pq['text'],
                            "answer": "",
                            "explanation": ""
                        })
                except Exception as e:
                    results.append({
                        "question_number": pq['num'],
                        "question_text": pq['text'],
                        "error": str(e),
                        "method": "gemini_fallback"
                    })
            continue  # Skip the main prompt processing below
        
        # If no question splits found, use the original approach but with enhanced cleaning
        prompt = f"""You are an expert exam solver. Extract and solve ONLY the actual questions from the text below.

CRITICAL INSTRUCTIONS - READ CAREFULLY:
1. IGNORE COMPLETELY and DO NOT include in question_text ANY of the following:
   - Headers: "Sreedhar's CCE", "SBI CLERK", "LIC Asst.", "PRELIMS MT", "NIACL Asst.", "TIER-I", "MT - 15", "MT - 117"
   - Section titles: "NUMERICAL ABILITY"
   - Directions: "Directions (31-35):", "Study the data carefully", "answer the following questions"
   - Chart descriptions: "The Bar-chart shows students registered for three different exams..."
   - Chart data: "0 10 20 30 40 50 60", "2012 2013 2014 2015 2016", "Years in Lakhs", "MTS CGL CHSL"
   - Footer text: "SBI CLERK / LIC Asst. PRELIMS MODEL TEST - 117", "NIACL Asst. TIER-I MODEL TEST - 15"
   - Page numbers, option numbers that appear before questions
   
2. Extract ONLY the numbered questions (e.g., questions starting with "31.", "32.", "33.")

3. For EACH question found:
   - question_number: Extract the question number (e.g., "31", "32", "33")
   - question_text: Extract ONLY the actual question sentence/paragraph that ends with "?"
     * Start from the first word of the actual question (like "Find", "Calculate", "What", "How", "Which", "Total", "Average")
     * End at the question mark "?"
     * DO NOT include any headers, directions, or metadata before the question
     * Example CORRECT: "Find the ratio of total students registered for all the three exams in 2012 and 2013 together to total students registered for all the three exams in 2014 and 2015 together?"
     * Example WRONG: "31. 1 Sreedhar's CCE SBI CLERK... Find the ratio..." (DO NOT include "31. 1 Sreedhar's CCE...")
   - answer: The correct option number (e.g., "1", "2", "3", "4", "5") based on the data
   - explanation: A concise 2-line explanation of how to solve this question

4. If you see multiple questions on a page, extract ALL of them separately.

CRITICAL: Return ONLY a JSON array (no markdown, no code blocks, no other text). Start with [ and end with ].
Example format:
[
  {{"question_number": "31", "question_text": "Find the ratio of total students registered for all the three exams in 2012 and 2013 together to total students registered for all the three exams in 2014 and 2015 together?", "answer": "3", "explanation": "Calculate totals for 2012+2013 and 2014+2015, then find ratio."}},
  {{"question_number": "32", "question_text": "Average number of students registered for MTS exam in all the five years together is how much less/more than the average number of students registered for CHSL exam in all the five years together?", "answer": "2", "explanation": "Calculate average MTS and average CHSL from the data, then find difference."}}
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
                
                # Clean extracted questions to remove headers/directions
                if isinstance(parsed, list):
                    for q in parsed:
                        q_text = q.get("question_text", "")
                        if q_text:
                            # Step 1: Find the actual question number pattern (e.g., "31.", "32.")
                            q_num = q.get("question_number", "")
                            if q_num:
                                # Try to find text starting from this question number
                                pattern = rf'\b{q_num}\.\s*'
                                match = re.search(pattern, q_text, re.IGNORECASE)
                                if match:
                                    # Extract text starting from the question number
                                    q_text = q_text[match.start():]
                                else:
                                    # If pattern not found, look for any number followed by period
                                    match = re.search(rf'^\d+\.\s*{q_num}\.\s*', q_text)
                                    if match:
                                        q_text = q_text[match.end():]
                            
                            # Step 2: Remove all unwanted headers/directions patterns
                            # Remove patterns that appear at the start (even after question number)
                            unwanted_patterns = [
                                r'^\d+\.\s*\d+\s+[A-Z][^?]*?Sreedhar\'s\s+CCE[^?]*?',
                                r'Sreedhar\'s\s+CCE[^?]*?',
                                r'SBI\s+CLERK[^?]*?',
                                r'LIC\s+Asst\.[^?]*?',
                                r'PRELIMS\s+MT[^?]*?',
                                r'NIACL\s+Asst\.[^?]*?',
                                r'TIER-I\s+MT[^?]*?',
                                r'NUMERICAL\s+ABILITY[^?]*?',
                                r'Directions\s*\([^)]+\)[^?]*?',
                                r'Study\s+the\s+data\s+carefully[^?]*?',
                                r'answer\s+the\s+following\s+questions[^?]*?',
                                r'The\s+Bar-chart\s+shows[^?]*?',
                                r'MODEL\s+TEST[^?]*?',
                                r'\d+\s+\d{4}\s+\d{4}[^?]*?',  # Remove chart axis labels like "0 10 20 30..."
                                r'Years\s+in\s+Lakhs[^?]*?',
                                r'MTS\s+CGL\s+CHSL[^?]*?(?=\d+\.)',  # Remove legend but keep if followed by question number
                            ]
                            
                            for pattern in unwanted_patterns:
                                q_text = re.sub(pattern, '', q_text, flags=re.IGNORECASE | re.DOTALL)
                            
                            # Step 3: Find the actual question (starts with a capital letter or number, ends with ?)
                            # Try to extract from first meaningful sentence that ends with ?
                            question_match = re.search(r'([A-Z][^?]*?\?)', q_text)
                            if question_match:
                                q_text = question_match.group(1)
                            else:
                                # Fallback: remove everything before the first meaningful question text
                                # Look for patterns like "Find the", "Calculate", "What is", etc.
                                question_start = re.search(r'(Find|Calculate|What|How|Which|Total|Average|Out\s+of|In\s+\d{4})', q_text, re.IGNORECASE)
                                if question_start:
                                    q_text = q_text[question_start.start():]
                            
                            # Step 4: Remove any remaining unwanted text before question
                            # Remove any leading numbers or metadata patterns
                            q_text = re.sub(r'^\d+\.\s*\d+\s+[A-Z\s/]+', '', q_text)  # Remove "31. 1 SBI CLERK / LIC"
                            q_text = re.sub(r'^\d+\.\s*[A-Z][^A-Z]*?(?=[A-Z][a-z])', '', q_text)  # Remove leading metadata
                            
                            # Step 5: Clean up multiple spaces and normalize
                            q_text = re.sub(r'\s+', ' ', q_text).strip()
                            
                            # Step 6: Ensure question ends with ? and contains actual question words
                            if not q_text.endswith('?'):
                                # Try to find the question mark in the text
                                q_match = re.search(r'([^?]*\?)', q_text)
                                if q_match:
                                    q_text = q_match.group(1)
                            
                            q["question_text"] = q_text
                        
                        # Ensure question_number is present and clean
                        if "question_number" not in q or not q["question_number"]:
                            # Try to extract from question_text
                            match = re.search(r'^(\d+)\.', q_text)
                            if match:
                                q["question_number"] = match.group(1)
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

CRITICAL: You MUST return ONLY valid JSON (no markdown, no code blocks, no explanations, no additional text). The response must start with {{ and end with }}.

Required JSON format (copy this structure exactly):
{{
  "question_text_{lang_lower}": "translated question with proper spacing",
  "answer_{lang_lower}": "translated answer with proper spacing",  
  "explanation_{lang_lower}": "translated explanation with proper spacing"
}}

DO NOT include any text before or after the JSON object. Start with {{ and end with }}.

Original Question: {q}
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
                        # Translation failed - don't mark as success, retry if attempts remaining
                        if attempt < max_retries - 1:
                            print(f"Warning: Translation extraction failed for question {item.get('question_number', '?')}. Retrying... (Attempt {attempt + 1}/{max_retries})")
                            time.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                        else:
                            # Final attempt failed - store with error but still add to list
                            print(f"Error: Could not extract translation for question {item.get('question_number', '?')} after {max_retries} attempts. Using original text.")
                            merged = {**item, f"translation_error_{lang_lower}": "Failed to extract translation", f"raw_translation_{lang_lower}": response_text}
                            translated.append(merged)
                            success = True  # Mark as processed to continue
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
                    # Not a rate limit error - retry once more, then give up
                    if attempt < max_retries - 1:
                        print(f"Warning: Translation error for question {item.get('question_number', '?')}: {err}. Retrying... (Attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        # Final attempt failed - store with error but still add to list
                        item[f"translation_error_{lang_lower}"] = str(err)
                        translated.append(item)
                        print(f"Error: Translation failed for question {item.get('question_number', '?')} after {max_retries} attempts: {err}")
                        success = True  # Mark as processed to continue with next item
                        break
        
        if not success and f"translation_error_{lang_lower}" not in item:
            item[f"translation_error_{lang_lower}"] = "Translation failed after retries"
            translated.append(item)
            print(f"Error: Translation failed for question {item.get('question_number', '?')} after all retries.")

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