# 🌐 Translation System Prompts - All Modules

**Date:** November 17, 2025  
**Purpose:** Document all translation prompts and context used across the 3 modules

---

## 📋 **Overview**

The system uses **3 different translation approaches** depending on the module:

| Module | Translation Method | Language Support | API Used |
|--------|-------------------|------------------|----------|
| **translate.py** | Google Translate API | 9 languages | Google Translator |
| **solution.py** | LLM-based (Gemini) | 9 languages | Google Gemini 2.0 |
| **generate.py** | Direct generation in target language | Hindi, Odia | Google Gemini 2.5 Pro |

---

## 1️⃣ **translate.py - Google Translate API**

### **Translation Method:**
Direct API call using `deep_translator.GoogleTranslator`

### **Translation Context:**
```python
# No explicit prompt - uses Google Translate API directly
GoogleTranslator(source="auto", target=target_lang).translate(text)
```

### **Key Features:**
- **Source detection:** Automatic language detection
- **Target languages:** hi, te, or, ta, ml, bn, gu, pa, mr
- **Retry logic:** 3 attempts with 2-second delays
- **Content filtering:** Skips mathematical/numeric content

### **Translation Rules:**
```python
# Content is translated ONLY if:
1. content_type != 'mathematical'
2. content_type != 'normal_text' (pure numbers/symbols)
3. Not in math_numeric_content section
4. translation_ready == True
```

### **Supported Languages:**
```python
LANG_OPTIONS = {
    "1": ("hi", "Hindi"),
    "2": ("te", "Telugu"),
    "3": ("or", "Odia"),
    "4": ("ta", "Tamil"),
    "5": ("ml", "Malayalam"),
    "6": ("bn", "Bengali"),
    "7": ("gu", "Gujarati"),
    "8": ("pa", "Punjabi"),
    "9": ("mr", "Marathi")
}
```

### **Example Translation Flow:**
```
Input Text: "What is the sum of 2 + 2?"
↓
Content Type Check: instruction (translatable)
↓
Google Translate API: auto → hi
↓
Output: "2 + 2 का योग क्या है?"
```

---

## 2️⃣ **solution.py - Gemini LLM Translation**

### **Translation Method:**
LLM-based translation with structured JSON output

### **System Prompt:**

```python
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
```

### **Key Features:**
- **Model:** Google Gemini 2.0 Flash
- **Output format:** Structured JSON
- **Retry logic:** 3 attempts with exponential backoff
- **Timeout:** 60 seconds per request
- **Context preservation:** Numbers, symbols, math expressions unchanged

### **Translation Rules:**
```
1. Translate question text → question_text_{lang}
2. Translate answer text → answer_{lang}
3. Translate explanation → explanation_{lang}
4. PRESERVE: All numbers (2, 20%, ₹120)
5. PRESERVE: All symbols (+, -, ×, ÷, =)
6. PRESERVE: All math expressions (2x + 5 = 10)
```

### **Supported Languages:**
```python
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
```

### **Example Input/Output:**

**Input:**
```json
{
  "question_text": "What is 2 + 2?",
  "answer": "4",
  "explanation": "Adding 2 and 2 gives 4"
}
```

**Output (Hindi):**
```json
{
  "question_text": "What is 2 + 2?",
  "answer": "4",
  "explanation": "Adding 2 and 2 gives 4",
  "question_text_hindi": "2 + 2 क्या है?",
  "answer_hindi": "4",
  "explanation_hindi": "2 और 2 को जोड़ने पर 4 मिलता है"
}
```

---

## 3️⃣ **generate.py - Direct Language Generation**

### **Translation Method:**
Direct MCQ generation in target language (not translation)

### **System Prompt:**

