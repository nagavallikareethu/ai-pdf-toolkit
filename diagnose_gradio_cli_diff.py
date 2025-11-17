"""
Diagnostic Script for CLI vs Gradio Translation Differences
Run this to identify why outputs don't match
"""
import os
import sys
import hashlib
import json
from datetime import datetime
from pathlib import Path

# Fix encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def print_section(title):
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)

def file_hash(filepath):
    """Calculate MD5 hash of file"""
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()

def diagnose_environment():
    """Check environment variables"""
    print_section("ENVIRONMENT VARIABLES")
    
    from dotenv import load_dotenv
    
    # Check .env file
    env_path = Path('.env')
    print(f"\n.env file: {env_path.absolute()}")
    print(f"Exists: {env_path.exists()}")
    
    if env_path.exists():
        print(f"Size: {env_path.stat().st_size} bytes")
        print(f"Modified: {datetime.fromtimestamp(env_path.stat().st_mtime)}")
    
    # Load environment
    load_dotenv(override=True)
    
    # Check critical variables
    print("\nCritical Variables:")
    vars_to_check = [
        'GENAI_API_KEY',
        'GEMINI_API_KEY', 
        'GENAI_MODEL',
        'GOOGLE_APPLICATION_CREDENTIALS',
        'PYTHONPATH'
    ]
    
    for var in vars_to_check:
        val = os.getenv(var)
        if val:
            # Mask sensitive data
            if 'KEY' in var:
                masked = f"{val[:10]}...{val[-6:]}" if len(val) > 16 else "***"
            else:
                masked = val
            print(f"  ✅ {var}: {masked}")
        else:
            print(f"  ❌ {var}: NOT SET")

def diagnose_modules():
    """Check module import paths"""
    print_section("MODULE IMPORT PATHS")
    
    modules_to_check = ['translate', 'solution', 'generate']
    
    for module_name in modules_to_check:
        try:
            # Try to import
            if module_name in sys.modules:
                del sys.modules[module_name]  # Force fresh import
            
            module = __import__(module_name)
            print(f"\n✅ {module_name}.py:")
            print(f"   Path: {module.__file__}")
            print(f"   Size: {os.path.getsize(module.__file__)} bytes")
            print(f"   Modified: {datetime.fromtimestamp(os.path.getmtime(module.__file__))}")
            
            # Check for __pycache__
            module_dir = Path(module.__file__).parent
            pycache = module_dir / '__pycache__'
            if pycache.exists():
                pyc_files = list(pycache.glob('*.pyc'))
                if pyc_files:
                    print(f"   ⚠️ __pycache__ exists with {len(pyc_files)} .pyc files")
                    latest_pyc = max(pyc_files, key=lambda p: p.stat().st_mtime)
                    print(f"   Latest .pyc: {datetime.fromtimestamp(latest_pyc.stat().st_mtime)}")
        
        except ImportError as e:
            print(f"\n❌ {module_name}.py: NOT FOUND")
            print(f"   Error: {e}")

def diagnose_file_handling():
    """Check file path handling"""
    print_section("FILE PATH HANDLING")
    
    print(f"\nCurrent Working Directory:")
    print(f"  {os.getcwd()}")
    
    print(f"\nScript Directory:")
    print(f"  {Path(__file__).parent.absolute()}")
    
    print(f"\nTemp Directory:")
    print(f"  {Path.home() / 'tmp' if os.name == 'posix' else Path(os.environ.get('TEMP', 'C:/Temp'))}")
    
    print(f"\nOutputs Directory:")
    outputs_dir = Path('outputs')
    print(f"  Path: {outputs_dir.absolute()}")
    print(f"  Exists: {outputs_dir.exists()}")
    if outputs_dir.exists():
        files = list(outputs_dir.glob('*'))
        print(f"  Files: {len(files)}")
        
        # Show recent files
        if files:
            recent = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:5]
            print("\n  Recent files:")
            for f in recent:
                mod_time = datetime.fromtimestamp(f.stat().st_mtime)
                print(f"    - {f.name} ({mod_time})")

def diagnose_translation_outputs():
    """Check translation output files"""
    print_section("TRANSLATION OUTPUT FILES")
    
    outputs_dir = Path('outputs')
    if not outputs_dir.exists():
        print("❌ outputs/ directory not found")
        return
    
    # Find translation outputs
    patterns = ['*_hi.pdf', '*_or.pdf', '*_te.pdf', '*_extracted.json', 'translated_*.json']
    
    all_files = []
    for pattern in patterns:
        all_files.extend(outputs_dir.glob(pattern))
    
    if not all_files:
        print("⚠️ No translation output files found")
        return
    
    # Group by base name
    from collections import defaultdict
    by_base = defaultdict(list)
    
    for f in all_files:
        base = f.stem.rsplit('_', 1)[0]
        by_base[base].append(f)
    
    print(f"\nFound {len(all_files)} translation files")
    print(f"Grouped into {len(by_base)} base files:\n")
    
    for base, files in sorted(by_base.items()):
        print(f"📄 {base}:")
        for f in sorted(files):
            size = f.stat().st_size
            mod_time = datetime.fromtimestamp(f.stat().st_mtime)
            md5 = file_hash(str(f))
            print(f"   - {f.name}")
            print(f"     Size: {size:,} bytes")
            print(f"     Modified: {mod_time}")
            print(f"     MD5: {md5}")

