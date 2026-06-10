import os
base = r"D:\Python Project\langchain4j-techAgent-python"
path = os.path.join(base, "service", "grade_document_service.py")
with open(path, "r", encoding="utf-8-sig") as f:
    for i, line in enumerate(f, 1):
        print(f"{i:3d}: {line}", end="")
