import solution
from pathlib import Path
pdf_path = Path('temp') / 'uploaded_20251101_112420.pdf'
if not pdf_path.exists():
    raise SystemExit(f'Missing PDF: {pdf_path}')
print(f'Using PDF: {pdf_path}')
pages = solution.extract_pdf(str(pdf_path), output_json='outputs/extracted_data.json', output_image_folder='outputs/extracted_images')
solved = solution.solve_pages(pages)
translated = solution.translate_items(solved, 'Telugu')
print(f'Solved {len(solved)} questions; translated entries: {len(translated)}')
