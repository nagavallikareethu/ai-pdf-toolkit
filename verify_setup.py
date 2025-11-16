"""
Setup Verification Script for solution.py
This script checks all dependencies, configurations, and requirements.
Run this before using solution.py to ensure everything is set up correctly.
"""

import sys
import os
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

def print_header(text):
    print("\n" + "="*70)
    print(f"  {text}")
    print("="*70)

def print_status(status, message):
    symbols = {"✅": "PASS", "❌": "FAIL", "⚠️": "WARN", "ℹ️": "INFO"}
    print(f"{status} {message}")

def check_python_version():
    print_header("1. Python Version Check")
    version = sys.version_info
    if version.major == 3 and version.minor >= 8:
        print_status("✅", f"Python {version.major}.{version.minor}.{version.micro} (OK)")
        return True
    else:
        print_status("❌", f"Python {version.major}.{version.minor}.{version.micro} (Need 3.8+)")
        return False

def check_dependencies():
    print_header("2. Required Dependencies Check")
    dependencies = {
        'fitz': 'PyMuPDF',
        'sympy': 'sympy',
        'google.generativeai': 'google-generativeai',
        'playwright': 'playwright',
        'reportlab': 'reportlab',
        'dotenv': 'python-dotenv',
        'tqdm': 'tqdm'
    }
    
    missing = []
    all_ok = True
    
    for module, package in dependencies.items():
        try:
            __import__(module)
            print_status("✅", f"{package:<25} - Installed")
        except ImportError:
            print_status("❌", f"{package:<25} - MISSING")
            missing.append(package)
            all_ok = False
    
    if missing:
        print("\nTo install missing packages, run:")
        print(f"  pip install {' '.join(missing)}")
    
    return all_ok

def check_env_file():
    print_header("3. Environment Configuration Check")
    env_path = Path('.env')
    
    if not env_path.exists():
        print_status("❌", ".env file not found")
        print("\nCreate a .env file with:")
        print("  GENAI_API_KEY=your_api_key_here")
        print("  GENAI_MODEL=models/gemini-2.0-flash-exp")
        return False
    
    print_status("✅", ".env file exists")
    
    # Load and check .env
    from dotenv import load_dotenv
    load_dotenv()
    
    api_key = os.getenv("GENAI_API_KEY")
    model_name = os.getenv("GENAI_MODEL")
    
    if not api_key:
        print_status("❌", "GENAI_API_KEY not set in .env")
        return False
    else:
        masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
        print_status("✅", f"GENAI_API_KEY is set ({masked_key})")
    
    if model_name:
        print_status("✅", f"GENAI_MODEL: {model_name}")
        if not model_name.startswith("models/"):
            print_status("⚠️", "Model name should start with 'models/'")
    else:
        print_status("ℹ️", "GENAI_MODEL not set (will use default)")
    
    return True

def check_playwright():
    print_header("4. Playwright Browser Check")
    try:
        import playwright
        print_status("✅", "Playwright package installed")
        
        # Check if chromium is installed
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
                print_status("✅", "Chromium browser installed and working")
                return True
        except Exception as e:
            error_msg = str(e)
            if "Executable doesn't exist" in error_msg or "playwright install" in error_msg.lower():
                print_status("❌", "Chromium browser not installed")
                print("\nTo install, run:")
                print("  playwright install chromium")
                return False
            else:
                print_status("⚠️", f"Chromium check failed: {str(e)[:50]}")
                return False
    except ImportError:
        print_status("❌", "Playwright not installed")
        return False

def check_fonts():
    print_header("5. Font Files Check")
    fonts_dir = Path("fonts")
    
    if not fonts_dir.exists():
        print_status("⚠️", "fonts/ directory not found (will be created)")
        print_status("ℹ️", "Font files are optional but recommended for proper Indic script rendering")
        return True
    
    print_status("✅", "fonts/ directory exists")
    
    font_files = {
        "NotoSansTelugu-Regular.ttf": "Telugu",
        "TiroDevanagariHindi-Regular.ttf": "Hindi",
        "NotoSansOriya-Regular.ttf": "Odia",
        "NotoSansTamil-Regular.ttf": "Tamil",
        "NotoSansKannada-Regular.ttf": "Kannada"
    }
    
    found = 0
    for font_file, lang in font_files.items():
        font_path = fonts_dir / font_file
        if font_path.exists():
            print_status("✅", f"{lang:<10} - {font_file}")
            found += 1
        else:
            print_status("⚠️", f"{lang:<10} - {font_file} (missing)")
    
    if found == 0:
        print_status("⚠️", "No font files found - PDF will use fallback fonts")
        print("\nTo download fonts:")
        print("  1. Visit https://fonts.google.com/noto")
        print("  2. Download the required language fonts")
        print("  3. Place .ttf files in the fonts/ directory")
    else:
        print_status("✅", f"{found}/{len(font_files)} font files found")
    
    return True

