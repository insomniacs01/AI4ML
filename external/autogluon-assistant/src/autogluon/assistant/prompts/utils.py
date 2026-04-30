import logging

logger = logging.getLogger(__name__)

SHELL_LANGUAGES = {"bash", "sh", "shell", "powershell", "ps1", "pwsh"}
PYTHON_LANGUAGES = {"python", "py"}


def _normalize_response(response):
    if response is None:
        return ""
    return str(response).replace("\r\n", "\n").replace("\r", "\n")


def _iter_fenced_code_blocks(response):
    normalized = _normalize_response(response)
    cursor = 0

    while True:
        start = normalized.find("```", cursor)
        if start == -1:
            return

        line_end = normalized.find("\n", start + 3)
        if line_end == -1:
            return

        label = normalized[start + 3 : line_end].strip().lower()
        body_start = line_end + 1
        end = normalized.find("```", body_start)
        if end == -1:
            yield label, normalized[body_start:].strip(), True
            return

        yield label, normalized[body_start:end].strip(), False
        cursor = end + 3


def _extract_fenced_code_block(response, languages):
    requested = {language.lower() for language in languages}
    for label, body, _unterminated in _iter_fenced_code_blocks(response):
        if label in requested and body:
            return body
    return None


def _extract_python_script(response):
    return _extract_fenced_code_block(response, list(PYTHON_LANGUAGES))


def _extract_bash_script(response):
    return _extract_fenced_code_block(response, list(SHELL_LANGUAGES))


def _extract_generic_fenced_code(response, language):
    for label, body, _unterminated in _iter_fenced_code_blocks(response):
        if not body:
            continue
        if language == "python" and label in SHELL_LANGUAGES:
            logger.warning("Skipping shell code block while extracting python code")
            continue
        if language == "bash" and label in PYTHON_LANGUAGES:
            logger.warning("Skipping python code block while extracting shell code")
            continue
        return body
    return None


def extract_code(response, language):
    response_text = _normalize_response(response)
    result = None

    if language == "python":
        result = _extract_python_script(response_text)
    elif language == "bash":
        result = _extract_bash_script(response_text)
    else:
        raise ValueError(f"Unsupported language: {language}")

    if result is None:
        logger.warning(f"No code block found for {language}, looking for the code wrapped without language specified")
        result = _extract_generic_fenced_code(response_text, language)

    if result is None:
        logger.warning(f"No code block found, return the full response instead: {response_text}")
        result = response_text

    return result
