import os
base = r"D:\Python Project\langchain4j-techAgent-python"
path = os.path.join(base, "service", "grade_document_service.py")

with open(path, "rb") as f:
    content = f.read()

# Fix the broken "\n" in text += page_text + "..." line
# The broken version is: text += page_text + "\r\n"
# Should be: text += page_text + "\n"
content = content.replace(
    b'text += page_text + "\r\n"',
    b'text += page_text + "\\n"'
)

with open(path, "wb") as f:
    f.write(content)

print("Fixed newline escape in _extract_text_from_pdf")
