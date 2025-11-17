# 🔄 Gradio-CLI Synchronization Guide

## Problem Statement
Translation output differs between:
- ✅ **Standalone CLI:** `python translate.py input.pdf --lang hi` → Correct output
- ❌ **Gradio App:** Same file + language → Different/outdated output

---

## Root Causes & Solutions

### 1. 🔄 **Module Caching (Most Common)**

#### Problem
Python caches imported modules. Changes to `translate.py` won't reflect until restart.

#### Solution A: Force Module Reload (Current in app_gradio.py)

```python
import importlib
import sys

def reload_backend_modules():
    """Reload all backend modules to pick up code changes"""
    global translate_module, solution_module
    
    # Method 1: importlib.reload (for already imported modules)
    if 'translate' in sys.modules:
        translate_module = importlib.reload(sys.modules['translate'])
        print("✅ Reloaded translate module")
    
    # Method 2: Force reimport (more aggressive)
    if 'translate' in sys.modules:
        del sys.modules['translate']
    import translate as translate_module
    
    return translate_module

# Call before each pipeline run
def run_translate_pipeline(input_pdf_path, target_lang_code):
    # Force reload to get latest code
    reload_backend_modules()
    
    # Now use the fresh module
    pipeline = translate_module.PDFProcessingPipeline(...)
```

#### Solution B: Disable Module Caching (Development)

```python
# At top of app_gradio.py
import sys
sys.dont_write_bytecode = True  # Prevent .pyc files

# For each module
import importlib
importlib.invalidate_caches()
```

#### Solution C: Auto-Reload on File Change (Best for Development)

```python
import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ModuleReloadHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('.py'):
            print(f"🔄 Detected change in {event.src_path}")
            reload_backend_modules()

# Start file watcher
observer = Observer()
observer.schedule(ModuleReloadHandler(), path='.', recursive=False)
observer.start()
```

---

### 2. 📁 **File Path Issues**

#### Problem
CLI uses absolute paths; Gradio uses temporary files with different paths.

#### Diagnosis Script

```python
def diagnose_file_paths(uploaded_file, pdf_path):
    """Compare file paths and contents"""
    import hashlib
    
    print("="*70)
    print("FILE PATH DIAGNOSIS")
    print("="*70)
    
    # Original uploaded file
    print(f"\n1. Gradio uploaded file object:")
    print(f"   Type: {type(uploaded_file)}")
    print(f"   Value: {uploaded_file}")
    
    # Resolved path
    print(f"\n2. Resolved PDF path:")
    print(f"   Path: {pdf_path}")
    print(f"   Exists: {os.path.exists(pdf_path)}")
    print(f"   Absolute: {os.path.abspath(pdf_path)}")
    print(f"   Size: {os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 'N/A'}")
    
    # Calculate hash to verify file integrity
    if os.path.exists(pdf_path):
        with open(pdf_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        print(f"   MD5: {file_hash}")
    
    # Working directory
    print(f"\n3. Working Directory:")
    print(f"   CWD: {os.getcwd()}")
    
    print("="*70)
```

#### Solution: Standardize Path Handling

```python
def save_uploaded_file_to_temp(uploaded_file):
    """Enhanced version with logging and validation"""
    import tempfile
    import shutil
    
    if uploaded_file is None:
        print("❌ No file uploaded")
        return None
    
    # Gradio 4.x typically provides string path directly
    if isinstance(uploaded_file, str) and os.path.isfile(uploaded_file):
        print(f"✅ Using Gradio temp file: {uploaded_file}")
        # Copy to persistent location to avoid cleanup issues
        persistent_path = os.path.join("outputs", "temp", os.path.basename(uploaded_file))
        os.makedirs(os.path.dirname(persistent_path), exist_ok=True)
        shutil.copy2(uploaded_file, persistent_path)
        print(f"✅ Copied to persistent: {persistent_path}")
        return persistent_path
    
    # Handle file object
    if hasattr(uploaded_file, "name"):
        return uploaded_file.name
    
    print("❌ Unknown file format")
    return None
```

---

### 3. 🔑 **Environment Variable Discrepancies**

#### Problem
CLI might load different `.env` than Gradio server.

#### Diagnosis Script

