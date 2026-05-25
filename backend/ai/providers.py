"""Free AI provider abstraction for the AI Topics feature."""
import subprocess
import httpx
import json


class TokenMissingError(Exception):
    pass

class TokenInvalidError(Exception):
    pass

class RateLimitError(Exception):
    pass

class ClaudeCLINotFoundError(Exception):
    pass


PROVIDER_CONFIG = {
    "anthropic": {
        "default_model": "claude-sonnet-4-6",
        "models": ["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"],
        "requires_key": True,
        "supports_tool_use": True,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "models": ["llama-3.3-70b-versatile", "gemma2-9b-it", "llama-3.1-8b-instant"],
        "requires_key": True,
        "supports_tool_use": False,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "mistralai/mistral-7b-instruct:free",
        "models": [
            "mistralai/mistral-7b-instruct:free",
            "meta-llama/llama-3.2-3b-instruct:free",
            "deepseek/deepseek-r1-distill-qwen-1.5b:free",
            "qwen/qwen-2.5-7b-instruct:free",
        ],
        "requires_key": True,
        "supports_tool_use": False,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-1.5-flash",
        "models": ["gemini-1.5-flash", "gemini-2.0-flash-exp", "gemini-2.0-flash-lite"],
        "requires_key": True,
        "supports_tool_use": False,
    },
    "claude_cli": {
        "requires_key": False,
        "supports_tool_use": False,
    },
}


def get_provider_info():
    """Return provider metadata for the frontend model selector."""
    return PROVIDER_CONFIG


class OpenAICompatProvider:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    def complete(
        self,
        messages: list,
        model: str,
        *,
        system: str = "",
        max_tokens: int = 2048,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}, *msgs]
        payload = {"model": model, "messages": msgs, "max_tokens": max_tokens}
        try:
            with httpx.Client(timeout=120) as client:
                r = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
        except httpx.RequestError as e:
            raise Exception(f"Network error: {e}")

        if r.status_code == 401:
            raise TokenInvalidError()
        if r.status_code == 429:
            raise RateLimitError()
        if r.status_code >= 400:
            raise Exception(f"Provider error {r.status_code}: {r.text[:200]}")

        data = r.json()
        return data["choices"][0]["message"]["content"]


class AnthropicProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def complete(
        self,
        messages: list,
        model: str,
        *,
        system: str = "",
        max_tokens: int = 2048,
    ) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system:
            kwargs["system"] = system
        try:
            response = client.messages.create(**kwargs)
        except anthropic.AuthenticationError:
            raise TokenInvalidError()
        except anthropic.RateLimitError:
            raise RateLimitError()
        return next((b.text for b in response.content if hasattr(b, "text")), "")


class ClaudeCLIProvider:
    def complete(
        self,
        messages: list,
        model: str = None,
        *,
        system: str = "",
        max_tokens: int = 2048,
    ) -> str:
        # Flatten messages into a single prompt
        prompt = "\n\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in messages
        )
        cmd = ["claude", "-p", "--output-format", "text"]
        if system:
            cmd += ["--append-system-prompt", system]
        try:
            result = subprocess.run(
                cmd, input=prompt,
                capture_output=True, text=True, timeout=120
            )
        except FileNotFoundError:
            raise ClaudeCLINotFoundError()
        except subprocess.TimeoutExpired:
            raise Exception("Claude CLI timed out")

        if result.returncode != 0:
            err = result.stderr.strip()
            if "not found" in err.lower() or result.returncode == 127:
                raise ClaudeCLINotFoundError()
            raise Exception(f"Claude CLI error: {err[:200]}")

        return result.stdout.strip()


def get_provider(provider_name: str, api_key: str | None):
    config = PROVIDER_CONFIG.get(provider_name)
    if not config:
        raise Exception(f"Unknown provider: {provider_name}")

    if provider_name == "claude_cli":
        return ClaudeCLIProvider()

    if config.get("requires_key") and not api_key:
        raise TokenMissingError(provider_name)

    if provider_name == "anthropic":
        return AnthropicProvider(api_key=api_key)

    return OpenAICompatProvider(base_url=config["base_url"], api_key=api_key)