```python
prompt = f"""IMPORTANT: You MUST follow EXACT formatting rules for {language_display} MCQs. FAILURE TO FOLLOW FORMAT WILL RESULT IN REJECTION.

TASK: Generate exactly {n} multiple-choice questions in {language_display} based on the document.

NON-NEGOTIABLE FORMAT RULES:
1. QUESTION FORMAT: "1. [Question text?]"
2. OPTION FORMAT: Use ONLY "A)", "B)", "C)", "D)" - NEVER use numbers or local scripts
3. ANSWER FORMAT: Use ONLY "Answer: X" where X is A, B, C, or D
4. NUMBER FORMAT: Keep all numbers as digits (20%, ₹120, etc.) - DO NOT translate numbers

EXAMPLE FORMAT - COPY EXACTLY:
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

ABSOLUTELY FORBIDDEN:
- DO NOT use 1) 2) 3) 4) or १) २) ३) ④) for options
- DO NOT use "उत्तर:" or any non-English answer label
- DO NOT put multiple options on one line
- DO NOT forget the question mark

DOCUMENT CONTENT:
{pdf_text[:6000]}

NOW GENERATE {n} QUESTIONS FOLLOWING THE EXAMPLE EXACTLY. EACH QUESTION MUST HAVE:
1. Number with dot (1. 2. 3. etc.)
2. Question ending with ?
3. Four options with A) B) C) D)
4. Answer line with "Answer: X"

BEGIN NOW:"""
```

### **Key Features:**
- **Model:** Google Gemini 2.5 Pro
- **Languages:** Hindi, Odia (specialized)
- **Output format:** Plain text with strict structure
- **Format enforcement:** Heavy emphasis on consistent formatting
- **Post-processing:** Automatic correction for common format issues

### **Critical Format Rules:**

```
✅ CORRECT FORMAT:
1. प्रश्न यहाँ लिखें?
A) विकल्प 1
B) विकल्प 2
C) विकल्प 3
D) विकल्प 4
Answer: B

❌ WRONG FORMATS:
- Using: 1) 2) 3) 4) for options
- Using: १) २) ३) ④) (Devanagari numbers)
- Using: "उत्तर: B" instead of "Answer: B"
- Missing question marks
- Multiple options on one line
```

### **Example for Hindi:**

```text
1. भारत की राजधानी क्या है?
A) मुंबई
B) दिल्ली
C) कोलकाता
D) चेन्नई
Answer: B
```

### **Example for Odia:**

```text
1. ଭାରତର ରାଜଧାନୀ କ'ଣ?
A) ମୁମ୍ବାଇ
B) ନୟା ଦିଲ୍ଲୀ
C) କୋଲକାତା
D) ଚେନ୍ନାଇ
Answer: B
```

---

## 📊 **Comparison Table**

