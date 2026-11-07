"""The coding agent's tools: bash and write_file in the conversation's folder on the code runner."""

from typing import Annotated

from langchain_core.tools import BaseTool, ToolException, tool
from pydantic import Field

from computer_use.sandbox import CodeRunner

RUN_SECONDS = 120


def coding_tools(runner: CodeRunner, thread: str, task: str) -> list[BaseTool]:
    """bash and write_file for a task (its log's id), in the conversation's folder on the code runner."""

    @tool
    async def bash(
        script: Annotated[str, Field(description="The commands, run with bash in your working folder.")],
    ) -> str:
        """Run commands with bash in your working folder; returns the exit code and what they printed, stdout and
        stderr together, cut in the middle when long."""
        try:
            output = await runner.run(thread, task, script, RUN_SECONDS)
        except ValueError as refused:
            raise ToolException(f"Not executed: {refused}.")
        if output.code is None:
            raise ToolException(f"Stopped: it ran for more than {RUN_SECONDS} seconds. What it printed:\n{output.text}")
        return f"Exit code {output.code}.\n{output.text}"

    @tool
    async def write_file(
        path: Annotated[str, Field(description="A path in your working folder.")],
        content: Annotated[str, Field(description="The file's whole text.")],
    ) -> str:
        """Write a text file in your working folder, replacing any there."""
        try:
            return await runner.write(thread, path, content)
        except ValueError as refused:
            raise ToolException(f"Not executed: {refused}.")

    tools = [bash, write_file]
    for each in tools:  # a refused or failed command is the agent's to hear and work around
        each.handle_tool_error = True
    return tools
