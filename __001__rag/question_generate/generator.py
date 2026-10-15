"""分层问题生成器。

将 LLM 配置和提示词统一在构造时注入，
不查询数据库，保持纯逻辑可复用。
"""

from __future__ import annotations

# 1. Python 标准库
import json
import math
import re
from typing import Any

# 2. 第三方库
from django.conf import settings
from loguru import logger

# 3. 本地应用
from __001__rag.assistant import AssistantService
from __001__rag.llm.base import ChatMessage
from __001__rag.llm.service import LLMService
from __001__rag.utils.llm_response import extract_json_from_llm_response

from .utils import (
    bounded_int,
    cosine_similarity,
    parse_question_list,
    strip_thinking,
)

# ---------------------------------------------------------------------------
# 默认提示词（优先从 settings 读取，未配置则使用内置默认值）
# ---------------------------------------------------------------------------

_BUILTIN_ASSESS_PROMPT = """
请评估知识片段的信息量和复杂度，并只返回 JSON：
{
  "complexity_score": 1-10,
  "info_points": 信息点数量,
  "suggested_total": 建议问题总数,
  "suggested_overview": 建议宏观问题数,
  "suggested_detail": 建议细节问题数
}
""".strip()

_BUILTIN_OVERVIEW_PROMPT = "生成宏观定位型问题，问题简短，不涉及过细参数。"
_BUILTIN_DETAIL_PROMPT = "生成细节深入型问题，问题具体，覆盖参数、步骤、条件或标准。"
_BUILTIN_MIXED_PROMPT = "生成多层次问题，既包含宏观定位，也包含细节追问。"
_BUILTIN_QUESTION_PROMPT = """
你是知识库问题生成助手。
{type_instruction}
如果无法继续生成有价值的新问题，请直接返回：{finished_flag}
请只返回 JSON 数组，例如 ["问题1", "问题2"]。
""".strip()

_FINISHED_FLAG = "finished"


def _get_default_assess_prompt() -> str:
    return getattr(settings, "QUESTION_GEN_ASSESS_PROMPT", _BUILTIN_ASSESS_PROMPT)


def _get_default_overview_prompt() -> str:
    return getattr(settings, "QUESTION_GEN_OVERVIEW_PROMPT", _BUILTIN_OVERVIEW_PROMPT)


def _get_default_detail_prompt() -> str:
    return getattr(settings, "QUESTION_GEN_DETAIL_PROMPT", _BUILTIN_DETAIL_PROMPT)


def _get_default_mixed_prompt() -> str:
    return getattr(settings, "QUESTION_GEN_MIXED_PROMPT", _BUILTIN_MIXED_PROMPT)


def _get_default_question_prompt() -> str:
    return getattr(settings, "QUESTION_GEN_QUESTION_PROMPT", _BUILTIN_QUESTION_PROMPT)


