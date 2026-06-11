"""Host contracts for capability-module assembly."""

from deepseek_tui.host.assembler import (
    AssembledContributions,
    AssemblyRequest,
    EngineAssemblyRequest,
    assemble_engine,
    assemble_registry_only,
    assemble_tool_runtime,
    collect_builtin_contributions,
    resolve_assembly_prompt_contributors,
)
from deepseek_tui.host.engine_attach import EngineAttachRequest, attach_engine_capabilities
from deepseek_tui.host.catalog import (
    EMPTY_BUILTIN_CATALOG,
    BuiltinModuleCatalog,
    default_builtin_catalog,
)
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
    TurnStartedContext,
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
    build_surface_router,
    mount_surface_routes,
)
from deepseek_tui.host.tool_execution import (
    RlmToolExecution,
    ToolExecutionContext,
    WorkflowToolExecution,
)

__all__ = [
    "AfterToolContext",
    "AssembledContributions",
    "AssemblyRequest",
    "BeforeToolContext",
    "BeforeUserTurnContext",
    "BuiltinModuleCatalog",
    "default_builtin_catalog",
    "CapabilityModule",
    "ContributionRegistryError",
    "Contributions",
    "EMPTY_BUILTIN_CATALOG",
    "EngineAssemblyRequest",
    "EngineAttachRequest",
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
    "RlmToolExecution",
    "ServiceRegistration",
    "ServiceRegistry",
    "ServiceRegistryError",
    "ServiceScope",
    "ToolExecutionContext",
    "ToolObserver",
    "TurnCompletionContext",
    "TurnFailureContext",
    "TurnStartedContext",
    "WorkflowToolExecution",
    "attach_engine_capabilities",
    "assemble_engine",
    "assemble_registry_only",
    "assemble_tool_runtime",
    "append_prompt_contributions",
    "build_surface_router",
    "collect_builtin_contributions",
    "mount_surface_routes",
    "resolve_assembly_prompt_contributors",
    "resolve_module_order",
]
