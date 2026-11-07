import anthropic
import httpx
import openai
import pytest
from langgraph.errors import GraphRecursionError

from computer_use.agent.failures import error_code, failed_in_stream
from computer_use.computers import ComputerError

REQUEST = httpx.Request("POST", "https://api.invalid/v1/responses")


def status_error(sdk, status: int) -> Exception:
    return sdk.APIStatusError("refused", response=httpx.Response(status, request=REQUEST), body=None)


@pytest.mark.parametrize("sdk", [openai, anthropic])
@pytest.mark.parametrize(("status", "code"), [
    (401, "E-MODEL-KEY"),
    (403, "E-MODEL-KEY"),
    (429, "E-MODEL-LIMIT"),
    (400, "E-MODEL-REQUEST"),
    (404, "E-MODEL-REQUEST"),
    (500, "E-MODEL-DOWN"),
    (529, "E-MODEL-DOWN"),
])
def test_a_model_api_error_is_coded_by_its_status(sdk, status, code):
    assert error_code(status_error(sdk, status)) == code


@pytest.mark.parametrize("sdk", [openai, anthropic])
def test_a_model_api_that_cannot_be_reached_or_times_out_is_down(sdk):
    assert error_code(sdk.APIConnectionError(request=REQUEST)) == "E-MODEL-DOWN"
    assert error_code(sdk.APITimeoutError(request=REQUEST)) == "E-MODEL-DOWN"


# An error the model API sends in a stream it has opened (HTTP 200), as each SDK raises it: OpenAI's a bare APIError
# with the error object as its body, Anthropic's a status error with status 200 and the whole event as its body.
def stream_error(sdk, kind: str) -> Exception:
    error = {"type": kind, "message": "from the stream"}
    if sdk is openai:
        return openai.APIError("from the stream", REQUEST, body=error)
    response = httpx.Response(200, request=REQUEST)
    return anthropic.APIStatusError("from the stream", response=response, body={"type": "error", "error": error})


@pytest.mark.parametrize(("sdk", "kind", "code"), [
    (openai, "server_error", "E-MODEL-DOWN"),
    (anthropic, "overloaded_error", "E-MODEL-DOWN"),
    (anthropic, "api_error", "E-MODEL-DOWN"),
    (openai, "rate_limit_exceeded", "E-MODEL-LIMIT"),
    (anthropic, "rate_limit_error", "E-MODEL-LIMIT"),
    (openai, "invalid_request_error", "E-MODEL-REQUEST"),
    (anthropic, "invalid_request_error", "E-MODEL-REQUEST"),
])
def test_an_error_in_an_open_stream_is_coded_by_its_type(sdk, kind, code):
    assert error_code(stream_error(sdk, kind)) == code


def test_the_desktop_the_call_limit_and_anything_else():
    assert error_code(ComputerError("screenshot failed: X connection failed: error 1")) == "E-DESKTOP"
    assert error_code(GraphRecursionError("Recursion limit of 70 reached")) == "E-CALL-LIMIT"
    assert error_code(ValueError("something else")) == "E-UNKNOWN"


@pytest.mark.parametrize("sdk", [openai, anthropic])
def test_only_a_stream_that_failed_on_the_apis_side_is_worth_another_try(sdk):
    # What the SDK retries itself (a failing status, no connection) or what would fail again is not.
    assert failed_in_stream(stream_error(sdk, "server_error"))
    assert failed_in_stream(stream_error(sdk, "overloaded_error"))
    assert failed_in_stream(stream_error(sdk, "rate_limit_error"))
    assert not failed_in_stream(stream_error(sdk, "invalid_request_error"))
    assert not failed_in_stream(status_error(sdk, 500))
    assert not failed_in_stream(sdk.APIConnectionError(request=REQUEST))
    assert not failed_in_stream(ValueError("not the model API"))