def diagnose_python_path():
    """Check Python path and imports"""
    print_section("PYTHON PATH")
    
    print("\nsys.path (first 10 entries):")
    for i, path in enumerate(sys.path[:10], 1):
        print(f"  {i}. {path}")
    
    print(f"\nPython executable:")
    print(f"  {sys.executable}")
    
    print(f"\nPython version:")
    print(f"  {sys.version}")

def check_gradio_module():
    """Check if Gradio is properly configured"""
    print_section("GRADIO CONFIGURATION")
    
    try:
        import gradio as gr
        print(f"✅ Gradio installed")
        print(f"   Version: {gr.__version__}")
        print(f"   Path: {gr.__file__}")
    except ImportError:
        print("❌ Gradio not installed")
        return
    
    # Check for app_gradio.py
    app_file = Path('app_gradio.py')
    if app_file.exists():
        print(f"\n✅ app_gradio.py found")
        print(f"   Size: {app_file.stat().st_size:,} bytes")
        print(f"   Modified: {datetime.fromtimestamp(app_file.stat().st_mtime)}")
    else:
        print(f"\n❌ app_gradio.py not found")

def run_quick_test():
    """Run a quick module import test"""
    print_section("QUICK IMPORT TEST")
    
    print("\nAttempting to import modules...")
    
    # Clear any cached imports
    modules_to_clear = ['translate', 'solution', 'generate']
    for mod in modules_to_clear:
        if mod in sys.modules:
            del sys.modules[mod]
            print(f"  Cleared cached {mod}")
    
    # Try importing
    results = {}
    
    for mod_name in modules_to_clear:
        try:
            mod = __import__(mod_name)
            results[mod_name] = {
                'status': 'SUCCESS',
                'path': getattr(mod, '__file__', 'Unknown'),
                'error': None
            }
        except Exception as e:
            results[mod_name] = {
                'status': 'FAILED',
                'path': None,
                'error': str(e)
            }
    
    print("\nImport Results:")
    for mod_name, result in results.items():
        if result['status'] == 'SUCCESS':
            print(f"  ✅ {mod_name}: {result['path']}")
        else:
            print(f"  ❌ {mod_name}: {result['error']}")

def generate_report():
    """Generate summary report"""
    print_section("DIAGNOSTIC SUMMARY")
    
    issues = []
    
    # Check .env
    if not Path('.env').exists():
        issues.append("❌ .env file not found")
    
    # Check API key
    if not os.getenv('GENAI_API_KEY') and not os.getenv('GEMINI_API_KEY'):
        issues.append("❌ No API key configured")
    
    # Check modules
    for mod in ['translate', 'solution']:
        if mod not in sys.modules:
            try:
                __import__(mod)
            except:
                issues.append(f"❌ Cannot import {mod}.py")
    
    # Check __pycache__
    if Path('__pycache__').exists():
        pyc_files = list(Path('__pycache__').glob('*.pyc'))
        if pyc_files:
            issues.append(f"⚠️ {len(pyc_files)} cached .pyc files found (may cause stale imports)")
    
    # Check outputs
    if Path('outputs').exists():
        files = list(Path('outputs').glob('*'))
        if len(files) > 100:
            issues.append(f"⚠️ {len(files)} files in outputs/ (may cause confusion)")
    
    if issues:
        print("\n🔍 Issues Found:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("\n✅ No obvious issues detected")
    
    print("\n" + "="*70)
    print("RECOMMENDATIONS:")
    print("="*70)
    
    print("""
1. Clear Python cache:
   rm -rf __pycache__ **/__pycache__ *.pyc
   (or on Windows: del /s *.pyc)

2. Force module reload in app_gradio.py:
   if 'translate' in sys.modules:
       del sys.modules['translate']
   import translate as translate_module

3. Enable debug mode:
   DEBUG_MODE=true python app_gradio.py

4. Compare outputs:
   # Run CLI
   python translate.py test.pdf --lang hi
   
   # Run Gradio (upload same file)
   python app_gradio.py
   
   # Compare hashes
   md5sum outputs/*_hi.pdf

5. Check logs:
   tail -f gradio_debug.log
    """)

def main():
    print("\n" + "="*70)
    print("  CLI vs GRADIO DIAGNOSTIC TOOL")
    print("="*70)
    print(f"\nTimestamp: {datetime.now()}")
    print(f"Working Directory: {os.getcwd()}")
    
    # Run all diagnostics
    diagnose_environment()
    diagnose_python_path()
    diagnose_modules()
    diagnose_file_handling()
    diagnose_translation_outputs()
    check_gradio_module()
    run_quick_test()
    generate_report()
    
    print("\n" + "="*70)
    print("✅ DIAGNOSTIC COMPLETE")
    print("="*70)
    print("\nSee GRADIO_CLI_SYNC_GUIDE.md for detailed solutions")
    print("="*70 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Diagnostic interrupted by user")
    except Exception as e:
        print(f"\n❌ Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()

