import os
import re
import pdfplumber
from pypdf import PdfReader

FOLDER = "/Users/alex/Library/CloudStorage/GoogleDrive-alejandro.gom10@gmail.com/Mi unidad/TecNM/Estudiantes/Mtra. Adriana/allintitle: Moving Bed Biofilm Reactor"

def clean_filename(title):
    """Remove or replace characters not allowed in filenames."""
    # Replace characters not allowed in filenames
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title)
    # Replace multiple spaces/newlines with single space
    title = re.sub(r'\s+', ' ', title)
    # Strip leading/trailing whitespace and dots
    title = title.strip('. ')
    # Limit length to 200 chars
    if len(title) > 200:
        title = title[:200].rsplit(' ', 1)[0]
    return title

def get_title_from_metadata(path):
    try:
        reader = PdfReader(path)
        meta = reader.metadata
        if meta and meta.title and len(meta.title.strip()) > 5:
            return meta.title.strip()
    except Exception:
        pass
    return None

def get_title_from_text(path):
    """Try to extract the title from the first page text."""
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return None
            page = pdf.pages[0]
            words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
            if not words:
                return None

            # Group words by their vertical position (top)
            lines = {}
            for w in words:
                # Round top to group words on same line
                top = round(w['top'])
                if top not in lines:
                    lines[top] = []
                lines[top].append(w)

            if not lines:
                return None

            sorted_tops = sorted(lines.keys())

            # Get the font sizes from words if available
            # pdfplumber words have 'size' attribute if using extract_words
            # Let's try a different approach: use chars to get font sizes
            chars = page.chars
            if chars:
                # Group chars by top position
                char_lines = {}
                for c in chars:
                    top = round(float(c.get('top', 0)))
                    if top not in char_lines:
                        char_lines[top] = []
                    char_lines[top].append(c)

                # Find lines with the largest font size (likely the title)
                line_sizes = {}
                for top, clist in char_lines.items():
                    sizes = [float(c.get('size', 0)) for c in clist if c.get('size')]
                    if sizes:
                        line_sizes[top] = max(sizes)

                if line_sizes:
                    max_size = max(line_sizes.values())
                    # Collect all lines with the largest font (within 2pt)
                    title_lines = []
                    for top in sorted(line_sizes.keys()):
                        if line_sizes[top] >= max_size - 2:
                            line_text = ''.join(c['text'] for c in char_lines[top])
                            line_text = line_text.strip()
                            if line_text:
                                title_lines.append(line_text)
                        elif title_lines:
                            # Stop at first non-title-size line after we started collecting
                            break

                    if title_lines:
                        title = ' '.join(title_lines)
                        if len(title) > 10:
                            return title

            # Fallback: first few lines of text
            text = page.extract_text()
            if text:
                lines_text = [l.strip() for l in text.split('\n') if l.strip()]
                # Skip very short lines at the start (like page numbers, journal names)
                for i, line in enumerate(lines_text[:10]):
                    if len(line) > 20:
                        # Combine with next line if it seems to continue the title
                        title = line
                        if i + 1 < len(lines_text) and len(lines_text[i+1]) > 20 and not lines_text[i+1][0].isupper() or (
                            i + 1 < len(lines_text) and len(title) < 40
                        ):
                            title = title + ' ' + lines_text[i+1]
                        return title

    except Exception as e:
        print(f"  Error extracting text: {e}")
    return None

def main():
    pdf_files = [f for f in os.listdir(FOLDER) if f.lower().endswith('.pdf')]
    pdf_files.sort()

    rename_map = []  # (old_name, new_name)
    skipped = []

    for filename in pdf_files:
        path = os.path.join(FOLDER, filename)
        print(f"\n{'='*60}")
        print(f"File: {filename}")

        title = get_title_from_metadata(path)
        source = "metadata"
        if not title:
            title = get_title_from_text(path)
            source = "text"

        if not title:
            print(f"  -> Could not extract title, skipping")
            skipped.append(filename)
            continue

        clean = clean_filename(title)
        if not clean:
            print(f"  -> Empty title after cleaning, skipping")
            skipped.append(filename)
            continue

        new_filename = clean + '.pdf'
        print(f"  Title ({source}): {title[:100]}")
        print(f"  New name: {new_filename[:100]}")
        rename_map.append((filename, new_filename))

    print(f"\n{'='*60}")
    print(f"\nSUMMARY: {len(rename_map)} files to rename, {len(skipped)} skipped")
    print("\nProposed renames:")
    for old, new in rename_map:
        print(f"  {old}")
        print(f"    -> {new}")
        print()

    confirm = input("\nProceed with renaming? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Aborted.")
        return

    errors = []
    for old, new in rename_map:
        old_path = os.path.join(FOLDER, old)
        new_path = os.path.join(FOLDER, new)

        # Handle duplicates
        if os.path.exists(new_path) and old_path != new_path:
            base, ext = os.path.splitext(new)
            counter = 1
            while os.path.exists(new_path):
                new_path = os.path.join(FOLDER, f"{base} ({counter}){ext}")
                counter += 1

        try:
            os.rename(old_path, new_path)
            print(f"  Renamed: {old} -> {os.path.basename(new_path)}")
        except Exception as e:
            print(f"  ERROR renaming {old}: {e}")
            errors.append((old, str(e)))

    print(f"\nDone. {len(rename_map) - len(errors)} renamed, {len(errors)} errors, {len(skipped)} skipped.")
    if skipped:
        print(f"Skipped: {skipped}")
    if errors:
        print(f"Errors: {errors}")

if __name__ == '__main__':
    main()
