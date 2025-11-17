# 🏗️ **System Architecture**

**Project:** AI-Powered PDF Processing Toolkit  
**Version:** 1.0.0  
**Last Updated:** November 17, 2025

---

## 📋 **Table of Contents**

1. [Overview](#overview)
2. [System Components](#system-components)
3. [Architecture Diagram](#architecture-diagram)
4. [Technology Stack](#technology-stack)
5. [Module Details](#module-details)
6. [Data Flow](#data-flow)
7. [API Integration](#api-integration)
8. [Storage Architecture](#storage-architecture)

---

## 🎯 **Overview**

The AI-Powered PDF Processing Toolkit is a comprehensive solution for PDF analysis, translation, solution generation, and MCQ creation. It consists of three main processing pipelines accessible through both CLI and web interface (Gradio).

### **Key Features:**
- ✅ Multi-language PDF translation (Hindi, Odia)
- ✅ Automatic solution generation for mathematical problems
- ✅ MCQ generation from PDFs or topics
- ✅ Dual interface: CLI and Web UI
- ✅ Intelligent content classification
- ✅ Format-preserving PDF overlay

---

## 🏛️ **System Components**

### **1. Frontend Layer**

```
┌─────────────────────────────────────┐
│         User Interface              │
├─────────────────────────────────────┤
│  • Gradio Web UI (app_gradio.py)   │
│  • CLI Interface (*.py main())      │
└─────────────────────────────────────┘
```

**Purpose:** User interaction and file management  
**Technologies:** Gradio 5.35.0, Python CLI  
**Features:**
- File upload/download
- Real-time progress tracking
- Multi-language support
- Responsive design

---

### **2. Processing Layer**

```
┌──────────────────────────────────────────────────────┐
│              Core Processing Modules                 │
├──────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │ Translation │  │  Solution   │  │     MCQ     │ │
│  │   Module    │  │   Module    │  │   Module    │ │
│  │ translate.py│  │ solution.py │  │ generate.py │ │
│  └─────────────┘  └─────────────┘  └─────────────┘ │
└──────────────────────────────────────────────────────┘
```

**Components:**
- **Translation Module** (`translate.py`)
  - PDF extraction
  - Content classification
  - Translation with Google Gemini
  - PDF overlay generation

- **Solution Module** (`solution.py`)
  - Equation solving with SymPy
  - LLM-assisted solution generation
  - Multi-language translation
  - PDF rendering with Playwright

- **MCQ Module** (`generate.py`)
  - Topic-based question generation
  - PDF content analysis
  - Difficulty level management
  - Multiple language support

---

### **3. Utility Layer**

```
┌─────────────────────────────────────────────────┐
│              Utility Components                 │
├─────────────────────────────────────────────────┤
│  • PDF Extraction (pdf_to_json_converter.py)   │
│  • JSON Translation (json_translator.py)        │
│  • PDF Creation (pdf_creation.py)              │
│  • Font Management (download_fonts.py)         │
└─────────────────────────────────────────────────┘
```

---

### **4. Storage Layer**

```
┌─────────────────────────────────────┐
│         File System                 │
├─────────────────────────────────────┤
│  • outputs/ (Generated files)       │
│  • translated_jsons/ (Translations) │
│  • fonts/ (Noto Sans fonts)         │
│  • temp/ (Temporary processing)     │
└─────────────────────────────────────┘
```

---

## 🔄 **Architecture Diagram**

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                          │
│  ┌──────────────────┐              ┌──────────────────┐        │
│  │  Gradio Web UI   │              │   CLI Interface  │        │
│  │  (Port 7860)     │              │  (python *.py)   │        │
│  └────────┬─────────┘              └─────────┬────────┘        │
└───────────┼──────────────────────────────────┼─────────────────┘
            │                                   │
            └───────────────┬───────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────┐
│                    PROCESSING PIPELINE                           │
│                           │                                      │
│  ┌────────────────────────┼────────────────────────────────┐   │
│  │   1. PDF EXTRACTION    │                                │   │
│  │   ┌────────────────────▼────────────────────┐           │   │
│  │   │  PDFToJSONConverter                     │           │   │
│  │   │  - Extract text, images, layout         │           │   │
│  │   │  - Preserve coordinates & structure     │           │   │
│  │   │  - Convert to JSON format               │           │   │
│  │   └────────────────────┬────────────────────┘           │   │
│  └────────────────────────┼────────────────────────────────┘   │
│                           │                                      │
│  ┌────────────────────────┼────────────────────────────────┐   │
│  │   2. CONTENT CLASSIFICATION                             │   │
│  │   ┌────────────────────▼────────────────────┐           │   │
│  │   │  Smart Content Detection                │           │   │
│  │   │  - Identify math content                │           │   │
│  │   │  - Classify questions/instructions      │           │   │
│  │   │  - Separate translatable text           │           │   │
│  │   └────────────────────┬────────────────────┘           │   │
│  └────────────────────────┼────────────────────────────────┘   │
│                           │                                      │
│  ┌────────────────────────┼────────────────────────────────┐   │
│  │   3. AI PROCESSING     │                                │   │
│  │   ┌────────────────────▼────────────────────┐           │   │
│  │   │  Google Gemini API                      │           │   │
│  │   │  - Translation (Hindi/Odia)             │           │   │
│  │   │  - Solution generation                  │           │   │
│  │   │  - MCQ creation                         │           │   │
│  │   │  - Retry logic with exponential backoff │           │   │
│  │   └────────────────────┬────────────────────┘           │   │
│  └────────────────────────┼────────────────────────────────┘   │
│                           │                                      │
│  ┌────────────────────────┼────────────────────────────────┐   │
│  │   4. PDF GENERATION    │                                │   │
│  │   ┌────────────────────▼────────────────────┐           │   │
│  │   │  PDF Overlay Generator                  │           │   │
│  │   │  - Preserve original formatting         │           │   │
│  │   │  - Replace text with translations       │           │   │
│  │   │  - Maintain layout & images             │           │   │
│  │   └────────────────────┬────────────────────┘           │   │
│  └────────────────────────┼────────────────────────────────┘   │
└───────────────────────────┼──────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────┐
│                     DATA STORAGE                                 │
│  ┌────────────────────────▼────────────────────┐                │
│  │  File System                                │                │
│  │  - outputs/          (Final PDFs)           │                │
│  │  - translated_jsons/ (Intermediate JSON)    │                │
│  │  - fonts/           (Noto Sans fonts)       │                │
│  └─────────────────────────────────────────────┘                │
└──────────────────────────────────────────────────────────────────┘
```

---

## 💻 **Technology Stack**

### **Core Technologies**

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Language** | Python | 3.12+ | Main programming language |
| **Web Framework** | Gradio | 5.35.0 | Web UI interface |
| **AI/LLM** | Google Gemini | 2.5-flash | Translation & generation |
| **PDF Processing** | PyMuPDF (fitz) | Latest | PDF extraction |
| **Math Solving** | SymPy | Latest | Equation solving |
| **PDF Rendering** | Playwright | Latest | PDF generation |
| **Fonts** | Noto Sans | Latest | Multi-language support |

### **Key Libraries**

```python
# Core Processing
import fitz               # PDF extraction
import google.generativeai as genai  # LLM
from sympy import *       # Math solving

# PDF Generation
from playwright.async_api import async_playwright

# Web Interface
import gradio as gr

# Data Processing
import json
import re
import os
from pathlib import Path
```

---

## 📦 **Module Details**

### **1. Translation Module** (`translate.py`)

**Size:** 3,346 lines  
**Purpose:** Complete PDF translation pipeline

**Key Classes:**
```python
class PDFToJSONConverter:
    - convert_pdf_to_json_enhanced()
    - extract_text_and_images()
    - detect_layout_elements()

class JSONTranslator:
    - translate_json_file()
    - classify_content()
    - call_gemini_api()

class OverlayPDFGenerator:
    - generate_pdf()
    - overlay_on_original()

class PDFProcessingPipeline:
    - run_complete_pipeline()
    - coordinate_all_steps()
```

**Key Functions:**
- `change_mathematical_to_normal_text()` - Content classification
- `update_content_types_to_mathematical()` - Smart math detection
- `verify_json_structure()` - Data validation
- `run_full_pipeline()` - CLI execution

---

### **2. Solution Module** (`solution.py`)

**Size:** 812 lines  
**Purpose:** Generate solutions for mathematical problems

**Key Functions:**
```python
def extract_pdf(pdf_path, output_json, output_image_folder)
    - Extract questions from PDF

def solve_math_equation(equation_text)
    - Solve using SymPy
    - Use LLM for complex problems

def solve_pages(pages)
    - Process all questions
    - Generate step-by-step solutions

def translate_items(items, target_lang)
    - Translate solutions to target language

async def render_pdf_from_data(data, language, output_pdf)
    - Create final PDF with Playwright
```

**Features:**
- Security: Uses `sympify()` instead of `eval()`
- Retry logic: Exponential backoff for API calls
- Multi-step solving: Combines SymPy + LLM
- Format preservation: HTML-based rendering

---

### **3. MCQ Generation Module** (`generate.py`)

**Size:** 48,206 bytes  
**Purpose:** Generate multiple-choice questions

**Key Components:**
- Topic-based generation
- PDF content analysis
- Difficulty levels (easy, medium, hard)
- Multi-language support
- Answer key generation

---

### **4. Gradio Interface** (`app_gradio.py`)

**Size:** 1,124 lines  
**Purpose:** Web-based user interface

**Architecture:**
```python
# Module Loading
translate_module = load_module('translate')
solution_module = load_module('solution')
generate_module = load_module('generate')

# UI Tabs
with gr.Blocks() as app:
    with gr.Tab("Translation"):
        # Translation UI
    with gr.Tab("Solution Generation"):
        # Solution UI
    with gr.Tab("MCQ Generation"):
        # MCQ UI

# Pipeline Wrappers
def run_translate_pipeline()
def run_solution_pipeline()
def run_generate_pipeline()
```

**Features:**
- Module reload on each request (prevents caching)
- Environment verification
- File hash verification (MD5)
- Real-time progress updates
- Download links for outputs

---

## 🔄 **Data Flow**

### **Translation Pipeline Flow**

```
1. INPUT
   ┌─────────────┐
   │  PDF File   │
   └──────┬──────┘
          │
2. EXTRACTION
   ┌──────▼──────────────────────┐
   │ PDFToJSONConverter          │
   │ - Extract text blocks       │
   │ - Extract images            │
   │ - Detect layout elements    │
   │ - Preserve coordinates      │
   └──────┬──────────────────────┘
          │
          ▼
   ┌──────────────────────────┐
   │ extracted_data.json      │
   └──────┬───────────────────┘
          │
3. CLASSIFICATION
   ┌──────▼──────────────────────┐
   │ Content Type Processing     │
   │ - change_mathematical...()  │
   │ - update_content_types...() │
   │ - verify_json_structure()   │
   └──────┬──────────────────────┘
          │
          ▼
   ┌──────────────────────────┐
   │ classified_data.json     │
   └──────┬───────────────────┘
          │
4. TRANSLATION
   ┌──────▼──────────────────────┐
   │ Google Gemini API           │
   │ - Translate text blocks     │
   │ - Skip math content         │
   │ - Preserve structure        │
   │ - Retry on failure          │
   └──────┬──────────────────────┘
          │
          ▼
   ┌──────────────────────────┐
   │ translated_hi.json       │
   └──────┬───────────────────┘
          │
5. PDF GENERATION
   ┌──────▼──────────────────────┐
   │ OverlayPDFGenerator         │
   │ - Load original PDF         │
   │ - Overlay translations      │
   │ - Preserve formatting       │
   └──────┬──────────────────────┘
          │
6. OUTPUT
   ┌──────▼──────────────┐
   │  translated_hi.pdf  │
   └─────────────────────┘
```

---

### **Solution Pipeline Flow**

```
1. INPUT → 2. EXTRACT → 3. SOLVE → 4. TRANSLATE → 5. RENDER → 6. OUTPUT
   PDF        JSON        SymPy      Gemini        Playwright    PDF
```

### **MCQ Pipeline Flow**

```
1. INPUT → 2. ANALYZE → 3. GENERATE → 4. FORMAT → 5. OUTPUT
   PDF/      Content     Questions     JSON/HTML     PDF
   Topic     Analysis    via Gemini                 
```

---

## 🔌 **API Integration**

### **Google Gemini API**

```python
# Configuration
GENAI_API_KEY = os.getenv('GENAI_API_KEY')
GENAI_MODEL = os.getenv('GENAI_MODEL', 'models/gemini-2.5-flash')

# Initialize
genai.configure(api_key=GENAI_API_KEY)
model = genai.GenerativeModel(GENAI_MODEL)

# Call with retry logic
def call_llm_with_retry(prompt, max_retries=3, timeout=60):
    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                prompt,
                request_options={"timeout": timeout}
            )
            return response.text
        except Exception as e:
            # Exponential backoff for rate limits
            wait_time = 2 ** attempt
            time.sleep(wait_time)
    raise Exception("All retries exhausted")
```

**Features:**
- ✅ Retry logic with exponential backoff
- ✅ Timeout handling (60s default)
- ✅ Rate limit detection (429 errors)
- ✅ Safety filter handling
- ✅ Error logging

**API Usage:**
- Translation: ~92 API calls per 4-page PDF
- Solution: Variable (depends on questions)
- MCQ: ~10-20 API calls per topic

---

## 💾 **Storage Architecture**

### **Directory Structure**

```
E:\MVP\
├── outputs/                    # Main output directory
│   ├── *.pdf                  # Translated PDFs
│   ├── *_extracted.json       # Extracted content
│   └── temp/                  # Temporary Gradio uploads
│
├── translated_jsons/          # Intermediate translations
│   ├── *_extracted_hi.json   # Hindi translations
│   └── *_extracted_or.json   # Odia translations
│
├── fonts/                     # Font files
│   ├── NotoSans-Regular.ttf
│   ├── NotoSans-Bold.ttf
│   └── NotoSansDevanagari-*.ttf
│
├── Core Modules/              # Python modules
│   ├── translate.py
│   ├── solution.py
│   ├── generate.py
│   └── app_gradio.py
│
└── Config/                    # Configuration
    ├── .env                   # API keys
    ├── requirements.txt       # Dependencies
    └── .gitignore            # Git ignore rules
```

### **File Naming Convention**

| Type | Pattern | Example |
|------|---------|---------|
| **Input** | `*.pdf` | `test.pdf` |
| **Extracted** | `{name}_extracted.json` | `test_extracted.json` |
| **Translated** | `{name}_extracted_{lang}.json` | `test_extracted_hi.json` |
| **Output** | `{name}_{lang}.pdf` | `test_hi.pdf` |
| **Solutions** | `solved_{lang}.pdf` | `solved_hi.pdf` |

---

## 🔐 **Security Features**

1. **Input Validation:**
   - PDF file type checking
   - File size limits
   - Path sanitization

2. **Code Safety:**
   - Uses `sympify()` instead of `eval()`
   - Input sanitization for equations
   - Error handling for malicious input

3. **API Security:**
   - Environment variable storage for keys
   - `.env` file excluded from Git
   - No hardcoded credentials

4. **File System:**
   - Sandboxed output directories
   - No arbitrary file access
   - Temporary file cleanup

---

## 📊 **Performance Characteristics**

| Operation | Time | Memory |
|-----------|------|--------|
| **PDF Extraction** | 2-5s per page | ~50MB |
| **Translation** | 30-60s per page | ~100MB |
| **Solution Gen** | 10-30s per question | ~150MB |
| **MCQ Gen** | 20-40s for 10 MCQs | ~100MB |
| **PDF Overlay** | 1-3s per page | ~50MB |

**Bottlenecks:**
- API calls (rate limited to 15 RPM)
- PDF rendering with Playwright
- Large file processing

**Optimization:**
- API retry with backoff
- Batch processing where possible
- Efficient JSON serialization

---

## 🔄 **Synchronization**

### **CLI vs Gradio**

Both interfaces use **identical processing logic** after synchronization fixes:

| Component | CLI | Gradio | Synchronized |
|-----------|-----|--------|--------------|
| Content Classification | ✅ | ✅ | ✅ YES |
| Smart Math Detection | ✅ | ✅ | ✅ YES |
| Translation Logic | ✅ | ✅ | ✅ YES |
| PDF Generation | OverlayPDF | OverlayPDF | ✅ YES |
| Module Reload | N/A | Forced | ✅ YES |

---

## 📚 **References**

- [Google Gemini API Documentation](https://ai.google.dev/docs)
- [Gradio Documentation](https://gradio.app/docs)
- [PyMuPDF Documentation](https://pymupdf.readthedocs.io/)
- [SymPy Documentation](https://docs.sympy.org/)
- [Playwright Documentation](https://playwright.dev/python/)

---

**Document Version:** 1.0  
**Last Updated:** November 17, 2025  
**Maintained By:** Development Team

