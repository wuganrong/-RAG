"""实时步骤追踪器，用于 SSE 流式进度展示。

追踪线性步骤序列，使用真实耗时替代模拟时间，根据步骤类型自适应调整
轮询间隔，并支持外部信号触发异步步骤完成。
"""

from __future__ import annotations

# 1. Python 标准库
import time
from dataclasses import dataclass


@dataclass
class StepDef:
    """步骤定义。

    Attributes:
        text: 步骤展示文本。
        min_duration: 自动推进前的最小展示时长（秒）。
            0.0 表示立即完成（首次 tick 即推进）。
        is_blocked: True 时永不自动推进，仅可通过 mark_done() 触发。
            用于对应真实异步工作的步骤（如检索）。
    """

    text: str
    min_duration: float = 0.3
    is_blocked: bool = False


@dataclass
class _CompletedStep:
    """内部：已完成的步骤记录。"""

    text: str
    elapsed: float
    has_time: bool


class StepTracker:
    """基于真实耗时的线性步骤追踪器。

    用法:
        tracker = StepTracker([
            StepDef("正在初始化...", min_duration=0.0),
            StepDef("正在检索...", min_duration=0.0, is_blocked=True),
        ])
        tracker.start()

        # 启动后台异步工作
        retrieval_thread.start()

        while not tracker.is_finished:
            tracker.tick()
            yield tracker.render_html()

            if tracker.current_step_def and tracker.current_step_def.is_blocked:
                if retrieval_done.is_set():
                    tracker.mark_done()
                    yield tracker.render_html()
                    break

            time.sleep(tracker.recommended_wait)
    """

    def __init__(self, steps: list[StepDef]) -> None:
        if not steps:
            raise ValueError("steps 至少需要一个 StepDef")
        self._steps = steps
        self._completed: list[_CompletedStep] = []
        self._current_idx: int = 0
        self._start_time: float | None = None
        self._step_start_time: float | None = None
        self._finished: bool = False
        self._done_pending: bool = False

    # ── 生命周期 ──────────────────────────────────────────────

    def start(self) -> None:
        """记录起始时间并开始追踪第一步。"""
        now = time.monotonic()
        self._start_time = now
        self._step_start_time = now
        self._finished = False
        self._done_pending = False
        self._current_idx = 0
        self._completed.clear()

    def tick(self) -> bool:
        """检查当前步骤是否应自动推进。

        Returns:
            True 表示步骤发生转移（调用方应重新渲染）。
        """
        if self._finished:
            return False

        step = self._current_step_def
        if step is None:
            self._finished = True
            return True

        if step.is_blocked:
            return False

        elapsed = time.monotonic() - self._step_start_time

        if step.min_duration <= 0.0:
            self._complete_current(0.0)
            self._advance()
            return True

        if elapsed >= step.min_duration:
            self._complete_current(elapsed)
            self._advance()
            return True

        return False

    def mark_done(self, elapsed: float | None = None) -> None:
        """通知当前阻塞步骤的异步工作已完成，记录真实耗时并推进。

        Args:
            elapsed: 异步工作的实际耗时（秒）。为 None 时使用步骤自身耗时。

        安全幂等：已推进或已完成时重复调用无副作用。
        """
        if self._finished or self._done_pending:
            return
        step = self._current_step_def
        if step is None or not step.is_blocked:
            return
        if elapsed is None:
            elapsed = time.monotonic() - self._step_start_time
        self._complete_current(elapsed)
        self._done_pending = True
        self._advance()

    # ── 状态查询 ──────────────────────────────────────────────

    @property
    def is_finished(self) -> bool:
        """所有步骤是否已完成。"""
        return self._finished

    @property
    def step_index(self) -> int:
        """当前步骤索引（0-based）。"""
        return self._current_idx

    @property
    def current_step_def(self) -> StepDef | None:
        """当前步骤定义，已完成时返回 None。"""
        if self._finished or self._current_idx >= len(self._steps):
            return None
        return self._steps[self._current_idx]

    @property
    def elapsed_total(self) -> float:
        """自 start() 以来的真实总耗时（秒）。"""
        if self._start_time is None:
            return 0.0
        return time.monotonic() - self._start_time

    @property
    def recommended_wait(self) -> float:
        """根据当前步骤类型返回自适应等待间隔。

        - 非阻塞步骤：计算剩余时长，返回 0.05~0.12s，保持 UI 灵敏
        - 阻塞步骤：0.15s 起步，逐步增至 0.50s，等待中降低 CPU 开销
        """
        step = self.current_step_def
        if step is None:
            return 0.50
        if step.is_blocked:
            elapsed = time.monotonic() - self._step_start_time
            if elapsed < 1.0:
                return 0.15
            elif elapsed < 3.0:
                return 0.30
            else:
                return 0.50
        remaining = step.min_duration - (time.monotonic() - self._step_start_time)
        if remaining <= 0:
            return 0.05
        return max(0.05, min(0.12, remaining + 0.02))

    # ── 渲染 ──────────────────────────────────────────────────

    def render_html(self) -> str:
        """渲染所有已完成步骤及当前进行中步骤的 HTML。

        格式与前端兼容：
          - 已完成耗时步骤: <p>{text}耗时{duration:.1f}s</p>
          - 已完成瞬时步骤: <p>{text}。</p>
          - 当前步骤: <p>{text}耗时{elapsed:.1f}s</p> 或 <p>{text}。</p>
          - 总耗时(>=2.0s): <p>总耗时{total:.1f}s</p>
        """
        parts: list[str] = []

        for cs in self._completed:
            if cs.has_time:
                parts.append(f"<p>{cs.text}耗时{cs.elapsed:.1f}s</p>")
            else:
                parts.append(f"<p>{cs.text}。</p>")

        if not self._finished and self._current_idx < len(self._steps):
            step = self._steps[self._current_idx]
            elapsed = time.monotonic() - self._step_start_time
            # 阻塞步骤：elapsed 可能为 0，先显示 "。" 再过渡到耗时
            if step.is_blocked:
                if elapsed >= 0.3:
                    parts.append(f"<p>{step.text}耗时{elapsed:.1f}s</p>")
                else:
                    parts.append(f"<p>{step.text}。</p>")
            elif step.min_duration > 0:
                # 非阻塞定时步骤：始终显示耗时，渐进递增避免重复渲染
                parts.append(f"<p>{step.text}耗时{elapsed:.1f}s</p>")
            else:
                # 瞬时步骤（min_duration=0）：显示 0.0s
                parts.append(f"<p>{step.text}耗时{elapsed:.1f}s</p>")

        total = self.elapsed_total
        if total >= 2.0:
            parts.append(f"<p>总耗时{total:.1f}s</p>")

        return "\n".join(parts)

    # ── 内部方法 ──────────────────────────────────────────────

    @property
    def _current_step_def(self) -> StepDef | None:
        if self._finished or self._current_idx >= len(self._steps):
            return None
        return self._steps[self._current_idx]

    def _complete_current(self, elapsed: float) -> None:
        step = self._steps[self._current_idx]
        has_time = True
        self._completed.append(
            _CompletedStep(text=step.text, elapsed=elapsed, has_time=has_time)
        )

    def _advance(self) -> None:
        self._current_idx += 1
        if self._current_idx >= len(self._steps):
            self._finished = True
        else:
            self._step_start_time = time.monotonic()
            self._done_pending = False
