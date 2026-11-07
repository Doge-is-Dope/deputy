"""Map run failures to codes shown by the web UI; exception details appear only in the user's copyable report."""

import anthropic
import openai
from langgraph.errors import GraphRecursionError

# Raised by either model API once its own retries are spent; a timeout is a connection error too.
CONNECTION_ERRORS = (openai.APIConnectionError, anthropic.APIConnectionError)
STATUS_ERRORS = (openai.APIStatusError, anthropic.APIStatusError)
# Any other error either model API raised: one it sent in a stream it had opened, which has no failing status.
API_ERRORS = (openai.APIError, anthropic.APIError)


def streamed_type(error: openai.APIError | anthropic.APIError) -> str:
    """The type a model API gave an error it sent in an open stream: OpenAI's body is the error itself, Anthropic's
    the event that holds it."""
    body = error.body if isinstance(error.body, dict) else {}
    inner = body.get("error")
    return str((inner if isinstance(inner, dict) else body).get("type") or "")


def failed_in_stream(error: BaseException) -> bool:
    """Whether a model call is worth another try: the API failed on its side in a stream it had opened (overloaded,
    an error of its own, a rate limit). The SDK retries a failing status or connection itself; it cannot retry a
    stream already under way. A request it rejected would fail again."""
    if isinstance(error, CONNECTION_ERRORS) or (isinstance(error, STATUS_ERRORS) and error.status_code >= 400):
        return False
    return isinstance(error, API_ERRORS) and streamed_type(error) != "invalid_request_error"


def error_code(error: BaseException) -> str:
    """Why a run failed:

    E-DESKTOP        the desktop could not be seen or used: no display, a screenshot or input that failed, a command
                     that hung
    E-MODEL-KEY      the model API refused the key or the account (401, 403)
    E-MODEL-LIMIT    the model API's rate or usage limit (429)
    E-MODEL-DOWN     the model API could not be reached, timed out, or failed on its side (5xx, or overloaded or
                     failing in a stream it had opened)
    E-MODEL-REQUEST  the model API rejected the request: too long, an unknown model, an unreadable image (other 4xx)
    E-CALL-LIMIT     the main agent called its model too many times without replying
    E-UNKNOWN        anything else

    An error the model API sent in a stream it had opened has no failing status: its type says which it is. An error
    of the runtime's own says its code itself (`failure_code`).
    """
    if code := getattr(error, "failure_code", None):
        return code
    if isinstance(error, CONNECTION_ERRORS):
        return "E-MODEL-DOWN"
    if isinstance(error, STATUS_ERRORS) and error.status_code >= 400:
        if error.status_code in (401, 403):
            return "E-MODEL-KEY"
        if error.status_code == 429:
            return "E-MODEL-LIMIT"
        return "E-MODEL-DOWN" if error.status_code >= 500 else "E-MODEL-REQUEST"
    if isinstance(error, API_ERRORS):
        kind = streamed_type(error)
        if kind.startswith("rate_limit"):
            return "E-MODEL-LIMIT"
        return "E-MODEL-REQUEST" if kind == "invalid_request_error" else "E-MODEL-DOWN"
    if isinstance(error, GraphRecursionError):
        return "E-CALL-LIMIT"
    return "E-UNKNOWN"
