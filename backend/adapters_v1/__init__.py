"""Trusted, dependency-independent Scaffold Arena adapter SDK."""

from . import models as _models
from .controlled_models import AttemptInput, ResultBundle
from .controls import (
    CONTROL_EXTENSION_NAMESPACE,
    CORE_CONTROL_IDS,
    AppliedControls,
    AttemptExecutionControls,
    ControlApplication,
    execution_controls_for,
)
from .invocation import InvocationContext

# Patch the canonical module exports before importing adapter implementations.
# The additive subclasses preserve the protocol-v1 wire shape: controls live in
# the existing namespaced scenario extension and applied_controls is optional.
_models.AttemptInput = AttemptInput
_models.ResultBundle = ResultBundle

from .base import HarnessAdapter
from .certification import certify_adapter
from .command_jsonl import CommandJsonlAdapter
from .external import DeepSeekHarnessAdapter, PiAdapter, PrimeAgentAdapter
from .http_rpc import HttpRpcAdapter, validate_rpc_endpoint
from .lm_studio import (
    LMStudioAdapter,
    lm_studio_endpoint_digest,
    validate_lm_studio_endpoint,
)
from .models import (
    AdapterCapabilities,
    AdapterHealth,
    ArtifactRef,
    CertificationReport,
    FailureClassification,
    PreparedAttempt,
    ProviderUsage,
    TerminalOutcome,
)
from .native import NativeScaffoldAdapter, ScaffoldRuntime, UsageEvidence
from .ollama import OllamaAdapter, ollama_endpoint_digest, validate_ollama_endpoint
from .context_handoff import ContextHandoffOllamaAdapter
from .openai_compatible import (
    OpenAICompatibleAdapter,
    endpoint_digest,
    validate_local_endpoint,
)
from .preflight import AdapterPreflightError, preflight
from .recorded import RecordedAdapter
from .registry import AdapterRegistry
from .transport import (
    AdapterTransportLimits,
    TransportLimitExceeded,
)

__all__ = [
    "CONTROL_EXTENSION_NAMESPACE",
    "CORE_CONTROL_IDS",
    "AdapterCapabilities",
    "AdapterHealth",
    "AdapterPreflightError",
    "AdapterRegistry",
    "AdapterTransportLimits",
    "AppliedControls",
    "ArtifactRef",
    "AttemptExecutionControls",
    "AttemptInput",
    "CertificationReport",
    "CommandJsonlAdapter",
    "ContextHandoffOllamaAdapter",
    "ControlApplication",
    "DeepSeekHarnessAdapter",
    "FailureClassification",
    "HarnessAdapter",
    "HttpRpcAdapter",
    "InvocationContext",
    "LMStudioAdapter",
    "NativeScaffoldAdapter",
    "OllamaAdapter",
    "OpenAICompatibleAdapter",
    "PiAdapter",
    "PreparedAttempt",
    "PrimeAgentAdapter",
    "ProviderUsage",
    "RecordedAdapter",
    "ResultBundle",
    "ScaffoldRuntime",
    "TerminalOutcome",
    "TransportLimitExceeded",
    "UsageEvidence",
    "certify_adapter",
    "endpoint_digest",
    "execution_controls_for",
    "lm_studio_endpoint_digest",
    "ollama_endpoint_digest",
    "preflight",
    "validate_lm_studio_endpoint",
    "validate_local_endpoint",
    "validate_ollama_endpoint",
    "validate_rpc_endpoint",
]