```python
def diagnose_environment():
    """Compare environment variables"""
    from dotenv import load_dotenv
    import os
    
    print("="*70)
    print("ENVIRONMENT DIAGNOSIS")
    print("="*70)
    
    # Check .env file location
    env_path = os.path.join(os.getcwd(), '.env')
    print(f"\n1. .env file:")
    print(f"   Path: {env_path}")
    print(f"   Exists: {os.path.exists(env_path)}")
    
    # Load and display (masked)
    load_dotenv(override=True)  # Force reload
    
    print(f"\n2. Key environment variables:")
    keys = ['GENAI_API_KEY', 'GEMINI_API_KEY', 'GENAI_MODEL', 'PYTHONPATH']
    for key in keys:
        val = os.getenv(key)
        if val:
            masked = f"{val[:10]}...{val[-6:]}" if len(val) > 16 else "***"
            print(f"   {key}: {masked}")
        else:
            print(f"   {key}: ❌ NOT SET")
    
    # Python path
    print(f"\n3. Python paths:")
    import sys
    for path in sys.path[:5]:
        print(f"   - {path}")
    
    print("="*70)
```

#### Solution: Force Consistent Environment

```python
# At the very top of app_gradio.py, BEFORE any imports
import os
from pathlib import Path

# Force load .env from script directory
script_dir = Path(__file__).parent.resolve()
env_file = script_dir / '.env'

if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file, override=True)
    print(f"✅ Loaded .env from: {env_file}")
else:
    print(f"⚠️ No .env file found at: {env_file}")

# Verify critical variables
required_vars = ['GENAI_API_KEY', 'GENAI_MODEL']
for var in required_vars:
    if not os.getenv(var):
        print(f"⚠️ WARNING: {var} not set!")
```

---

### 4. 🎛️ **Parameter Differences**

#### Problem
CLI flags might not map correctly to function parameters.

#### Solution: Parameter Logging Decorator

```python
import functools
import json

def log_parameters(func):
    """Decorator to log all function calls with parameters"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        print("="*70)
        print(f"🔍 FUNCTION CALL: {func.__name__}")
        print("="*70)
        
        # Log positional args
        if args:
            print("\nPositional arguments:")
            for i, arg in enumerate(args):
                arg_str = str(arg)[:100]  # Truncate long strings
                print(f"  [{i}] {type(arg).__name__}: {arg_str}")
        
        # Log keyword args
        if kwargs:
            print("\nKeyword arguments:")
            for key, val in kwargs.items():
                val_str = str(val)[:100]
                print(f"  {key} = {val_str}")
        
        print("="*70)
        
        # Call function
        result = func(*args, **kwargs)
        
        print(f"✅ {func.__name__} completed")
        return result
    
    return wrapper

# Apply to pipeline functions
@log_parameters
def run_translate_pipeline(input_pdf_path: str, target_lang_code: str):
    # ... existing code
```

#### Create Parameter Comparison Script

```python
def compare_cli_vs_gradio_params():
    """Compare parameters between CLI and Gradio execution"""
    
    print("="*70)
    print("PARAMETER COMPARISON")
    print("="*70)
    
    # Simulate CLI execution
    print("\n1. CLI Execution:")
    cli_params = {
        'pdf_path': '/absolute/path/to/file.pdf',
        'target_lang': 'hi',
        'include_images': True,
        'working_dir': os.getcwd(),
    }
    print(json.dumps(cli_params, indent=2))
    
    # Simulate Gradio execution
    print("\n2. Gradio Execution:")
    gradio_params = {
        'pdf_path': '/tmp/gradio/uploaded_file.pdf',
        'target_lang': 'hi',
        'include_images': True,
        'working_dir': 'outputs',  # Different!
    }
    print(json.dumps(gradio_params, indent=2))
    
    # Highlight differences
    print("\n3. Differences:")
    for key in set(cli_params.keys()) | set(gradio_params.keys()):
        cli_val = cli_params.get(key)
        gradio_val = gradio_params.get(key)
        if cli_val != gradio_val:
            print(f"   ❌ {key}:")
            print(f"      CLI:    {cli_val}")
            print(f"      Gradio: {gradio_val}")
    
    print("="*70)
```

---

### 5. 📝 **Comprehensive Logging System**

#### Solution: Add Debug Mode to Gradio

