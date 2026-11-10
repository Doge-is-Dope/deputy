"""The main agent's question to the user: a card in the conversation, which the user's next message answers."""

from typing import Annotated

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from computer_use.prompts import notes
from computer_use.prompts.main import ASK_MULTIPLE, ASK_OPTIONS, ASK_PLACEHOLDER, ASK_QUESTION, ASK_USER_TOOL, OPTION_LABEL, OPTION_REASON

ASK_USER = "ask_user"
MAX_OPTIONS = 4


class Option(BaseModel):
    label: Annotated[str, Field(min_length=1, description=OPTION_LABEL)]
    reason: Annotated[str, Field(min_length=1, description=OPTION_REASON)]


@tool(ASK_USER, description=ASK_USER_TOOL)
def ask_user(
    question: Annotated[str, Field(min_length=1, description=ASK_QUESTION)],
    options: Annotated[list[Option] | None, Field(max_length=MAX_OPTIONS, description=ASK_OPTIONS)] = None,
    multiple: Annotated[bool, Field(description=ASK_MULTIPLE)] = False,
    placeholder: Annotated[str | None, Field(description=ASK_PLACEHOLDER)] = None,
) -> str:
    return notes.ASKED
