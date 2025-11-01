# AI PDF Workspace

A unified web application for AI-powered PDF processing featuring Translation, Solution Generation, and MCQ Generation modules.

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Download fonts
python download_fonts.py

# Run the application
python app_gradio.py
```

Open http://localhost:7860 in your browser.

## 📋 Features

### 🌐 Translation Module
- Translate PDF content to multiple Indian languages
- Preserve layout and formatting
- Support for: English, Telugu, Hindi, Odia, Tamil

### 🧩 Solution Module
- Extract and solve exam questions
- AI-powered explanations
- Generate solved question papers with answers

### ❓ MCQ Generation Module
- Create new MCQs from PDF content
- Customizable question count
- Multi-language support

## 📚 Documentation

- **QUICKSTART.md** - Get started in 5 minutes
- **README_GRADIO.md** - Comprehensive guide
- **IMPLEMENTATION_SUMMARY.md** - Technical details

## ⚙️ Configuration

Create a `.env` file with:
```
GEMINI_API_KEY=your_api_key_here
```

## 🎯 Requirements

- Python 3.8+
- Gemini API Key (for Solution and MCQ modules)
- Internet connection for AI operations

## 📄 License

This project is provided as-is for educational and development purposes.

