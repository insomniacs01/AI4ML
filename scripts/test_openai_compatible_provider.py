from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test an OpenAI-compatible provider by checking /models and sending a tiny inference request."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("AI4ML_MLZERO_PROVIDER_BASE_URL_OVERRIDE") or os.getenv("AI4ML_PROVIDER_BASE_URL"),
        help="OpenAI-compatible provider base URL, e.g. https://api.siliconflow.cn/v1",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("AI4ML_MLZERO_OPENAI_API_KEY") or os.getenv("AI4ML_PROVIDER_API_KEY"),
        help="Provider API key. Prefer passing it through env vars instead of shell history.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("AI4ML_MLZERO_MODEL_ALIAS") or os.getenv("AI4ML_PROVIDER_MODEL"),
        help="Model id to test.",
    )
    parser.add_argument(
        "--wire-api",
        choices=["chat_completions", "responses"],
        default=os.getenv("AI4ML_MLZERO_PROVIDER_WIRE_API")
        or os.getenv("AI4ML_PROVIDER_WIRE_API")
        or "chat_completions",
        help="Which inference endpoint to test.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--skip-chat",
        action="store_true",
        help="Only test /models and skip the chat completion call.",
    )
    return parser.parse_args()


def request_json(url: str, *, headers: dict[str, str], body: dict | None, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    args = parse_args()

    if not args.base_url:
        print("ERROR: base URL is required.", file=sys.stderr)
        return 2
    if not args.api_key:
        print("ERROR: API key is required.", file=sys.stderr)
        return 2
    if not args.model:
        print("ERROR: model id is required.", file=sys.stderr)
        return 2
    if args.model.startswith("Pro/"):
        print(f"ERROR: Pro model is blocked by project policy: {args.model}", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {args.api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }

    print(f"Testing provider base URL: {base_url}")
    print(f"Testing model: {args.model}")

    try:
        models_payload = request_json(
            f"{base_url}/models",
            headers={
                "Authorization": headers["Authorization"],
                "User-Agent": headers["User-Agent"],
            },
            body=None,
            timeout=args.timeout,
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"ERROR: /models returned HTTP {exc.code}: {body}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: /models request failed: {exc}", file=sys.stderr)
        return 1

    model_ids = [item.get("id", "") for item in models_payload.get("data", []) if isinstance(item, dict)]
    if args.model not in model_ids:
        print(
            f"ERROR: model is not listed by provider: {args.model}",
            file=sys.stderr,
        )
        return 1

    print("PASS: /models is reachable and the configured model is listed.")

    if args.skip_chat:
        print("Inference test skipped.")
        return 0

    if args.wire_api == "responses":
        inference_payload = {
            "model": args.model,
            "input": "Reply with exactly: openai-compatible-ok",
        }
        endpoint = "/responses"
    else:
        inference_payload = {
            "model": args.model,
            "messages": [{"role": "user", "content": "Reply with exactly: openai-compatible-ok"}],
            "max_tokens": 16,
            "temperature": 0,
        }
        endpoint = "/chat/completions"

    try:
        inference_response = request_json(
            f"{base_url}{endpoint}",
            headers=headers,
            body=inference_payload,
            timeout=args.timeout,
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"ERROR: {endpoint} returned HTTP {exc.code}: {body}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {endpoint} request failed: {exc}", file=sys.stderr)
        return 1

    if args.wire_api == "responses":
        content = (
            inference_response.get("output", [{}])[0]
            .get("content", [{}])[0]
            .get("text", "")
            .strip()
        )
    else:
        content = (
            inference_response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

    print(f"PASS: {endpoint} succeeded.")
    print(f"Model reply: {content}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
