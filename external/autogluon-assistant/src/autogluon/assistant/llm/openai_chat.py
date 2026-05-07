import logging
import os
from typing import Any, Dict, List

from langchain_openai import ChatOpenAI
from openai import OpenAI

from .base_chat import BaseAssistantChat

logger = logging.getLogger(__name__)


class AssistantChatOpenAI(ChatOpenAI, BaseAssistantChat):
    """OpenAI chat model with LangGraph support."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.initialize_conversation(self)

    def describe(self) -> Dict[str, Any]:
        base_desc = super().describe()
        return {**base_desc, "model": self.model_name, "proxy": self.openai_proxy}


def get_openai_models() -> List[str]:
    try:
        default_headers = {"User-Agent": os.environ.get("OPENAI_USER_AGENT", "Mozilla/5.0")}
        client = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL"),
            default_headers=default_headers,
        )
        models = client.models.list()
        return [model.id for model in models]
    except Exception as e:
        logger.error(f"Error fetching OpenAI models: {e}")
        return []


def create_openai_chat(config, session_name: str) -> AssistantChatOpenAI:
    """Create an OpenAI chat model instance."""
    model = config.model
    wire_api = getattr(config, "wire_api", "chat_completions")

    if "OPENAI_API_KEY" not in os.environ:
        raise ValueError("OpenAI API key not found in environment")

    if wire_api not in {"chat_completions", "responses"}:
        raise ValueError(f"Unsupported wire_api for OpenAI provider: {wire_api}")

    logger.info(f"Using OpenAI model: {model} for session: {session_name} with wire_api={wire_api}")
    kwargs = {
        "model_name": model,
        "openai_api_key": os.environ["OPENAI_API_KEY"],
        "session_name": session_name,
        "max_tokens": config.max_tokens,
        "default_headers": {"User-Agent": os.environ.get("OPENAI_USER_AGENT", "Mozilla/5.0")},
    }

    request_timeout = os.environ.get("OPENAI_REQUEST_TIMEOUT") or getattr(config, "request_timeout", None)
    if request_timeout is not None:
        kwargs["timeout"] = float(request_timeout)

    if hasattr(config, "temperature"):
        kwargs["temperature"] = config.temperature

    if hasattr(config, "verbose"):
        kwargs["verbose"] = config.verbose

    if hasattr(config, "proxy_url"):
        kwargs["openai_api_base"] = config.proxy_url

    if wire_api == "responses":
        kwargs["use_responses_api"] = True

    return AssistantChatOpenAI(**kwargs)
