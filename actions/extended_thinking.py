"""
title: Extended Thinking Toggle
author: @nokodo
description: Toggle extended thinking mode with configurable reasoning effort
version: 1.0.0
required_open_webui_version: >= 0.9.0
license: see extension documentation file `extended_thinking.md` (License section) for the licensing terms.
"""

from typing import Any, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, Field


class Action:
    """Action to toggle extended thinking mode with configurable reasoning effort."""

    class Valves(BaseModel):
        reasoning_effort: Literal["low", "medium", "high", "max"] = Field(
            default="medium",
            description="reasoning effort level: low, medium, high, max",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def action(
        self,
        body: dict[str, Any],
        __user__: Optional[dict[str, Any]] = None,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
        __event_call__: Optional[Callable[[Any], Awaitable[Any]]] = None,
        __model__: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Toggle extended thinking mode."""

        reasoning_effort = self.valves.reasoning_effort

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "notification",
                    "data": {
                        "type": "success",
                        "content": f"reasoning effort set to: {reasoning_effort}",
                    },
                }
            )

        return {
            "content": f"**Extended thinking mode**\n\nReasoning effort: `{reasoning_effort}`\n\nThis will apply to your next message.",
        }
