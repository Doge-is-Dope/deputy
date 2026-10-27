"""Map run failures to codes shown by the web UI.

Exception details appear only in the user's copyable report. E-DESKTOP also
identifies live-view failures."""

import anthropic
import openai
from langgraph.errors import GraphRecursionError

from computer_use.computers import ComputerError

# Raised by either model API once its own retries are spent; a timeout is a connection error too.
CONNECTION_ERRORS = (openai.APIConnectionError, anthropic.APIConnectionError)
STATUS_ERRORS = (openai.APIStatusError, anthropic.APIStatusError)


def error_code(error: BaseException) -> str:
    """Why a run failed:

    E-DESKTOP        the desktop could not be seen or used: no display, a screenshot or input that failed, a command
                     that hung
    E-MODEL-KEY      the model API refused the key or the account (401, 403)
    E-MODEL-LIMIT    the model API's rate or usage limit (429)
    E-MODEL-DOWN     the model API could not be reached, timed out, or failed on its side (5xx)
    E-MODEL-REQUEST  the model API rejected the request: too long, an unknown model, an unreadable image (other 4xx)
    E-CALL-LIMIT     the main agent called its model too many times without replying
    E-UNKNOWN        anything else
    """
    if isinstance(error, ComputerError):
        return "E-DESKTOP"
    if isinstance(error, CONNECTION_ERRORS):
        return "E-MODEL-DOWN"
    if isinstance(error, STATUS_ERRORS):
        if error.status_code in (401, 403):
            return "E-MODEL-KEY"
        if error.status_code == 429:
            return "E-MODEL-LIMIT"
        return "E-MODEL-DOWN" if error.status_code >= 500 else "E-MODEL-REQUEST"
    if isinstance(error, GraphRecursionError):
        return "E-CALL-LIMIT"
    return "E-UNKNOWN"
