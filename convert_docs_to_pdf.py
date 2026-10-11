import os
import sys
import subprocess
import html
import re

WORKSPACE_DIR = r"s:\Drive Tasks\moveinsync assignment"
DOCS_DIR = os.path.join(WORKSPACE_DIR, "docs")

# 1. Ensure any old PDFs are permanently deleted
for fname in ["Recommendation_Memo.pdf", "Methodology_and_Tools.pdf"]:
    pdf_path = os.path.join(DOCS_DIR, fname)
    if os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
            print(f"Deleted old PDF: {pdf_path}")
        except Exception as e:
            print(f"Warning: could not delete {pdf_path}: {e}")

# 2. Locate Edge or Chrome executable
edge_paths = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
browser_exe = None
for p in edge_paths:
    if os.path.exists(p):
        browser_exe = p
        break

if not browser_exe:
    print("ERROR: No compatible Chromium browser found.")
    sys.exit(1)

print(f"Using browser engine: {browser_exe}")

def format_inline(text):
    """Formats markdown bold, italics, inline code, links, and math cleanly."""
    # First preserve explicit <br> tags before escaping
    text = re.sub(r'<br\s*/?>', '___BR___', text, flags=re.IGNORECASE)

    # Escape HTML special characters
    text = html.escape(text)

    # Restore <br>
    text = text.replace('___BR___', '<br>')

    # Convert LaTeX display / inline equations cleanly (handling subscripts)
    text = text.replace(r"\Delta \text{WoW} = \text{Rating}_{W_k} - \text{Rating}_{W_{k-1}}",
                        "&Delta; WoW = Rating<sub>W<sub>k</sub></sub> &minus; Rating<sub>W<sub>k&minus;1</sub></sub>")
    text = text.replace(r"\text{Sim}(v_i, v_j) = v_i \cdot v_j",
                        "Sim(v<sub>i</sub>, v<sub>j</sub>) = v<sub>i</sub> &sdot; v<sub>j</sub>")
    text = text.replace(r"v_i, v_j", "v<sub>i</sub>, v<sub>j</sub>")
    text = text.replace(r"\le", "&le;")
    text = text.replace(r"\text{dist}", "dist")
    text = text.replace(r"\text{identical}", "identical")
    text = text.replace(r"\text{opposite}", "opposite")

    # Clean up math delimiters ($...$ or $$...$$) while preserving currency like $0 or $100
    text = re.sub(r'\$\$(.*?)\$\$', r'\1', text)
    text = re.sub(r'(?<!\w)\$(?!\d)(.*?)\$(?!\w)', r'\1', text)

    # Markdown links: [text](url) -> render the text/code directly for clean PDF display
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

    # Inline code: `code`
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # Bold + Italic: ***text***
    text = re.sub(r'\*\*\*([^\*]+)\*\*\*', r'<strong><em>\1</em></strong>', text)

    # Bold: **text**
    text = re.sub(r'\*\*([^\*]+)\*\*', r'<strong>\1</strong>', text)

    # Italic: *text* (avoid matching list markers or bullet symbols)
    text = re.sub(r'(?<!\*)\*([^\*]+)\*(?!\*)', r'<em>\1</em>', text)

    return text