```python
# In app_gradio.py
DEBUG_MODE = os.getenv('DEBUG_MODE', 'false').lower() == 'true'

def debug_log(message, level="INFO"):
    """Conditional debug logging"""
    if DEBUG_MODE:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")

def run_translate_pipeline(input_pdf_path: str, target_lang_code: str):
    """Enhanced with comprehensive logging"""
    
    debug_log(f"Starting translation pipeline", "INFO")
    debug_log(f"Input path: {input_pdf_path}", "DEBUG")
    debug_log(f"Target language: {target_lang_code}", "DEBUG")
    debug_log(f"CWD: {os.getcwd()}", "DEBUG")
    
    # Verify file
    if not os.path.exists(input_pdf_path):
        debug_log(f"File not found: {input_pdf_path}", "ERROR")
        return None, "File not found"
    
    file_size = os.path.getsize(input_pdf_path)
    debug_log(f"File size: {file_size} bytes", "DEBUG")
    
    # Force reload module
    debug_log("Reloading translate module", "DEBUG")
    reload_backend_modules()
    
    # Create pipeline
    debug_log("Creating PDFProcessingPipeline", "DEBUG")
    pipeline = translate_module.PDFProcessingPipeline(working_dir="outputs")
    
    # Run pipeline
    debug_log("Running pipeline", "INFO")
    result = pipeline.run_complete_pipeline(
        pdf_path=input_pdf_path,
        languages=[target_lang_code],
        include_images=True,
        image_handling="metadata"
    )
    
    debug_log(f"Pipeline result keys: {result.keys()}", "DEBUG")
    
    # Check outputs
    if "generated_pdfs" in result and result["generated_pdfs"]:
        output_path = result["generated_pdfs"][0]
        debug_log(f"Output PDF: {output_path}", "INFO")
        
        if os.path.exists(output_path):
            output_size = os.path.getsize(output_path)
            debug_log(f"Output size: {output_size} bytes", "DEBUG")
            return output_path, None
        else:
            debug_log(f"Output file not found: {output_path}", "ERROR")
    
    debug_log("No output generated", "ERROR")
    return None, "Pipeline failed to generate output"
```

---

### 6. 🔬 **Testing Framework**

#### Create Comparison Test Script

```python
# test_cli_vs_gradio.py
import os
import sys
import subprocess
import hashlib
from pathlib import Path

def run_cli_translation(pdf_path, lang):
    """Run standalone CLI translation"""
    print("\n🔧 Running CLI translation...")
    cmd = ['python', 'translate.py', pdf_path, '--lang', lang]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    print("CLI Output:")
    print(result.stdout)
    if result.stderr:
        print("CLI Errors:")
        print(result.stderr)
    
    return result.returncode == 0

def run_gradio_translation(pdf_path, lang):
    """Simulate Gradio translation"""
    print("\n🌐 Running Gradio translation...")
    
    # Import and call directly
    sys.path.insert(0, os.getcwd())
    import app_gradio
    
    # Reload modules
    app_gradio.reload_backend_modules()
    
    # Call pipeline
    output, error = app_gradio.run_translate_pipeline(pdf_path, lang)
    
    if error:
        print(f"Gradio Error: {error}")
        return False
    
    print(f"Gradio Output: {output}")
    return True

def compare_outputs(cli_output, gradio_output):
    """Compare output files"""
    print("\n📊 Comparing outputs...")
    
    if not os.path.exists(cli_output):
        print(f"❌ CLI output not found: {cli_output}")
        return False
    
    if not os.path.exists(gradio_output):
        print(f"❌ Gradio output not found: {gradio_output}")
        return False
    
    # Compare file sizes
    cli_size = os.path.getsize(cli_output)
    gradio_size = os.path.getsize(gradio_output)
    
    print(f"CLI output size: {cli_size} bytes")
    print(f"Gradio output size: {gradio_size} bytes")
    
    if abs(cli_size - gradio_size) / max(cli_size, gradio_size) > 0.1:
        print("⚠️ Output sizes differ by >10%")
    
    # Compare hashes
    def file_hash(path):
        with open(path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    
    cli_hash = file_hash(cli_output)
    gradio_hash = file_hash(gradio_output)
    
    print(f"CLI MD5: {cli_hash}")
    print(f"Gradio MD5: {gradio_hash}")
    
    if cli_hash == gradio_hash:
        print("✅ Outputs are IDENTICAL")
        return True
    else:
        print("❌ Outputs DIFFER")
        return False

if __name__ == "__main__":
    test_pdf = "test_input.pdf"
    test_lang = "hi"
    
    print("="*70)
    print("CLI vs GRADIO COMPARISON TEST")
    print("="*70)
    
    # Run both
    cli_success = run_cli_translation(test_pdf, test_lang)
    gradio_success = run_gradio_translation(test_pdf, test_lang)
    
    if cli_success and gradio_success:
        # Find and compare outputs
        cli_out = f"outputs/test_input_{test_lang}.pdf"
        gradio_out = f"outputs/test_input_{test_lang}.pdf"
        
        compare_outputs(cli_out, gradio_out)
```

