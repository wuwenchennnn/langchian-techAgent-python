import os
base = r"D:\Python Project\langchain4j-techAgent-python"
path = os.path.join(base, "service", "grade_document_service.py")

with open(path, "r", encoding="utf-8-sig") as f:
    content = f.read()

# Add import io and fix PdfReader call
content = content.replace(
    "import PyPDF2",
    "import io\nimport PyPDF2"
)
content = content.replace(
    "reader = PyPDF2.PdfReader(pdf_content)",
    "reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))"
)

with open(path, "w", encoding="utf-8-sig") as f:
    f.write(content)

print("Fixed: PdfReader now receives BytesIO instead of raw bytes")
