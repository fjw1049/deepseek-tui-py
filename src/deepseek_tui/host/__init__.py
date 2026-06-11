"""Host contracts for capability-module assembly."""

from deepseek_tui.host.assembler import (
    AssemblyRequest,
    EngineAssemblyRequest,
    assemble_engine,
    assemble_registry_only,
    assemble_tool_runtime,
)
from deepseek_tui.host.catalog import EMPTY_BUILTIN_CATALOG, BuiltinModuleCatalog
from deepseek_tui.host.contributions import (
    ContributionRegistryError,
    Contributions,
    PostTurnPipelineContribution,
)
from deepseek_tui.host.lifecycle import (
    AfterToolContext,
    BeforeToolContext,
    BeforeUserTurnContext,
    FunctionLifecycleObserver,
    LifecycleObserverRegistration,
    LifecycleRegistry,
    LifecycleRegistryError,
    ToolObserver,
    TurnCompletionContext,
    TurnFailureContext,
)
from deepseek_tui.host.module import (
    CapabilityModule,
    ModuleDescriptor,
    ModuleOrderError,
    resolve_module_order,
)
from deepseek_tui.host.prompts import (
    FunctionPromptContributor,
    PromptContribution,
    PromptContributor,
    PromptContributorContext,
    append_prompt_contributions,
)
from deepseek_tui.host.services import (
    ServiceRegistration,
    ServiceRegistry,
    ServiceRegistryError,
    ServiceScope,
)
from deepseek_tui.host.surfaces import (
    EventPresenterContribution,
    RuntimeRouteContribution,
    RuntimeSurfaceRegistry,
    RuntimeSurfaceRegistryError,
)

__all__ = [
    "AfterToolContext",
    "AssemblyRequest",
    "BeforeToolContext",
    "BeforeUserTurnContext",
    "BuiltinModuleCatalog",
    "CapabilityModule",
    "ContributionRegistryError",
    "Contributions",
    "EMPTY_BUILTIN_CATALOG",
    "EngineAssemblyRequest",
    "EventPresenterContribution",
    "FunctionPromptContributor",
    "FunctionLifecycleObserver",
    "LifecycleObserverRegistration",
    "LifecycleRegistry",
    "LifecycleRegistryError",
    "ModuleDescriptor",
    "ModuleOrderError",
    "PromptContribution",
    "PromptContributor",
    "PromptContributorContext",
    "PostTurnPipelineContribution",
    "RuntimeRouteContribution",
    "RuntimeSurfaceRegistry",
    "RuntimeSurfaceRegistryError",
    "ServiceRegistration",
    "ServiceRegistry",
    "ServiceRegistryError",
    "ServiceScope",
    "ToolObserver",
    "TurnCompletionContext",
    "TurnFailureContext",
    "assemble_engine",
    "assemble_registry_only",
    "assemble_tool_runtime",
    "append_prompt_contributions",
    "resolve_module_order",
]