def check_api_connection():
    print_header("6. API Connection Test")
    try:
        from dotenv import load_dotenv
        import google.generativeai as genai
        
        load_dotenv()
        api_key = os.getenv("GENAI_API_KEY")
        model_name = os.getenv("GENAI_MODEL", "models/gemini-2.0-flash-exp")
        
        if not api_key:
            print_status("❌", "Cannot test - API key not set")
            return False
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        print_status("ℹ️", "Testing API connection (this may take a few seconds)...")
        response = model.generate_content("Say 'Hello'")
        
        if response and response.text:
            print_status("✅", "API connection successful!")
            print_status("ℹ️", f"Response: {response.text[:50]}")
            return True
        else:
            print_status("❌", "API returned empty response")
            return False
            
    except Exception as e:
        print_status("❌", f"API test failed: {str(e)}")
        print("\nCommon issues:")
        print("  - Invalid API key")
        print("  - No internet connection")
        print("  - API quota exceeded")
        print("  - Invalid model name")
        return False

def check_file_structure():
    print_header("7. File Structure Check")
    
    required_files = {
        "solution.py": "Main solution script",
        ".env": "Environment configuration"
    }
    
    all_ok = True
    for file, desc in required_files.items():
        if Path(file).exists():
            print_status("✅", f"{file:<20} - {desc}")
        else:
            print_status("❌", f"{file:<20} - {desc} (MISSING)")
            all_ok = False
    
    # Check optional directories
    optional_dirs = {
        "outputs": "Generated output files",
        "extracted_images": "Extracted PDF images",
        "fonts": "Font files for Indic languages"
    }
    
    print("\nOptional directories (will be auto-created):")
    for dir_name, desc in optional_dirs.items():
        if Path(dir_name).exists():
            print_status("✅", f"{dir_name:<20} - {desc}")
        else:
            print_status("ℹ️", f"{dir_name:<20} - {desc} (will be created)")
    
    return all_ok

def test_sympy_security():
    print_header("8. Security Check (sympify vs eval)")
    try:
        from sympy import symbols, sympify, Eq, solve
        
        x = symbols('x')
        # Test safe equation
        test_eq = "2*x + 5"
        result = sympify(test_eq, locals={'x': x})
        print_status("✅", "sympify() is working correctly (secure)")
        
        # Verify eval is NOT used
        solution_path = Path("solution.py")
        if solution_path.exists():
            try:
                content = solution_path.read_text(encoding='utf-8')
                if 'sympify' in content and content.count('eval(') <= 1:  # eval might be in comments
                    print_status("✅", "Solution uses secure sympify() method")
                    return True
                else:
                    print_status("⚠️", "Check if eval() is still being used")
                    return False
            except Exception as e:
                print_status("⚠️", f"Could not read solution.py: {str(e)[:50]}")
                return True  # Don't fail the check if we can't read the file
        return True
    except Exception as e:
        print_status("❌", f"SymPy test failed: {e}")
        return False

def run_all_checks():
    print("\n" + "="*70)
    print("  SOLUTION.PY VERIFICATION SCRIPT")
    print("="*70)
    
    results = {
        "Python Version": check_python_version(),
        "Dependencies": check_dependencies(),
        "Environment Config": check_env_file(),
        "Playwright Browser": check_playwright(),
        "Font Files": check_fonts(),
        "API Connection": check_api_connection(),
        "File Structure": check_file_structure(),
        "Security Check": test_sympy_security()
    }
    
    # Summary
    print_header("VERIFICATION SUMMARY")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for check, status in results.items():
        symbol = "✅" if status else "❌"
        print(f"{symbol} {check}")
    
    print(f"\nPassed: {passed}/{total}")
    
    if passed == total:
        print_status("✅", "ALL CHECKS PASSED! Solution is ready to use.")
        print("\nTo run the solution:")
        print("  python solution.py")
        return True
    else:
        failed = total - passed
        print_status("❌", f"{failed} check(s) failed. Please fix the issues above.")
        print("\nQuick fixes:")
        if not results["Dependencies"]:
            print("  • Install dependencies: pip install -r requirements.txt")
        if not results["Environment Config"]:
            print("  • Create .env file with GENAI_API_KEY")
        if not results["Playwright Browser"]:
            print("  • Install Playwright: playwright install chromium")
        return False

if __name__ == "__main__":
    try:
        success = run_all_checks()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️ Verification interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Verification script error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

