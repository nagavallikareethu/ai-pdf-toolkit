"""
Quick Test: Compare CLI vs Gradio Translation Outputs
Run this after translating the same file in both CLI and Gradio
"""
import os
import sys
import hashlib
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def file_hash(filepath):
    """Calculate MD5 hash of file"""
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()

def compare_outputs(file1, file2, label1="CLI", label2="Gradio"):
    """Compare two output files"""
    print("="*70)
    print(f"COMPARING: {label1} vs {label2}")
    print("="*70)
    
    # Check existence
    if not os.path.exists(file1):
        print(f"❌ {label1} file not found: {file1}")
        return False
    
    if not os.path.exists(file2):
        print(f"❌ {label2} file not found: {file2}")
        return False
    
    # File sizes
    size1 = os.path.getsize(file1)
    size2 = os.path.getsize(file2)
    
    print(f"\n📊 File Sizes:")
    print(f"   {label1}:  {size1:,} bytes")
    print(f"   {label2}: {size2:,} bytes")
    
    if size1 == size2:
        print(f"   ✅ Sizes MATCH")
    else:
        diff_pct = abs(size1 - size2) / max(size1, size2) * 100
        print(f"   ⚠️ Size difference: {diff_pct:.2f}%")
    
    # File hashes
    hash1 = file_hash(file1)
    hash2 = file_hash(file2)
    
    print(f"\n🔐 MD5 Hashes:")
    print(f"   {label1}:  {hash1}")
    print(f"   {label2}: {hash2}")
    
    if hash1 == hash2:
        print(f"\n✅ ✅ ✅ HASHES MATCH - OUTPUTS ARE IDENTICAL! ✅ ✅ ✅")
        return True
    else:
        print(f"\n❌ ❌ ❌ HASHES DIFFER - OUTPUTS ARE DIFFERENT! ❌ ❌ ❌")
        return False

def main():
    print("\n" + "="*70)
    print("CLI vs GRADIO OUTPUT COMPARISON")
    print("="*70)
    
    # Prompt for files or use defaults
    print("\nEnter file paths to compare (or press Enter to use defaults):")
    
    cli_file = input("CLI output file [outputs/test_hi.pdf]: ").strip()
    if not cli_file:
        cli_file = "outputs/test_hi.pdf"
    
    gradio_file = input("Gradio output file [outputs/test_hi.pdf]: ").strip()
    if not gradio_file:
        gradio_file = "outputs/test_hi.pdf"
    
    # If same file, look for alternatives
    if cli_file == gradio_file:
        print(f"\n⚠️ Both paths are the same!")
        print(f"Looking for alternative files in outputs/...")
        
        outputs_dir = Path("outputs")
        if outputs_dir.exists():
            pdf_files = sorted(outputs_dir.glob("*_hi.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
            
            if len(pdf_files) >= 2:
                print(f"\nFound {len(pdf_files)} Hindi PDF files (most recent first):")
                for i, f in enumerate(pdf_files[:5], 1):
                    mod_time = f.stat().st_mtime
                    from datetime import datetime
                    mod_str = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M:%S')
                    print(f"  {i}. {f.name} ({mod_str})")
                
                choice = input(f"\nCompare which two files? (e.g., '1 2'): ").strip().split()
                if len(choice) == 2:
                    try:
                        idx1, idx2 = int(choice[0]) - 1, int(choice[1]) - 1
                        cli_file = str(pdf_files[idx1])
                        gradio_file = str(pdf_files[idx2])
                    except:
                        print("Invalid choice, using defaults")
    
    # Compare
    result = compare_outputs(cli_file, gradio_file, "File 1", "File 2")
    
    print("\n" + "="*70)
    if result:
        print("✅ TEST PASSED - Outputs are identical!")
    else:
        print("❌ TEST FAILED - Outputs differ!")
    print("="*70 + "\n")
    
    return result

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️ Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

