"""
统一日志配置模块
所有模块应从此处导入 logger
"""
from loguru import logger

# 只配置一次
logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    format="<green>{time:HH:mm:ss:SSS}</green> | <cyan>{extra[name]:<8}</cyan> | <level>{level:<8}</level> | <level>{message}</level>",
    level="INFO",
    colorize=True
)

def get_logger(name: str):
    """获取带名称的 logger"""
    return logger.bind(name=name)