| Feature | translate.py | solution.py | generate.py |
|---------|-------------|-------------|-------------|
| **Method** | Google Translate API | Gemini LLM | Gemini Generation |
| **Prompt Type** | None (API) | Structured JSON | Strict format rules |
| **Model** | N/A | Gemini 2.0 Flash | Gemini 2.5 Pro |
| **Languages** | 9 (all Indian) | 9 (all Indian) | 2 (Hindi, Odia) |
| **Input** | Extracted text | Solved MCQs | PDF document |
| **Output** | Translated text | JSON with translations | Formatted MCQs |
| **Math Handling** | Skip (don't translate) | Preserve | Keep as digits |
| **Retry Logic** | 3 attempts | 3 attempts | No retry |
| **Timeout** | None | 60 seconds | Default |
| **Use Case** | Full PDF translation | Solution translation | New MCQ creation |

---

## 🎯 **Common Translation Principles**

### **Across All Modules:**

1. **Preserve Numbers:** Never translate digits (2, 20, 120)
2. **Preserve Symbols:** Keep math symbols unchanged (+, -, ×, ÷, =, %)
3. **Preserve Currency:** Keep ₹, $, etc. as-is
4. **Preserve Math Expressions:** Don't translate "2x + 5 = 10"
5. **Skip Pure Math Content:** Don't translate content_type='mathematical'

### **Content Type Classification:**

```python
# What gets translated:
✅ 'instruction'  - "Directions (1-5): Read the passage..."
✅ 'question'     - "What is the capital of India?"
✅ 'option'       - "A) Mumbai"
✅ 'normal_text'  - Regular paragraphs

# What gets skipped:
❌ 'mathematical' - "2x + 5 = 10"
❌ Pure numbers   - "30 a"
❌ Symbols only   - "< > ≤ ≥"
```

---

## 🔧 **API Configuration**

### **Environment Variables:**

```bash
# For solution.py and generate.py
GENAI_API_KEY=your_gemini_api_key_here
GENAI_MODEL=models/gemini-2.0-flash-exp

# For translate.py
# No API key needed (uses free Google Translate)
```

### **Model Selection:**

```python
# solution.py (Fast translation)
model = genai.GenerativeModel("gemini-2.0-flash-exp")

# generate.py (Quality generation)
model = genai.GenerativeModel("gemini-2.5-pro")

# translate.py (Free API)
translator = GoogleTranslator(source="auto", target=target_lang)
```

---

## 📝 **Usage Examples**

### **1. translate.py - Full PDF Translation**

```bash
python translate.py input.pdf --lang hi
```

**What happens:**
1. Extract PDF → JSON
2. Classify content types (instruction/question/mathematical)
3. Skip mathematical content
4. Translate using Google Translate API
5. Preserve coordinates and layout
6. Generate translated PDF with OverlayPDFGenerator

---

### **2. solution.py - Solve & Translate**

```bash
python solution.py
# Enter PDF path, select language
```

**What happens:**
1. Extract PDF content
2. Solve equations (SymPy) and MCQs (Gemini)
3. Translate solutions using Gemini with structured prompt
4. Render translated PDF with solutions

---

### **3. generate.py - Generate MCQs in Language**

```bash
python generate.py
# Enter PDF, number of MCQs, select language
```

**What happens:**
1. Extract PDF text (first 6000 chars)
2. Send to Gemini 2.5 Pro with strict format rules
3. Generate MCQs directly in target language
4. Parse and format output
5. Create PDF with generated questions

---

## 🎨 **Best Practices**

### **For translate.py:**
- Use for full document translation
- Best for preserving original layout
- Handles 9 Indian languages
- Free (no API costs)

### **For solution.py:**
- Use for exam question translation with solutions
- Best for structured MCQ format
- Requires Gemini API key
- Handles explanations well

### **For generate.py:**
- Use for creating NEW questions in target language
- Best for Hindi and Odia (tested extensively)
- Requires Gemini API key
- Strict format enforcement

---

## ⚙️ **Configuration Files**

### **Update Prompts:**

**solution.py** (Line 339-353):
```python
prompt = f"""
Translate the following solved MCQ into {target_lang}.
[MODIFY THIS PROMPT HERE]
"""
```

**generate.py** (Line 130-170):
```python
prompt = f"""IMPORTANT: You MUST follow...
[MODIFY THIS PROMPT HERE]
"""
```

**translate.py** (No prompt - API-based):
```python
# Modify translation behavior:
GoogleTranslator(source="auto", target=target_lang).translate(text)
```

---

## 📞 **Troubleshooting**

### **If Translations are Wrong:**

**For translate.py:**
- Check content_type classification
- Verify text is not marked as 'mathematical'
- Check Google Translate API limits

**For solution.py:**
- Increase timeout (line 50: `timeout=60`)
- Check API key and quota
- Verify JSON parsing in response

**For generate.py:**
- Check format enforcement rules
- Verify language examples in prompt
- Test with smaller number of questions

---

## ✅ **Summary**

This document provides the complete translation context for all 3 modules:

1. ✅ **translate.py** → Google Translate API (no prompt)
2. ✅ **solution.py** → Gemini LLM with structured JSON prompt
3. ✅ **generate.py** → Gemini with strict format enforcement prompt

All modules follow common principles:
- Preserve numbers, symbols, and math
- Support Indian languages
- Handle content type classification
- Provide retry/error handling

---

**Created:** November 17, 2025  
**Modules Documented:** translate.py, solution.py, generate.py  
**Status:** ✅ Complete

