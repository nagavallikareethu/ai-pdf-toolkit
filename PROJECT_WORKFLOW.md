# 🔄 **Project Workflow**

**Project:** AI-Powered PDF Processing Toolkit  
**Version:** 1.0.0  
**Last Updated:** November 17, 2025

---

## 📋 **Table of Contents**

1. [Overview](#overview)
2. [Translation Workflow](#translation-workflow)
3. [Solution Generation Workflow](#solution-generation-workflow)
4. [MCQ Generation Workflow](#mcq-generation-workflow)
5. [CLI Workflow](#cli-workflow)
6. [Gradio Web UI Workflow](#gradio-web-ui-workflow)
7. [Development Workflow](#development-workflow)
8. [Deployment Workflow](#deployment-workflow)

---

## 🎯 **Overview**

This document describes the end-to-end workflows for using and developing the AI-Powered PDF Processing Toolkit. The system supports three main operations, each accessible through CLI or Web UI.

---

## 🌐 **Translation Workflow**

### **Purpose:** 
Translate PDF documents to Hindi or Odia while preserving formatting.

### **Step-by-Step Process:**

```
┌─────────────────────────────────────────────────────────────┐
│                   TRANSLATION WORKFLOW                      │
└─────────────────────────────────────────────────────────────┘

STEP 1: Upload/Input PDF
┌────────────────────────────────┐
│ User provides PDF file         │
│ - Web: Upload via Gradio UI   │
│ - CLI: File path as argument  │
└───────────────┬────────────────┘
                │
                ▼
STEP 2: PDF Extraction
┌────────────────────────────────┐
│ Extract content to JSON        │
│ ✓ Text blocks with coordinates│
│ ✓ Images with metadata        │
│ ✓ Layout elements (lines/etc) │
│ ✓ Page structure              │
│                                │
│ Output: *_extracted.json       │
└───────────────┬────────────────┘
                │
                ▼
STEP 3: Content Classification
┌────────────────────────────────┐
│ Classify content types         │
│ ✓ Mathematical content → skip │
│ ✓ Questions → translate       │
│ ✓ Instructions → translate    │
│ ✓ Normal text → translate     │
│ ✓ Options → translate         │
│                                │
│ 78 items translatable          │
│ 72 items skipped (math)       │
└───────────────┬────────────────┘
                │
                ▼
STEP 4: Translation
┌────────────────────────────────┐
│ Translate via Google Gemini    │
│ ✓ Process page by page        │
│ ✓ Preserve structure           │
│ ✓ Skip mathematical content   │
│ ✓ Retry on failures            │
│                                │
│ API calls: ~23 per page        │
│ Time: ~30-60s per page         │
│                                │
│ Output: *_extracted_hi.json    │
└───────────────┬────────────────┘
                │
                ▼
STEP 5: PDF Generation
┌────────────────────────────────┐
│ Overlay on original PDF        │
│ ✓ Load original PDF            │
│ ✓ Replace text with translation│
│ ✓ Preserve fonts & images      │
│ ✓ Maintain layout              │
│                                │
│ Method: OverlayPDFGenerator    │
│ Time: ~1-3s per page           │
│                                │
│ Output: *_hi.pdf               │
└───────────────┬────────────────┘
                │
                ▼
STEP 6: Download/Access
┌────────────────────────────────┐
│ Provide output to user         │
│ - Web: Download link           │
│ - CLI: File in outputs/        │
│                                │
│ ✓ Translated PDF ready         │
│ ✓ Original formatting preserved│
└────────────────────────────────┘
```

### **Detailed Steps:**

#### **Step 1: Upload/Input (0-5 seconds)**

**Web UI:**
1. User opens Gradio interface (http://localhost:7860)
2. Navigates to "Translation" tab
3. Uploads PDF file (drag & drop or browse)
4. Selects target language (Hindi/Odia)
5. Clicks "Translate PDF" button

**CLI:**
```bash
python translate.py "input.pdf" --lang hi
```

**Validation:**
- ✓ File exists
- ✓ File is PDF format
- ✓ File size < 50MB
- ✓ File is readable

---

#### **Step 2: PDF Extraction (2-5 seconds per page)**

**Process:**
```python
# Convert PDF to JSON
converter = PDFToJSONConverter()
pages = converter.convert_pdf_to_json_enhanced(
    pdf_path,
    output_json,
    include_images=True,
    image_handling="metadata"
)
```

**What's Extracted:**
```json
{
  "pages": [
    {
      "page_num": 1,
      "text_content": [
        {
          "content": "Question text here",
          "content_type": "normal_text",
          "coordinates": {"x": 100, "y": 200},
          "font": "Arial",
          "font_size": 12
        }
      ],
      "images": [...],
      "layout_elements": {
        "lines": [...],
        "vectors": [...]
      }
    }
  ]
}
```

**Output:** `input_extracted.json` (~280KB for 4-page PDF)

---

#### **Step 3: Content Classification (1-2 seconds)**

**Process:**
```python
# Reclassify mathematical content
change_mathematical_to_normal_text(json_path)

# Smart detection of content types
update_content_types_to_mathematical(json_path)

# Validate structure
verify_json_structure(json_path)
```

**Classification Examples:**

| Text | Before | After | Reason |
|------|--------|-------|--------|
| "Directions (31-35): Study..." | mathematical | instruction | Contains direction keywords |
| "30 a" | normal_text | (kept as normal_text) | Not pure math |
| "1) 11:15 2) 9:17..." | normal_text | mathematical | Pure numbers/options |
| "What is the ratio..." | mathematical | question | Contains question pattern |

**Result:**
- ✓ 78 blocks marked for translation
- ✓ 72 blocks marked as mathematical (skip)

---

#### **Step 4: Translation (30-60 seconds per page)**

**Process:**
```python
translator = JSONTranslator()
translated_json = translator.translate_json_file(
    extracted_json,
    lang_code="hi",
    lang_name="Hindi"
)
```

**Translation Flow:**
```
For each page:
  For each text block:
    If content_type == "mathematical":
      ⏭️  Skip (preserve as is)
    
    Else if translatable:
      🔄 Call Google Gemini API
      📝 Get translation
      ✅ Update JSON with translation
      
      On API error:
        ⚠️  Wait (exponential backoff)
        🔄 Retry (max 3 attempts)
```

**API Call Example:**
```python
prompt = f"""
Translate the following English text to Hindi.
Preserve numbers and mathematical expressions.

Text: {english_text}

Provide only the Hindi translation, nothing else.
"""

response = model.generate_content(prompt)
hindi_text = response.text
```

**Progress Tracking:**
```
📄 Page 1:
   🔄 TRANSLATING [1]: Sreedhar's CCE SBI CLERK...
   ✅ Translation successful (attempt 1)
   ⏭️  SKIPPED [8]: MTS CGL CHSL...
   📊 Page 1 summary: 20 translated, 11 skipped
```

**Output:** `translated_jsons/input_extracted_hi.json` (~320KB)

---

#### **Step 5: PDF Generation (1-3 seconds per page)**

**Process:**
```python
# Use overlay method (preserves formatting)
generator = OverlayPDFGenerator(
    translated_json,
    original_pdf,
    output_pdf
)
generator.generate_pdf()
```

**Overlay Process:**
1. Load original PDF as base
2. For each page:
   - Read text blocks from translated JSON
   - Calculate overlay positions
   - Render translated text at coordinates
   - Preserve images and layout
3. Save as new PDF

**Why Overlay vs Recreate:**

| Aspect | Recreate (PDFGenerator) | Overlay (OverlayPDFGenerator) |
|--------|------------------------|-------------------------------|
| Formatting | ❌ Lost | ✅ Preserved |
| Fonts | ❌ Generic | ✅ Original |
| Images | ❌ Missing | ✅ Intact |
| Layout | ❌ Changed | ✅ Exact |
| Speed | Slower | Faster |

**Output:** `outputs/input_hi.pdf` (~91KB)

---

#### **Step 6: Download/Access (Immediate)**

**Web UI:**
- ✅ Success message displayed
- 📊 File verification (MD5 hash shown)
- 📥 Download link appears
- Click to download translated PDF

**CLI:**
```bash
✅ Generated PDF: outputs/input_hi.pdf

=== PIPELINE SUMMARY ===
📄 Source PDF        : input.pdf
🧾 Extracted JSON    : outputs/input_extracted.json
🌐 Languages         : hi
💾 Translated JSONs  : 1 files
📚 Generated PDFs    : 1 files

✅ Pipeline completed successfully!
```

---

### **Error Handling:**

| Error Type | Handling | Recovery |
|-----------|----------|----------|
| **PDF not found** | Show error, ask for valid path | User re-uploads |
| **API rate limit** | Wait 10-30s, retry | Exponential backoff |
| **Translation failure** | Log error, skip item | Continue with others |
| **PDF generation error** | Fallback to JSON output | User notified |
| **Timeout** | Retry with longer timeout | Max 3 attempts |

---

## 🧮 **Solution Generation Workflow**

### **Purpose:**
Generate step-by-step solutions for mathematical problems in PDFs.

### **Step-by-Step Process:**

```
┌─────────────────────────────────────────────────────────────┐
│              SOLUTION GENERATION WORKFLOW                   │
└─────────────────────────────────────────────────────────────┘

STEP 1: Upload PDF with Questions
┌────────────────────────────────┐
│ User provides PDF with math    │
│ problems or questions          │
└───────────────┬────────────────┘
                │
                ▼
STEP 2: Extract Questions
┌────────────────────────────────┐
│ Parse PDF and identify         │
│ mathematical problems          │
│                                │
│ ✓ Detect equations             │
│ ✓ Extract question text        │
│ ✓ Capture context              │
└───────────────┬────────────────┘
                │
                ▼
STEP 3: Solve Problems
┌────────────────────────────────┐
│ Generate solutions             │
│                                │
│ Method 1: SymPy (algebra)      │
│ ├─ Parse equation              │
│ ├─ Solve symbolically          │
│ └─ Format solution             │
│                                │
│ Method 2: LLM (complex)        │
│ ├─ Send to Gemini              │
│ ├─ Get step-by-step solution   │
│ └─ Validate answer             │
└───────────────┬────────────────┘
                │
                ▼
STEP 4: Translate Solutions
┌────────────────────────────────┐
│ Translate to target language   │
│ (Hindi/Odia)                   │
│                                │
│ ✓ Preserve mathematical syntax │
│ ✓ Translate explanations       │
└───────────────┬────────────────┘
                │
                ▼
STEP 5: Render PDF
┌────────────────────────────────┐
│ Create PDF with solutions      │
│                                │
│ Using: Playwright + HTML       │
│ ✓ Professional formatting      │
│ ✓ Math rendered properly       │
│ ✓ Step-by-step layout          │
└───────────────┬────────────────┘
                │
                ▼
STEP 6: Download
┌────────────────────────────────┐
│ Provide solved PDF to user     │
└────────────────────────────────┘
```

### **Solving Methods:**

#### **Method 1: SymPy (Algebraic Equations)**

```python
from sympy import symbols, Eq, solve, sympify

def solve_math_equation(equation_text):
    x = symbols('x')
    
    # Example: "2x + 5 = 15"
    lhs, rhs = equation_text.split('=')
    equation = Eq(sympify(lhs), sympify(rhs))
    
    solutions = solve(equation, x)
    return solutions
```

**Use Cases:**
- Linear equations (2x + 5 = 15)
- Quadratic equations (x² - 4 = 0)
- Simultaneous equations
- Polynomial equations

---

#### **Method 2: LLM (Complex Problems)**

```python
def solve_with_llm(question):
    prompt = f"""
    Solve the following problem step by step:
    
    {question}
    
    Provide:
    1. Problem understanding
    2. Step-by-step solution
    3. Final answer
    """
    
    solution = call_llm_with_retry(prompt)
    return solution
```

**Use Cases:**
- Word problems
- Multi-step reasoning
- Geometry problems
- Statistics/probability

---

### **Time Estimates:**

| Step | Time |
|------|------|
| Extract | 2-5s per page |
| Solve (SymPy) | <1s per equation |
| Solve (LLM) | 10-30s per problem |
| Translate | 5-10s per solution |
| Render | 5-10s total |
| **Total** | **30s - 5min** |

---

## 📝 **MCQ Generation Workflow**

### **Purpose:**
Generate multiple-choice questions from PDFs or topics.

### **Step-by-Step Process:**

```
┌─────────────────────────────────────────────────────────────┐
│               MCQ GENERATION WORKFLOW                       │
└─────────────────────────────────────────────────────────────┘

STEP 1: Input (Choose One)
┌────────────────────────────────┐
│ Option A: Upload PDF           │
│   └─ Extract content           │
│   └─ Analyze topics            │
│                                │
│ Option B: Enter Topic          │
│   └─ Use topic directly        │
└───────────────┬────────────────┘
                │
                ▼
STEP 2: Configure
┌────────────────────────────────┐
│ Set parameters                 │
│ ├─ Number of questions (5-20) │
│ ├─ Language (Hindi/Odia)       │
│ └─ Difficulty (auto)           │
└───────────────┬────────────────┘
                │
                ▼
STEP 3: Generate Questions
┌────────────────────────────────┐
│ Create MCQs via Gemini         │
│                                │
│ For each question:             │
│ ├─ Generate question text      │
│ ├─ Create 4 options (A-D)      │
│ ├─ Mark correct answer         │
│ └─ Add explanation             │
└───────────────┬────────────────┘
                │
                ▼
STEP 4: Format Output
┌────────────────────────────────┐
│ Structure as JSON              │
│                                │
│ {                              │
│   "questions": [               │
│     {                          │
│       "question": "...",       │
│       "options": {...},        │
│       "answer": "B",           │
│       "explanation": "..."     │
│     }                          │
│   ]                            │
│ }                              │
└───────────────┬────────────────┘
                │
                ▼
STEP 5: Create PDF
┌────────────────────────────────┐
│ Render as formatted PDF        │
│                                │
│ ✓ Question numbering           │
│ ✓ Clear option layout          │
│ ✓ Answer key at end            │
└───────────────┬────────────────┘
                │
                ▼
STEP 6: Download
┌────────────────────────────────┐
│ Provide MCQ PDF to user        │
└────────────────────────────────┘
```

### **MCQ Format:**

```
Question 1: What is the capital of France?
A) London
B) Paris    ✓ (Correct)
C) Berlin
D) Madrid

Explanation: Paris is the capital and largest city of France.

---

Question 2: ...
```

---

## 💻 **CLI Workflow**

### **General CLI Pattern:**

```bash
# Translation
python translate.py <input.pdf> --lang <hi|or>

# Solution Generation
python solution.py <input.pdf> --lang <hi|or>

# MCQ Generation  
python generate.py --topic "<topic>" --count 10 --lang <hi|or>
python generate.py --pdf <input.pdf> --count 10 --lang <hi|or>
```

### **CLI Execution Flow:**

```
1. Parse arguments
   ├─ Validate input file
   ├─ Check language code
   └─ Verify API key

2. Load environment
   ├─ Read .env file
   ├─ Configure API
   └─ Initialize modules

3. Execute pipeline
   ├─ Extract
   ├─ Process
   ├─ Generate
   └─ Save output

4. Display results
   ├─ Show summary
   ├─ Print file paths
   └─ Report errors
```

### **Example Session:**

```bash
$ python translate.py "test.pdf" --lang hi

🚀 Running PDF Translation Pipeline

======================================================================
📄 PDF File: test.pdf
🌐 Language: Hindi
======================================================================

=== STEP 1: PDF → JSON Extraction ===
🚀 FIXED PDF Conversion: test.pdf
  📄 Processing page 1/4...
  ✅ Extracted 53 images
✅ Enhanced JSON saved: outputs\test_extracted.json (279.4 KB)

🔄 Processing content types...
✅ Changed 8 mathematical → normal_text
✅ Detected 63 full math content → mathematical

🔢 Smart math content detection...
   🔄 Fixed: 'Directions (31-35)...' → instruction
✅ Fixed 7 incorrect mathematical classifications

=== STEP 2: JSON Translation ===
--- Translating into Hindi (hi) ---

📄 Page 1:
   🔄 TRANSLATING [1]: Sreedhar's CCE SBI CLERK...
   ✅ Translation successful (attempt 1)
   📊 Page 1 summary: 20 translated, 11 skipped

✅ SUCCESSFULLY SAVED TRANSLATED FILE:
   📍 Location: translated_jsons\test_extracted_hi.json

--- Rebuilding PDF for Hindi ---
✅ Generated PDF: outputs\test_hi.pdf

=== PIPELINE SUMMARY ===
📄 Source PDF        : test.pdf
🧾 Extracted JSON    : outputs\test_extracted.json
🌐 Languages         : hi
💾 Translated JSONs  : 1 files
📚 Generated PDFs    : 1 files

✅ Pipeline completed successfully!
```

---

## 🌐 **Gradio Web UI Workflow**

### **User Journey:**

```
1. Start Server
   $ python app_gradio.py
   → Opens at http://localhost:7860

2. Select Module
   ┌─────────────────────────────┐
   │ [ Translation ] [ Solution ] [ MCQ ] │
   └─────────────────────────────┘

3. Upload/Input
   ┌─────────────────────────────┐
   │  Drop PDF here or click     │
   │  [ Browse Files ]           │
   └─────────────────────────────┘

4. Configure
   ┌─────────────────────────────┐
   │  Language: [Hindi ▼]        │
   │  [Translate PDF]            │
   └─────────────────────────────┘

5. Process
   ┌─────────────────────────────┐
   │  Processing... 45%          │
   │  [████████░░░░░░░░░]        │
   └─────────────────────────────┘

6. Download
   ┌─────────────────────────────┐
   │  ✅ Translation complete!   │
   │  📥 [Download PDF]          │
   └─────────────────────────────┘
```

### **Key Features:**

1. **Module Reload:**
   ```python
   # Forces fresh code on every request
   fresh_module = force_reload_translate_module()
   ```

2. **File Verification:**
   ```python
   # Log input file hash
   input_hash = hashlib.md5(file_data).hexdigest()
   print(f"📊 Input MD5: {input_hash}")
   
   # Log output file hash
   output_hash = hashlib.md5(output_data).hexdigest()
   print(f"📊 Output MD5: {output_hash}")
   ```

3. **Progress Updates:**
   ```python
   # Real-time status messages
   yield "Extracting PDF... 25%"
   yield "Translating page 2/4... 50%"
   yield "Generating PDF... 75%"
   yield "✅ Complete! 100%"
   ```

---

## 👨‍💻 **Development Workflow**

### **Setup Development Environment:**

```bash
# 1. Clone repository
git clone https://github.com/nagavallikareethu/ai-pdf-toolkit.git
cd ai-pdf-toolkit

# 2. Create .env file
echo "GENAI_API_KEY=your_key_here" > .env
echo "GENAI_MODEL=models/gemini-2.5-flash" >> .env

# 3. Install dependencies
pip install -r requirements.txt

# 4. Download fonts
python download_fonts.py

# 5. Verify setup
python verify_setup.py

# 6. Run tests
python test_cli_vs_gradio_outputs.py
```

### **Making Changes:**

```
1. Create feature branch
   git checkout -b feature/new-feature

2. Make changes
   - Edit code
   - Test locally
   - Check linting

3. Test thoroughly
   - Run CLI tests
   - Run Gradio tests
   - Compare outputs

4. Commit changes
   git add .
   git commit -m "feat: description"

5. Push to GitHub
   git push origin feature/new-feature

6. Create Pull Request
```

### **Testing Checklist:**

- [ ] CLI translation works
- [ ] Gradio translation works
- [ ] Output hashes match
- [ ] No linter errors
- [ ] Documentation updated
- [ ] .env file not committed
- [ ] Tests pass

---

## 🚀 **Deployment Workflow**

### **Local Deployment:**

```bash
# 1. Ensure environment ready
python verify_setup.py

# 2. Start Gradio server
python app_gradio.py

# 3. Access at http://localhost:7860
```

### **Production Deployment:**

```bash
# 1. Set production environment variables
export GENAI_API_KEY=production_key
export GENAI_MODEL=models/gemini-2.5-flash

# 2. Install production dependencies
pip install -r requirements.txt --no-dev

# 3. Run with Gradio sharing
python app_gradio.py --share

# 4. Access via public Gradio URL
# https://xxxxx.gradio.live
```

### **Server Deployment (Optional):**

```bash
# Using systemd service
sudo nano /etc/systemd/system/pdf-toolkit.service

[Unit]
Description=AI PDF Processing Toolkit
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/pdf-toolkit
Environment="GENAI_API_KEY=your_key"
ExecStart=/usr/bin/python3 app_gradio.py --server_port 7860
Restart=always

[Install]
WantedBy=multi-user.target

# Enable and start service
sudo systemctl enable pdf-toolkit
sudo systemctl start pdf-toolkit
```

---

## 📊 **Monitoring & Maintenance**

### **Health Checks:**

```bash
# 1. Check API connectivity
curl -X POST https://generativelanguage.googleapis.com/...

# 2. Verify disk space
df -h outputs/

# 3. Check process status
ps aux | grep python

# 4. Review logs
tail -f gradio_app.log
```

### **Regular Maintenance:**

```bash
# Weekly
- Clear old output files (>7 days)
- Review error logs
- Update dependencies

# Monthly
- API usage review
- Performance optimization
- Security updates
```

---

## 🔗 **Workflow Integration**

### **CI/CD Pipeline (Future):**

```yaml
# .github/workflows/test.yml
name: Test Pipeline

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: python -m pytest tests/
      - run: python verify_setup.py
```

---

## 📚 **Additional Resources**

- **Setup Guide:** `VERIFICATION_REPORT.md`
- **Architecture:** `SYSTEM_ARCHITECTURE.md`
- **Troubleshooting:** `GRADIO_CLI_SYNC_GUIDE.md`
- **API Fixes:** `FIXES_APPLIED.md`

---

**Document Version:** 1.0  
**Last Updated:** November 17, 2025  
**Maintained By:** Development Team