---

### 7. 🛠️ **Recommended Fixes for app_gradio.py**

#### Add These Improvements:

```python
# At top of app_gradio.py, add:
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.DEBUG if os.getenv('DEBUG_MODE') == 'true' else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('gradio_debug.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Modify run_translate_pipeline:
def run_translate_pipeline(input_pdf_path: str, target_lang_code: str):
    logger.info(f"="*70)
    logger.info(f"TRANSLATION REQUEST")
    logger.info(f"="*70)
    logger.info(f"PDF: {input_pdf_path}")
    logger.info(f"Language: {target_lang_code}")
    logger.info(f"CWD: {os.getcwd()}")
    logger.info(f"Timestamp: {datetime.now()}")
    
    # Verify file exists and log details
    if not os.path.exists(input_pdf_path):
        logger.error(f"File not found: {input_pdf_path}")
        return None, f"File not found: {input_pdf_path}"
    
    file_stat = os.stat(input_pdf_path)
    logger.info(f"File size: {file_stat.st_size} bytes")
    logger.info(f"File modified: {datetime.fromtimestamp(file_stat.st_mtime)}")
    
    # CRITICAL: Force module reload
    logger.info("Forcing module reload...")
    try:
        if 'translate' in sys.modules:
            del sys.modules['translate']
        global translate_module
        import translate as translate_module
        logger.info("✅ Module reloaded successfully")
    except Exception as e:
        logger.error(f"❌ Module reload failed: {e}")
        # Continue with cached version
    
    # Rest of your pipeline code...
```

---

## 🎯 **Action Plan**

### Immediate Steps:

1. **Add Logging**
   ```bash
   # Run with debug mode
   DEBUG_MODE=true python app_gradio.py
   ```

2. **Force Module Reload**
   ```python
   # Before EVERY pipeline call in app_gradio.py
   if 'translate' in sys.modules:
       del sys.modules['translate']
   import translate as translate_module
   ```

3. **Standardize Paths**
   ```python
   # Always use absolute paths
   input_pdf_path = os.path.abspath(input_pdf_path)
   ```

4. **Verify Environment**
   ```python
   # Add at Gradio startup
   diagnose_environment()
   ```

### Testing Procedure:

```bash
# 1. Run CLI
python translate.py test.pdf --lang hi
# Note output path and hash

# 2. Run Gradio
DEBUG_MODE=true python app_gradio.py
# Upload same file, same language
# Compare output hash

# 3. Check logs
tail -f gradio_debug.log
```

---

## 📋 **Checklist**

- [ ] Module reload implemented before each pipeline call
- [ ] Environment variables logged and verified identical
- [ ] File paths converted to absolute paths
- [ ] Debug logging enabled in development
- [ ] Parameter logging decorator added
- [ ] CLI vs Gradio comparison test created
- [ ] .env file location forced to script directory
- [ ] Temporary file handling standardized
- [ ] Output file hashes compared
- [ ] Working directory consistency verified

---

## 🔗 **Quick Debug Commands**

```bash
# Check module import paths
python -c "import sys; import translate; print(translate.__file__)"

# Compare environments
python translate.py --debug
DEBUG_MODE=true python app_gradio.py

# Force fresh start
rm -rf __pycache__ **/__pycache__ *.pyc
python app_gradio.py
```

---

## 📞 **Still Having Issues?**

If outputs still differ after implementing above:

1. **Capture both outputs and diff them:**
   ```bash
   diff -u cli_output.pdf gradio_output.pdf
   ```

2. **Check file timestamps:**
   - Ensure Gradio isn't serving cached old files

3. **Verify API calls:**
   - Log all API requests from both paths
   - Compare request bodies

4. **Check working directory:**
   - `os.getcwd()` should be same in both cases