class QuestionGenerator:
    """分层的知识库问题生成器。

    所有配置（模型参数和提示词）在构造时注入，不查询数据库。

    用法:
        generator = QuestionGenerator(
            model_config={"model_name": "qwen2.5:14b@Ollama", "temperature": 0.3, ...},
            prompts={
                "assess_system_prompt": "...",
                "question_generate_system_prompt": "...",
                "overview_instruction": "...",
                "detail_instruction": "...",
                "mixed_instruction": "...",
            },
            embedding_model_name="bge-large-zh-v1.5",
        )
        questions = generator.generate(snippet, max_questions=5)
    """

    def __init__(
        self,
        model_config: dict[str, Any] | None = None,
        prompts: dict[str, str] | None = None,
        embedding_model_name: str | None = None,
    ) -> None:
        """初始化问题生成器。

        Args:
            model_config: LLM 模型配置 {"model_name", "temperature", "top_p", "max_tokens", "extra_params"}
            prompts: 提示词配置 {"assess_system_prompt", "question_generate_system_prompt",
                     "overview_instruction", "detail_instruction", "mixed_instruction"}
            embedding_model_name: 用于问题去重的 Embedding 模型名称
        """
        mc = model_config or {}
        self.model_name: str | None = mc.get("model_name")
        self.temperature: float | None = mc.get("temperature")
        self.top_p: float | None = mc.get("top_p")
        self.max_tokens: int | None = mc.get("max_tokens")
        self.extra_params: dict[str, Any] = mc.get("extra_params") or {}
        self._prompts: dict[str, str] = prompts or {}
        self.embedding_model_name: str | None = (
            embedding_model_name or getattr(settings, "EMBEDDING_MODEL_ID", None)
        )
        logger.info(
            "问题生成器初始化完成，model_name={}，embedding_model={}",
            self.model_name,
            self.embedding_model_name,
        )

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def generate(
        self,
        snippet: str,
        max_questions: int | None = None,
        similarity_threshold: float | None = None,
        max_retry: int | None = None,
    ) -> list[str]:
        """从知识片段生成问题列表。

        Args:
            snippet: 知识片段文本
            max_questions: 最多生成的问题数量
            similarity_threshold: 去重时的相似度阈值
            max_retry: 每层问题的最大重试轮数

        Returns:
            问题文本列表
        """
        _max_questions = max_questions if max_questions is not None else int(getattr(settings, "QUESTION_GEN_MAX_QUESTIONS", 5))
        _similarity_threshold = similarity_threshold if similarity_threshold is not None else float(getattr(settings, "QUESTION_GEN_SIMILARITY_THRESHOLD", 0.55))
        _max_retry = max_retry if max_retry is not None else int(getattr(settings, "QUESTION_GEN_MAX_RETRY", 3))
        logger.info(
            "开始生成问题，content_length={}, max_questions={}, similarity_threshold={}, max_retry={}",
            len(snippet),
            _max_questions,
            _similarity_threshold,
            _max_retry,
        )
        result = self._generate_hierarchical(
            snippet=snippet,
            max_questions=_max_questions,
            similarity_threshold=_similarity_threshold,
            max_retry=_max_retry,
        )
        questions = [item["question"] for item in result["all_questions"]]
        logger.info("问题生成完成，question_count={}", len(questions))
        return questions

    # ------------------------------------------------------------------
    # 分层生成流程
    # ------------------------------------------------------------------

    def _generate_hierarchical(
        self,
        snippet: str,
        max_questions: int = 5,
        similarity_threshold: float = 0.55,
        max_retry: int = 3,
    ) -> dict[str, Any]:
        """分宏观、细节两个层次生成问题并去重。"""
        logger.info("进入分层问题生成流程")

        assessment = self._assess_complexity(snippet)
        suggested_overview = assessment["overview"]
        suggested_detail = assessment["detail"]

        if suggested_overview + suggested_detail > max_questions:
            ratio = suggested_overview / max(suggested_overview + suggested_detail, 1)
            suggested_overview = max(1, math.floor(max_questions * ratio))
            suggested_detail = max(1, max_questions - suggested_overview)
            logger.info(
                "按最大问题数调整分配，overview={}, detail={}, max_questions={}",
                suggested_overview,
                suggested_detail,
                max_questions,
            )

        logger.info("开始生成宏观问题，target_count={}", suggested_overview)
        overview_questions = self._generate_level_questions(
            snippet=snippet,
            exist_questions=[],
            target_count=suggested_overview,
            question_type="overview",
            max_retry=max_retry,
        )
        overview_exist = [item["question"] for item in overview_questions]
        logger.info("宏观问题生成结束，accepted_count={}", len(overview_questions))

        logger.info("开始生成细节问题，target_count={}", suggested_detail)
        detail_questions = self._generate_level_questions(
            snippet=snippet,
            exist_questions=overview_exist,
            target_count=suggested_detail,
            question_type="detail",
            max_retry=max_retry,
        )
        logger.info("细节问题生成结束，accepted_count={}", len(detail_questions))

        logger.info("开始最终去重，candidate_count={}", len(overview_questions) + len(detail_questions))
        all_questions = self._filter_duplicate_questions(
            overview_questions + detail_questions,
            similarity_threshold=similarity_threshold,
        )[:max_questions]
        logger.info("最终去重结束，final_count={}", len(all_questions))

        return {
            "overview_questions": [item for item in all_questions if item["type"] == "overview"],
            "detail_questions": [item for item in all_questions if item["type"] == "detail"],
            "all_questions": all_questions,
            "metadata": {
                "complexity_score": assessment["complexity_score"],
                "info_points": assessment["info_points"],
                "overview_count": len([item for item in all_questions if item["type"] == "overview"]),
                "detail_count": len([item for item in all_questions if item["type"] == "detail"]),
                "total_count": len(all_questions),
                "suggested_overview": suggested_overview,
                "suggested_detail": suggested_detail,
            },
        }

    # ------------------------------------------------------------------
    # 片段评估
    # ------------------------------------------------------------------

    def _assess_complexity(self, snippet: str) -> dict[str, int]:
        """评估片段复杂度，内部通过 assistant_key="assess_snippet_complexity" 获取配置。"""
        logger.info("开始评估片段复杂度，content_length={}", len(snippet))
        default = self._get_default_assessment(snippet)

        assess_config = AssistantService.get_task_config("assess_snippet_complexity")
        system_prompt = assess_config.get("system_prompt") or _get_default_assess_prompt()
        user_prompt_template = assess_config.get("user_prompt_template") or "【知识片段】：\n{snippet}\n\n请评估该片段的信息量和复杂度。"
        user_prompt = user_prompt_template.replace("{snippet}", snippet)

        model_overrides = {
            "model_name": assess_config.get("model_name"),
            "temperature": assess_config.get("temperature"),
            "top_p": assess_config.get("top_p"),
            "max_tokens": assess_config.get("max_tokens"),
            "extra_params": assess_config.get("extra_params") or {},
        }
        logger.info(
            "评估配置加载完成，model_name={}, temperature={}, top_p={}",
            model_overrides["model_name"],
            model_overrides["temperature"],
            model_overrides["top_p"],
        )

        try:
            response = self._chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                default_temperature=float(getattr(settings, "QUESTION_GEN_DEFAULT_TEMPERATURE", 0.1)),
                default_max_tokens=int(getattr(settings, "QUESTION_GEN_ASSESS_MAX_TOKENS", 300)),
                model_overrides=model_overrides,
            )
            assessment = self._extract_assessment(response)
            normalized = self._normalize_assessment(assessment, default)
            logger.info(
                "片段复杂度评估完成，complexity_score={}, info_points={}, overview={}, detail={}",
                normalized["complexity_score"],
                normalized["info_points"],
                normalized["overview"],
                normalized["detail"],
            )
            return normalized
        except Exception:
            logger.exception("评估知识片段复杂度失败，使用默认值")
            return default

    # ------------------------------------------------------------------
    # 分层问题生成
    # ------------------------------------------------------------------

    def _generate_level_questions(
        self,
        *,
        snippet: str,
        exist_questions: list[str],
        target_count: int,
        question_type: str,
        max_retry: int,
    ) -> list[dict[str, str]]:
        """按指定层次类型生成问题，支持重试。"""
        if target_count <= 0:
            logger.info("{} 问题目标数为 0，跳过", question_type)
            return []

        accepted: list[dict[str, str]] = []
        current_exist = exist_questions.copy()
        for index in range(max_retry):
            if len(accepted) >= max(1, math.ceil(target_count * 0.5)):
                logger.info("{} 问题已达到接收阈值，停止重试，accepted_count={}", question_type, len(accepted))
                break

            needed = target_count - len(accepted)
            logger.info("{} 问题生成第 {} 轮，needed_count={}", question_type, index + 1, needed)
            questions = self._generate_questions_batch(snippet, current_exist, needed, question_type=question_type)
            if not questions:
                logger.info("{} 问题生成第 {} 轮无新增结果", question_type, index + 1)
                break

            for question in questions:
                if not self._is_duplicate(question, current_exist):
                    accepted.append({"question": question, "type": question_type})
                    current_exist.append(question)

            logger.info(
                "{} 问题第 {} 轮处理完成，generated_count={}, accepted_count={}",
                question_type,
                index + 1,
                len(questions),
                len(accepted),
            )

        return accepted

    def _generate_questions_batch(
        self,
        snippet: str,
        exist_questions: list[str],
        needed_count: int,
        question_type: str = "mixed",
    ) -> list[str]:
        """调用 LLM 生成指定层次的一批问题。"""
        type_instruction = self._get_type_instruction(question_type)
        system_prompt = self._prompts.get("question_generate_system_prompt") or _get_default_question_prompt()
        system_prompt = system_prompt.replace("{type_instruction}", type_instruction)
        system_prompt = system_prompt.replace("{finished_flag}", _FINISHED_FLAG)
        system_prompt = system_prompt.replace("{topn}", str(needed_count))

        user_prompt = f"""
【知识片段】：
{snippet}

【已采纳问题列表】：
{json.dumps(exist_questions, ensure_ascii=False)}

【任务】：
请生成最多 {needed_count} 个新的{'宏观定位型' if question_type == 'overview' else '细节深入型' if question_type == 'detail' else '多层次'}问题。

【要求】：
1. 质量优先，不要为凑数生成语义重复问题。
2. 如果没有新的有价值问题，请返回：{_FINISHED_FLAG}
3. 输出 JSON 数组，不要输出解释。
""".strip()

        try:
            response = self._chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                default_temperature=float(getattr(settings, "QUESTION_GEN_DEFAULT_TEMPERATURE", 0.1)),
                default_max_tokens=int(getattr(settings, "QUESTION_GEN_GENERATE_MAX_TOKENS", 500)),
            )
        except Exception:
            logger.exception("生成问题失败")
            return []

        cleaned = strip_thinking(response)
        if len(cleaned) < 20 and _FINISHED_FLAG in cleaned.lower():
            logger.info("{} 问题生成返回 finished 标志", question_type)
            return []

        questions = parse_question_list(cleaned, needed_count)
        logger.info("{} 问题解析完成，parsed_count={}", question_type, len(questions))
        return questions

    def _get_type_instruction(self, question_type: str) -> str:
        """获取指定问题类型的提示词指令。"""
        config_map = {
            "overview": ("overview_instruction", _get_default_overview_prompt()),
            "detail": ("detail_instruction", _get_default_detail_prompt()),
            "mixed": ("mixed_instruction", _get_default_mixed_prompt()),
        }
        prompt_key, default_prompt = config_map.get(question_type, config_map["mixed"])
        prompt = self._prompts.get(prompt_key) or default_prompt
        logger.info("加载问题类型提示词，question_type={}, prompt_key={}", question_type, prompt_key)
        return prompt

    # ------------------------------------------------------------------
    # LLM 调用
    # ------------------------------------------------------------------

    def _chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        default_temperature: float,
        default_max_tokens: int,
        model_overrides: dict[str, Any] | None = None,
    ) -> str:
        """使用注入的模型配置调用 LLM，可通过 model_overrides 覆盖单次调用的参数。"""
        overrides = model_overrides or {}
        model_id = (
            overrides.get("model_name")
            or self.model_name
            or getattr(settings, "LLM_MODEL_ID", None)
        )
        temperature = (
            overrides.get("temperature")
            if overrides.get("temperature") is not None
            else (self.temperature if self.temperature is not None else default_temperature)
        )
        top_p = overrides.get("top_p") if "top_p" in overrides else self.top_p
        max_tokens = (
            overrides.get("max_tokens")
            if overrides.get("max_tokens") is not None
            else (self.max_tokens if self.max_tokens is not None else default_max_tokens)
        )
        extra = overrides.get("extra_params") or self.extra_params
        logger.info(
            "调用问题生成 LLM，model_id={}, temperature={}, top_p={}, max_tokens={}",
            model_id,
            temperature,
            top_p,
            max_tokens,
        )
        response = LLMService.chat(
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt),
            ],
            model_name=model_id,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            extra=extra,
        )
        logger.info("问题生成 LLM 调用完成，response_length={}", len(response.content or ""))
        return response.content

    # ------------------------------------------------------------------
    # 去重
    # ------------------------------------------------------------------

    def _filter_duplicate_questions(
        self,
        questions: list[dict[str, str]],
        similarity_threshold: float,
    ) -> list[dict[str, str]]:
        """对问题列表进行语义去重。"""
        result: list[dict[str, str]] = []
        exist: list[str] = []
        for item in questions:
            question = item["question"]
            if not self._is_duplicate(question, exist, threshold=similarity_threshold):
                result.append(item)
                exist.append(question)
        return result

    def _is_duplicate(self, question: str, exist_questions: list[str], threshold: float | None = None) -> bool:
        """检查问题是否与已有问题语义重复。"""
        if not exist_questions:
            return False

        _threshold = threshold if threshold is not None else float(getattr(settings, "QUESTION_GEN_DEDUP_THRESHOLD", 0.85))
        try:
            logger.info(
                "开始问题去重检测，embedding_model={}, existing_count={}",
                self.embedding_model_name,
                len(exist_questions),
            )
            question_emb = LLMService.embed([question], model_name=self.embedding_model_name)[0]
            exist_embs = LLMService.embed(exist_questions, model_name=self.embedding_model_name)
            max_similarity = max(cosine_similarity(question_emb, emb) for emb in exist_embs)
            is_duplicate = max_similarity >= _threshold
            logger.info(
                "问题去重检测完成，max_similarity={:.4f}, threshold={}, duplicate={}",
                max_similarity,
                _threshold,
                is_duplicate,
            )
            return is_duplicate
        except Exception:
            logger.exception("问题去重向量计算失败，退化为文本去重")
            return any(question in exist or exist in question for exist in exist_questions)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _get_default_assessment(snippet: str) -> dict[str, int]:
        """按片段长度给出默认复杂度评估。"""
        length = len(snippet)
        if length < 30:
            return {"complexity_score": 2, "info_points": 1, "total": 1, "overview": 1, "detail": 0}
        if length < 100:
            return {"complexity_score": 4, "info_points": 2, "total": 3, "overview": 1, "detail": 2}
        if length < 300:
            return {"complexity_score": 6, "info_points": 4, "total": 6, "overview": 2, "detail": 4}
        return {"complexity_score": 8, "info_points": 6, "total": 10, "overview": 3, "detail": 7}

    @staticmethod
    def _extract_assessment(response: str) -> dict[str, Any]:
        """从 LLM 返回中提取评估 JSON。"""
        cleaned = strip_thinking(response)
        result = extract_json_from_llm_response(cleaned)
        return result if isinstance(result, dict) else {}

    @staticmethod
    def _normalize_assessment(
        assessment: dict[str, Any],
        default: dict[str, int],
    ) -> dict[str, int]:
        """将 LLM 返回的评估值标准化到合理范围。"""
        total = bounded_int(assessment.get("suggested_total"), default["total"], 0, 15)
        overview = bounded_int(assessment.get("suggested_overview"), default["overview"], 0, 5)
        detail = bounded_int(assessment.get("suggested_detail"), default["detail"], 0, 10)

        if overview + detail != total:
            detail = max(0, total - overview)

        return {
            "complexity_score": bounded_int(assessment.get("complexity_score"), default["complexity_score"], 0, 10),
            "info_points": bounded_int(assessment.get("info_points"), default["info_points"], 1, 50),
            "total": total,
            "overview": overview,
            "detail": detail,
        }
