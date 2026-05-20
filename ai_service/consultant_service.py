from langchain_openai import ChatOpenAI
from config.settings import settings
import os


class ConsultantService:
    def __init__(self):
        # 加载系统提示
        system_prompt_path = os.path.join("resources", "system.txt")
        with open(system_prompt_path, "r", encoding="utf-8") as f:
            self.system_prompt = f.read()
        
        # 创建OpenAI聊天模型
        self.llm = ChatOpenAI(
            model_name=settings.openai_model_name,
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            temperature=0.7
        )
        
        # 存储不同会话的记忆
        self.memories = {}
    
    def chat(self, memory_id: str, message: str) -> str:
        """与AI进行聊天"""
        # 获取或创建会话记忆
        if memory_id not in self.memories:
            self.memories[memory_id] = []
        
        # 构建对话历史
        messages = [{
            "role": "system",
            "content": self.system_prompt
        }]
        
        # 添加之前的对话历史
        for msg in self.memories[memory_id]:
            messages.append(msg)
        
        # 添加当前用户消息
        messages.append({
            "role": "user",
            "content": message
        })
        
        # 调用OpenAI API
        response = self.llm.invoke(messages)
        
        # 保存对话历史
        self.memories[memory_id].append({
            "role": "user",
            "content": message
        })
        self.memories[memory_id].append({
            "role": "assistant",
            "content": response.content
        })
        
        return response.content
