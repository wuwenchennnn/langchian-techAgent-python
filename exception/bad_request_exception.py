class BadRequestException(Exception):
    """请求参数错误异常"""
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)
