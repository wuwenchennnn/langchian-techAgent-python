import PyPDF2
from typing import Optional
from repository.redis_grade_document_store import RedisGradeDocumentStore


class GradeDocumentService:
    def __init__(self):
        self.document_store = RedisGradeDocumentStore()
    
    def upload_and_store(self, memory_id: str, file) -> str:
        """上传并存储文档内容"""
        if not file:
            raise ValueError("文件不能为空")
        
        # 读取文件内容
        file_content = file.file.read()
        
        # 解析PDF文件
        extracted_text = self._extract_text_from_pdf(file_content)
        
        # 存储到Redis
        self.document_store.store_document(memory_id, extracted_text)
        
        return extracted_text
    
    def get_relevant_content(self, memory_id: str, message: str) -> Optional[str]:
        """获取与消息相关的文档内容"""
        # 这里简化处理，直接返回存储的文档内容
        # 实际项目中可以使用向量相似度搜索
        return self.document_store.get_document(memory_id)
    
    def delete(self, memory_id: str):
        """删除文档内容"""
        self.document_store.delete_document(memory_id)
    
    def _extract_text_from_pdf(self, pdf_content: bytes) -> str:
        """从PDF文件中提取文本"""
        text = ""
        try:
            reader = PyPDF2.PdfReader(pdf_content)
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                text += page.extract_text() + "\n"
        except Exception as e:
            raise ValueError(f"PDF解析失败: {str(e)}")
        return text
