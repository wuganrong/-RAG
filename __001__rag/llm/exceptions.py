"""LLM 相关异常类定义。

底层将第三方 SDK 异常包装为项目自定义异常，
上层可针对性捕获并决定降级策略（重试 / 报错 / 兜底）。
"""


class LLMConfigError(ValueError):
    """LLM 配置不可用（模型未找到、厂商配置缺失等）。不可重试。"""


class LLMAuthError(PermissionError):
    """LLM API 认证失败（API Key 无效、过期、权限不足）。不可重试。"""


class LLMTimeoutError(TimeoutError):
    """LLM API 调用超时。可重试。"""


class LLMRateLimitError(RuntimeError):
    """LLM API 触发限流。可重试。"""


class LLMResponseError(RuntimeError):
    """LLM API 返回了不可解析或格式异常的响应。通常不可重试。"""
