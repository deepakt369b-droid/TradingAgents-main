
from .base_client import BaseLLMClient


def create_llm_client(
    provider: str,
    model: str,
    base_url: str | None = None,
    **kwargs,
) -> BaseLLMClient:
    """Create an LLM client for the specified provider.

    Provider modules are imported lazily so that simply importing this
    factory (e.g. during test collection) does not pull in heavy LLM SDKs
    or fail when their API keys are absent.

    Args:
        provider: LLM provider name
        model: Model name/identifier
        base_url: Optional base URL for API endpoint
        **kwargs: Additional provider-specific arguments

    Returns:
        Configured BaseLLMClient instance

    Raises:
        ValueError: If provider is not supported
    """
    provider_lower = provider.lower()

    # Apply Cloudflare AI Gateway settings if configured and base_url is not explicitly provided
    from .cloudflare_gateway import CloudflareAIGateway
    cf_gateway = CloudflareAIGateway()
    if cf_gateway.is_configured and not base_url:
        kwargs = cf_gateway.apply_to_kwargs(provider_lower, kwargs)
        base_url = kwargs.get("base_url", base_url)

    # Extract fallback_providers if present
    fallback_providers = kwargs.pop("fallback_providers", None)

    # Native (non-OpenAI) APIs are matched first so their string check doesn't
    # import the OpenAI client. Everything else is OpenAI-compatible and routes
    # through the provider registry (single source of truth).
    if provider_lower == "anthropic":
        from .anthropic_client import AnthropicClient
        client = AnthropicClient(model, base_url, **kwargs)

    elif provider_lower == "google":
        from .google_client import GoogleClient
        client = GoogleClient(model, base_url, **kwargs)

    elif provider_lower == "azure":
        from .azure_client import AzureOpenAIClient
        client = AzureOpenAIClient(model, base_url, **kwargs)

    elif provider_lower == "bedrock":
        from .bedrock_client import BedrockClient
        client = BedrockClient(model, base_url, **kwargs)

    else:
        from .openai_client import OpenAIClient, is_openai_compatible
        if is_openai_compatible(provider_lower):
            client = OpenAIClient(model, base_url, provider=provider_lower, **kwargs)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    # Wrap in ResilientLLMGateway if fallback providers are configured
    if fallback_providers:
        from .llm_gateway import ResilientLLMGateway
        fallback_clients = []
        for fb in fallback_providers:
            if isinstance(fb, str):
                fallback_clients.append(create_llm_client(provider=fb, model=model))
            elif isinstance(fb, dict):
                fallback_clients.append(create_llm_client(**fb))
        return ResilientLLMGateway(primary_client=client, fallback_clients=fallback_clients)

    return client
