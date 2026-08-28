"""Cztery rzuty tej samej powierzchni.

Każdy adapter jest cienki z zasady: jeśli musi coś wiedzieć o konkretnej
operacji, to znaczy, że wiedza wyciekła ze słownika do transportu.
"""
from .a2a import agent_card, handle_task
from .cli import build_parser, main
from .mcp import call_tool, list_tools
from .rest import build_router

__all__ = ["agent_card", "build_parser", "build_router", "call_tool", "handle_task",
           "list_tools", "main"]
