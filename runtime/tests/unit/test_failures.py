import anthropic
import httpx
import openai
import pytest
from langgraph.errors import GraphRecursionError

from computer_use.agent.failures import error_code
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


def test_the_desktop_the_call_limit_and_anything_else():
    assert error_code(ComputerError("screenshot failed: X connection failed: error 1")) == "E-DESKTOP"
    assert error_code(GraphRecursionError("Recursion limit of 70 reached")) == "E-CALL-LIMIT"
    assert error_code(ValueError("something else")) == "E-UNKNOWN"