def parse_markdown_to_html(md_text, title):
    lines = md_text.splitlines()
    html_out = []
    
    in_table = False
    table_alignments = []
    table_rows = []
    
    in_ul = False
    in_ol = False
    in_blockquote = False
    blockquote_lines = []
    
    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            html_out.append('</ul>')
            in_ul = False
        if in_ol:
            html_out.append('</ol>')
            in_ol = False

    def close_blockquote():
        nonlocal in_blockquote, blockquote_lines
        if in_blockquote:
            bq_content = '<br>'.join(blockquote_lines)
            html_out.append(f'<blockquote>{bq_content}</blockquote>')
            in_blockquote = False
            blockquote_lines = []

    def close_table():
        nonlocal in_table, table_alignments, table_rows
        if in_table:
            html_out.append('<table>')
            for r_idx, (is_header, cells) in enumerate(table_rows):
                html_out.append('<tr>')
                tag = 'th' if is_header else 'td'
                for c_idx, cell in enumerate(cells):
                    align = table_alignments[c_idx] if c_idx < len(table_alignments) else 'left'
                    cell_html = format_inline(cell)
                    html_out.append(f'<{tag} style="text-align: {align};">{cell_html}</{tag}>')
                html_out.append('</tr>')
            html_out.append('</table>')
            in_table = False
            table_alignments = []
            table_rows = []

    i = 0
    while i < len(lines):
        raw_line = lines[i]
        line = raw_line.strip()

        # Check for table line
        if line.startswith('|') and line.endswith('|') and line.count('|') >= 2:
            close_lists()
            close_blockquote()
            
            cells = [c.strip() for c in line.split('|')[1:-1]]
            
            # Check if next line is alignment delimiter (e.g., |---|:---:|---|)
            if not in_table:
                # This is header row
                in_table = True
                table_rows.append((True, cells))
                # Check next line for alignment
                if i + 1 < len(lines):
                    next_line = lines[i+1].strip()
                    if next_line.startswith('|') and '---' in next_line:
                        align_cells = [c.strip() for c in next_line.split('|')[1:-1]]
                        table_alignments = []
                        for ac in align_cells:
                            if ac.startswith(':') and ac.endswith(':'):
                                table_alignments.append('center')
                            elif ac.endswith(':'):
                                table_alignments.append('right')
                            else:
                                table_alignments.append('left')
                        i += 2
                        continue
            else:
                # Standard data row
                if not ('---' in line and set(line.replace('|', '').replace('-', '').replace(':', '').strip()) == set()):
                    table_rows.append((False, cells))
            i += 1
            continue
        else:
            close_table()

        if not line:
            close_lists()
            close_blockquote()
            i += 1
            continue

        # Display math block $$...$$
        if line.startswith('$$') and line.endswith('$$') and len(line) > 2:
            close_lists()
            close_blockquote()
            math_expr = line[2:-2].strip()
            formatted = format_inline(math_expr)
            html_out.append(f'<div class="math-block">{formatted}</div>')
            i += 1
            continue

        # Blockquote
        if line.startswith('>'):
            close_lists()
            bq_text = format_inline(line[1:].strip())
            if not in_blockquote:
                in_blockquote = True
                blockquote_lines = [bq_text]
            else:
                blockquote_lines.append(bq_text)
            i += 1
            continue
        else:
            close_blockquote()

        # Headings
        if line.startswith('# '):
            close_lists()
            html_out.append(f'<h1>{format_inline(line[2:])}</h1>')
            i += 1
            continue
        elif line.startswith('## '):
            close_lists()
            html_out.append(f'<h2>{format_inline(line[3:])}</h2>')
            i += 1
            continue
        elif line.startswith('### '):
            close_lists()
            html_out.append(f'<h3>{format_inline(line[4:])}</h3>')
            i += 1
            continue
        elif line.startswith('#### '):
            close_lists()
            html_out.append(f'<h4>{format_inline(line[5:])}</h4>')
            i += 1
            continue

        # Horizontal rule
        if line in ['---', '***', '___']:
            close_lists()
            html_out.append('<hr>')
            i += 1
            continue

        # Numbered list
        ol_match = re.match(r'^(\d+)\.\s+(.*)$', line)
        if ol_match:
            if in_ul:
                html_out.append('</ul>')
                in_ul = False
            if not in_ol:
                in_ol = True
                html_out.append('<ol>')
            html_out.append(f'<li>{format_inline(ol_match.group(2))}</li>')
            i += 1
            continue

        # Unordered list
        ul_match = re.match(r'^[\*\-]\s+(.*)$', line)
        if ul_match:
            if in_ol:
                html_out.append('</ol>')
                in_ol = False
            if not in_ul:
                in_ul = True
                html_out.append('<ul>')
            html_out.append(f'<li>{format_inline(ul_match.group(1))}</li>')
            i += 1
            continue

        # Standard paragraph
        close_lists()
        html_out.append(f'<p>{format_inline(line)}</p>')
        i += 1

    close_lists()
    close_blockquote()
    close_table()

    body_html = '\n'.join(html_out)

    styled_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{html.escape(title)}</title>
    <style>
        @page {{
            size: A4;
            margin: 14mm 16mm 14mm 16mm;
        }}
        * {{
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            font-size: 9.8pt;
            line-height: 1.52;
            color: #1e293b;
            background: #ffffff;
            margin: 0;
            padding: 0;
        }}
        h1 {{
            font-size: 17pt;
            font-weight: 700;
            color: #0f172a;
            border-bottom: 2.5px solid #2563eb;
            padding-bottom: 6px;
            margin-top: 0;
            margin-bottom: 10px;
            page-break-after: avoid;
            break-after: avoid;
        }}
        h2 {{
            font-size: 12.5pt;
            font-weight: 700;
            color: #1e293b;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 4px;
            margin-top: 16px;
            margin-bottom: 8px;
            page-break-after: avoid;
            break-after: avoid;
        }}
        h3 {{
            font-size: 10.8pt;
            font-weight: 600;
            color: #1e3a8a;
            margin-top: 13px;
            margin-bottom: 5px;
            page-break-after: avoid;
            break-after: avoid;
        }}
        h4 {{
            font-size: 9.8pt;
            font-weight: 600;
            color: #334155;
            margin-top: 9px;
            margin-bottom: 3px;
            page-break-after: avoid;
            break-after: avoid;
        }}
        p {{
            margin-top: 3px;
            margin-bottom: 5px;
        }}
        blockquote {{
            background: #f8fafc;
            border-left: 4px solid #2563eb;
            padding: 8px 12px;
            margin: 8px 0 10px 0;
            color: #334155;
            font-size: 9.2pt;
            border-radius: 0 4px 4px 0;
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0 12px 0;
            font-size: 8.7pt;
            page-break-inside: avoid;
            break-inside: avoid;
            background: #ffffff;
        }}
        th, td {{
            border: 1px solid #cbd5e1;
            padding: 6px 9px;
            line-height: 1.4;
        }}
        th {{
            background: #f1f5f9;
            color: #0f172a;
            font-weight: 700;
            letter-spacing: 0.01em;
        }}
        tr:nth-child(even) {{
            background: #f8fafc;
        }}
        code {{
            font-family: Consolas, "Courier New", monospace;
            background: #f1f5f9;
            color: #0f172a;
            padding: 1.5px 4.5px;
            border-radius: 3px;
            font-size: 8.5pt;
            border: 1px solid #e2e8f0;
        }}
        .math-block {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 4px;
            padding: 8px 14px;
            margin: 10px 0;
            text-align: center;
            font-family: "Cambria Math", "Times New Roman", serif;
            font-size: 11pt;
            color: #0f172a;
            page-break-inside: avoid;
        }}
        hr {{
            border: none;
            border-top: 1px solid #e2e8f0;
            margin: 14px 0;
        }}
        ul, ol {{
            padding-left: 20px;
            margin-top: 4px;
            margin-bottom: 6px;
        }}
        li {{
            margin-bottom: 4px;
            page-break-inside: avoid;
        }}
        strong {{
            color: #0f172a;
        }}
    </style>
</head>
<body>
{body_html}
</body>
</html>"""
    return styled_html

targets = [
    ("Recommendation_Memo.md", "Recommendation_Memo.pdf", "MoveInSync Play Store Strategy: Engineering & Product Recommendations"),
    ("Methodology_and_Tools.md", "Methodology_and_Tools.pdf", "Methodology & Tools Specification"),
]

for md_file, pdf_file, title in targets:
    md_path = os.path.join(DOCS_DIR, md_file)
    pdf_path = os.path.join(DOCS_DIR, pdf_file)
    html_temp = os.path.join(DOCS_DIR, md_file.replace(".md", ".temp.html"))

    if not os.path.exists(md_path):
        print(f"Skipping {md_file}: file does not exist.")
        continue

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    html_content = parse_markdown_to_html(md_text, title)

    with open(html_temp, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Converting {md_file} -> {pdf_file}...")
    cmd = [
        browser_exe,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        html_temp
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)

    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
        print(f"[OK] Created {pdf_path} ({os.path.getsize(pdf_path):,} bytes)")
        try:
            os.remove(html_temp)
        except Exception:
            pass
    else:
        print(f"[ERROR] Failed to create {pdf_file}: {res.stderr}")

print("All PDF conversions finished.")
