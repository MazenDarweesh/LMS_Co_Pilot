"""
Prompts for Autonomous Agentic Stepper Package.
Centralizes all LLM prompt templates and helper constructors used by
ScreenResolver and PayloadExtractor, separating prompt definitions from logic.
"""

from src.core.prompts import (
    ERP_PAYMENT_RULES,
    STEPPER_SCREEN_RESOLVER_PROMPT_TEMPLATE,
    STEPPER_TRANSACTION_EXTRACTION_PROMPT_TEMPLATE,
    get_stepper_screen_resolver_prompt,
    get_stepper_transaction_extraction_prompt,
)

__all__ = [
    "ERP_PAYMENT_RULES",
    "STEPPER_SCREEN_RESOLVER_PROMPT_TEMPLATE",
    "STEPPER_TRANSACTION_EXTRACTION_PROMPT_TEMPLATE",
    "get_stepper_screen_resolver_prompt",
    "get_stepper_transaction_extraction_prompt",
]
