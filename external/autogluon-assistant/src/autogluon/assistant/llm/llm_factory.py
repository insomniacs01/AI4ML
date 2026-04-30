import logging
import os
from typing import Any, Dict, Optional

from omegaconf import DictConfig

logger = logging.getLogger(__name__)


class ChatLLMFactory:
    """Factory class for creating chat models with LangGraph support."""

    @staticmethod
    def get_total_token_usage(save_path: Optional[str] = None) -> Dict[str, Any]:
        """Get total token usage across all conversations and sessions."""
        from .base_chat import GlobalTokenTracker

        return GlobalTokenTracker().get_total_usage(save_path)

    @classmethod
    def get_valid_models(cls, provider):
        if provider == "azure":
            from .azure_openai_chat import get_azure_models

            return get_azure_models()
        elif provider == "openai":
            from .openai_chat import get_openai_models

            return get_openai_models()
        elif provider == "bedrock":
            from .bedrock_chat import get_bedrock_models

            return get_bedrock_models()
        elif provider == "anthropic":
            from .anthropic_chat import get_anthropic_models

            return get_anthropic_models()
        elif provider == "sagemaker":
            from .sagemaker_chat import get_sagemaker_endpoints

            return get_sagemaker_endpoints()
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    @classmethod
    def get_valid_providers(cls):
        return ["azure", "openai", "bedrock", "anthropic", "sagemaker"]

    @classmethod
    def get_chat_model(cls, config: DictConfig, session_name: str) -> Any:
        """Get a configured chat model instance using LangGraph patterns."""
        provider = config.provider
        model = config.model

        valid_providers = cls.get_valid_providers()
        if provider not in valid_providers:
            raise ValueError(f"Invalid provider: {provider}. Must be one of {valid_providers}")

        skip_model_validation = provider == "openai" and bool(getattr(config, "proxy_url", None))

        if provider != "sagemaker" and not skip_model_validation:
            valid_models = cls.get_valid_models(provider)
            if model not in valid_models:
                if model[3:] not in valid_models:  # TODO: better logic for cross region inference
                    raise ValueError(
                        f"Invalid model: {model} for provider {provider}. All valid models are {valid_models}. If you are using Bedrock, please check if the requested model is available in the provided AWS_DEFAULT_REGION: {os.environ.get('AWS_DEFAULT_REGION')}"
                    )

        if provider == "openai":
            from .openai_chat import create_openai_chat

            return create_openai_chat(config, session_name)
        elif provider == "azure":
            from .azure_openai_chat import create_azure_openai_chat

            return create_azure_openai_chat(config, session_name)
        elif provider == "anthropic":
            from .anthropic_chat import create_anthropic_chat

            return create_anthropic_chat(config, session_name)
        elif provider == "bedrock":
            from .bedrock_chat import create_bedrock_chat

            return create_bedrock_chat(config, session_name)
        elif provider == "sagemaker":
            from .sagemaker_chat import create_sagemaker_chat

            return create_sagemaker_chat(config, session_name)
        else:
            raise ValueError(f"Unsupported provider: {provider}")
