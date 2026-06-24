"""
ToolRegistry — aggregates all tool providers and routes dispatch.

Provider check order:
  1. PlatformToolProvider  — always active, no DB required
  2. CoachingToolProvider  — active when business_type == coaching_institute
  3. TenantCustomToolProvider — active per tenant, loaded from DB (checked last)

Usage:
    from backend.tools.registry import get_registry

    tools = await get_registry().get_tools(tenant_ctx)
    result = await get_registry().dispatch(name, args, session_ctx)
"""

from __future__ import annotations

import logging
from typing import Any

from backend.tools.base import ToolNotFoundError
from backend.tools.platform import PlatformToolProvider
from backend.tools.coaching import CoachingToolProvider
from backend.tools.tenant_custom import TenantCustomToolProvider

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Aggregates platform, vertical, and tenant-custom tool providers.

    • get_tools()  returns the merged, deduplicated tool list in OpenAI format.
    • dispatch()   routes a tool call to the owning provider.
    """

    def __init__(self) -> None:
        self._platform = PlatformToolProvider()
        self._coaching = CoachingToolProvider()
        self._custom = TenantCustomToolProvider()

        # Ordered list — dispatch tries these in sequence (custom last, slowest)
        self._providers = [self._platform, self._coaching, self._custom]

    async def get_tools(self, tenant_ctx: Any) -> list[dict]:
        """
        Return all active tools for the tenant in OpenAI function format.

        Platform tools are always present (subject to their own filtering).
        Coaching tools only appear for coaching_institute tenants.
        Custom tools are loaded from the DB for this specific tenant.
        """
        merged: list[dict] = []
        seen: set[str] = set()

        for provider in self._providers:
            for tool in await provider.list_tools(tenant_ctx):
                name = tool.get("function", {}).get("name", "")
                if name and name not in seen:
                    merged.append(tool)
                    seen.add(name)

        logger.info(
            "[Registry] get_tools → %d tools (tenant=%s)",
            len(merged),
            getattr(tenant_ctx, "slug", None) or "global",
        )
        return merged

    async def dispatch(self, name: str, args: dict, session_ctx: dict) -> dict:
        """
        Route a tool call to the first provider that handles it.

        Platform and coaching providers are checked first (fast, in-memory).
        TenantCustomToolProvider is checked last (requires a DB query).
        """
        # Fast path: platform owns the name
        if self._platform.handles(name):
            return await self._platform.call_tool(name, args, session_ctx)

        # Coaching tools
        if self._coaching.handles(name):
            return await self._coaching.call_tool(name, args, session_ctx)

        # Custom tools (DB lookup — slowest, try last)
        try:
            return await self._custom.call_tool(name, args, session_ctx)
        except ToolNotFoundError:
            logger.warning("[Registry] Unknown tool dispatched: %s", name)
            return {"error": f"Unknown tool: {name}"}

    # ── Convenience accessors ─────────────────────────────────────────────────

    @property
    def platform(self) -> PlatformToolProvider:
        return self._platform

    @property
    def coaching(self) -> CoachingToolProvider:
        return self._coaching

    @property
    def custom(self) -> TenantCustomToolProvider:
        return self._custom


# ── Singleton ─────────────────────────────────────────────────────────────────

_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Return the global ToolRegistry singleton (created lazily)."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        logger.info("[Registry] Initialized ToolRegistry (platform + coaching + custom)")
    return _registry
