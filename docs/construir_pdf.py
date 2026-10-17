"""Convierte docs/caso-spin-fde.md en HTML estilizado y PDF (Chrome headless).
Uso: uv run --with markdown python docs/construir_pdf.py
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

RAIZ = Path(__file__).resolve().parent
md = (RAIZ / "caso-spin-fde.md").read_text(encoding="utf-8")
cuerpo = markdown.markdown(md, extensions=["tables", "fenced_code", "toc", "attr_list", "md_in_html"],
                           extension_configs={"toc": {"toc_depth": "2-3"}})
cuerpo = re.sub(r"<p>\[\[SALTO\]\]</p>", '<div class="salto"></div>', cuerpo)
cuerpo = re.sub(r"<li>\s*<a href=\"#contenido\">Contenido</a>\s*</li>", "", cuerpo)

css = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
html { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 10.6pt; line-height: 1.45; color: #111827; }
body { max-width: 100%; margin: 0; }
h1 { font-size: 22pt; margin: 0 0 6pt; color: #111827; }
h2 { font-size: 15pt; margin: 20pt 0 6pt; color: #1e1b4b; border-bottom: 1.5px solid #c7d2fe; padding-bottom: 3pt; page-break-after: avoid; }
h3 { font-size: 12pt; margin: 14pt 0 4pt; color: #312e81; page-break-after: avoid; }
h4 { font-size: 10.8pt; margin: 10pt 0 3pt; }
p { margin: 0 0 7pt; }
ul, ol { margin: 0 0 8pt; padding-left: 18pt; }
li { margin-bottom: 2pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 9.3pt; page-break-inside: auto; }
th, td { border: 1px solid #d1d5db; padding: 4pt 6pt; vertical-align: top; text-align: left; }
th { background: #eef2ff; color: #1e1b4b; }
tr { page-break-inside: avoid; }
code { font-family: 'DejaVu Sans Mono', Menlo, monospace; font-size: 8.8pt; background: #f3f4f6; padding: 0 3pt; border-radius: 3pt; }
pre { background: #f3f4f6; border: 1px solid #e5e7eb; padding: 7pt 9pt; border-radius: 4pt; font-size: 8.6pt; overflow-x: hidden; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
blockquote { border-left: 3px solid #a5b4fc; margin: 8pt 0; padding: 4pt 10pt; background: #f8fafc; color: #1f2937; }
img { max-width: 100%; }
.salto { page-break-after: always; }
.portada { text-align: left; padding-top: 70mm; }
.portada .sup { color: #6b7280; font-size: 11pt; letter-spacing: 1px; text-transform: uppercase; }
.portada h1 { font-size: 28pt; margin: 10pt 0 6pt; }
.portada .sub { font-size: 15pt; color: #312e81; margin-bottom: 30pt; }
.portada .meta { color: #374151; font-size: 11pt; line-height: 1.7; }
.caja { border: 1px solid #c7d2fe; background: #eef2ff; border-radius: 5pt; padding: 8pt 12pt; margin: 8pt 0 12pt; }
.nota { font-size: 9.3pt; color: #4b5563; }
.toc { font-size: 9.8pt; column-count: 2; column-gap: 28pt; }
.toc ul { list-style: none; padding-left: 0; }
.toc ul ul { padding-left: 12pt; }
.toc a { color: #1f2937; text-decoration: none; }
figure { margin: 8pt 0 12pt; text-align: center; }
figcaption { font-size: 9pt; color: #6b7280; margin-top: 3pt; }
.evidencia { border: 1px solid #d1d5db; }
"""
html = f"<!doctype html><html lang='es'><head><meta charset='utf-8'><title>Caso de negocio Spin — Conciliación automática</title><style>{css}</style></head><body>{cuerpo}</body></html>"
salida_html = RAIZ / "caso-spin-fde.html"
salida_html.write_text(html, encoding="utf-8")

chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
if not chrome:
    print("sin Chrome: solo HTML", file=sys.stderr)
    sys.exit(0)
pdf = RAIZ / "caso-spin-fde.pdf"
subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                f"--print-to-pdf={pdf}", f"file://{salida_html}"], check=True, capture_output=True)
print(f"PDF: {pdf} ({pdf.stat().st_size // 1024} KB)")
