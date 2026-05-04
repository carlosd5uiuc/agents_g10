from __future__ import annotations

from dataclasses import dataclass

from .models import ActionProposal
from .providers import ModelProvider, ProviderRateLimitError
from .state import StateManager
from .models import TaskSpec


@dataclass
class ActionSelection:
    proposal: ActionProposal | None
    raw: object
    error: str | None = None
    rate_limited: bool = False
    retry_after_seconds: float | None = None


class ActionSelector:
    def __init__(self, provider: ModelProvider):
        self.provider = provider

    async def next_action(self, task: TaskSpec, state: StateManager, repair_context: str | None = None) -> ActionSelection:
        try:
            raw = await self.provider.propose(task, state, repair_context=repair_context)
        except ProviderRateLimitError as exc:
            return ActionSelection(
                proposal=None,
                raw={"provider_error": repr(exc), "rate_limited": True, "retry_after_seconds": exc.retry_after_seconds},
                error=str(exc),
                rate_limited=True,
                retry_after_seconds=exc.retry_after_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - provider failures are model-output failures for the agent loop
            return ActionSelection(proposal=None, raw={"provider_error": repr(exc)}, error=str(exc))
        try:
            proposal = ActionProposal.from_mapping(raw)
        except (TypeError, ValueError) as exc:
            return ActionSelection(proposal=None, raw=raw, error=str(exc))
        return ActionSelection(proposal=proposal, raw=raw)
