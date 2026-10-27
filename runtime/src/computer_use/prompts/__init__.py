"""Everything the runtime tells its agents in its own words: their system prompts, what the main agent is told of each
agent it hands work to, and the runtime's notes, refusals and reports in their conversations.

The eval names a version's prompts by this folder's contents (eval/html_report.py PROMPTS), so wording is changed here:
each module holds text, and functions that only put text together. What tools are (their names, docstrings and
arguments) stays with the tools, and what the desktop and the code runner say of an action stays with them."""
