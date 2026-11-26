"""
DAROGA Token Optimization & Observability Module
================================================
Tracks and records LLM usage, input/output tokens, cache hits, deterministic rules evaluated,
and files scanned to enforce the "Minimum LLM Usage — Code First, Scripts First, LLM Last" requirement.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class TokenUsageMetrics:
    files_scanned: int = 0
    files_sent_to_llm: int = 0
    aws_resources_inspected: int = 0
    deterministic_findings: int = 0
    ai_reasoning_calls: int = 0
    cache_hits: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_api_cost_usd: float = 0.0

    def format_summary(self) -> str:
        return f"""Inspection Summary
------------------
Files scanned: {self.files_scanned}
Files sent to LLM: {self.files_sent_to_llm}
AWS resources inspected: {self.aws_resources_inspected}
Deterministic findings: {self.deterministic_findings}
AI reasoning calls: {self.ai_reasoning_calls}
Cache hits: {self.cache_hits}
Total input tokens: {self.total_input_tokens}
Total output tokens: {self.total_output_tokens}
Estimated API cost: ${self.estimated_api_cost_usd:.4f}"""


class TokenTracker:
    """
    Singleton tracker collecting observability metrics across the inspection lifecycle.
    """

    def __init__(self):
        self.metrics = TokenUsageMetrics()

    def record_scan(self, total_files: int):
        self.metrics.files_scanned = total_files

    def record_aws(self, resource_count: int):
        self.metrics.aws_resources_inspected = resource_count

    def record_deterministic_finding(self, count: int = 1):
        self.metrics.deterministic_findings += count

    def record_llm_call(self, in_tokens: int, out_tokens: int, cost_usd: float = 0.0, files_included: int = 1):
        self.metrics.ai_reasoning_calls += 1
        self.metrics.files_sent_to_llm += files_included
        self.metrics.total_input_tokens += in_tokens
        self.metrics.total_output_tokens += out_tokens
        self.metrics.estimated_api_cost_usd += cost_usd

    def record_cache_hit(self):
        self.metrics.cache_hits += 1

    def get_summary(self) -> str:
        return self.metrics.format_summary()
