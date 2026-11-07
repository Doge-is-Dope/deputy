"""Skills: the list in each agent's system prompt, the shared ones and its own, and read_skill reading one only from its
folder."""

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from computer_use.agent import coding_agent, computer_agent, main_agent
from computer_use.middleware.skills import SkillsMiddleware, catalog, read_skill_tool
from computer_use.storage import MAIN
from conftest import ScriptedModel, logged, run_turn, tool_call, use_script


def write_skill(folder, name, text):
    (folder / name).mkdir(parents=True)
    (folder / name / "SKILL.md").write_text(text, encoding="utf-8")


def read(tool, call_id="r1", **args) -> ToolMessage:
    return tool.invoke({"type": "tool_call", "id": call_id, "name": "read_skill", "args": args})


def reading(name) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": "s1", "name": "read_skill", "args": {"name": name}, "type": "tool_call"}])


def test_a_skill_is_named_and_described_by_its_frontmatter(tmp_path):
    write_skill(tmp_path, "office", "---\nname: office\ndescription: >\n  Excel and\n  Word.\n---\n\nUse the Name Box.\n")

    (skill,) = catalog(tmp_path)

    assert (skill.name, skill.description, skill.folder) == ("office", "Excel and Word.", tmp_path / "office")


@pytest.mark.parametrize("text", [
    "Use the Name Box.\n",  # no frontmatter
    "---\nname: excel\ndescription: Excel.\n---\n",  # a name other than its folder's
    "---\nname: office\n---\n",  # no description
])
def test_a_skill_without_a_valid_frontmatter_stops_the_runtime(tmp_path, text):
    write_skill(tmp_path, "office", text)

    with pytest.raises(ValueError, match="SKILL.md"):
        catalog(tmp_path)


def skill_text(name):
    return f"---\nname: {name}\ndescription: About {name}.\n---\n\nHow to {name}.\n"


def test_an_agent_is_told_the_shared_skills_and_its_own_by_name_not_another_agents(tmp_path):
    write_skill(tmp_path / "shared", "office", "---\nname: office\ndescription: Excel and Word.\n---\n\nThe Name Box.\n")
    write_skill(tmp_path / "computer", "file-dialogs", skill_text("file-dialogs"))
    write_skill(tmp_path / "coding", "python", skill_text("python"))

    assert SkillsMiddleware("computer", tmp_path).section == (
        "Skills: when your work matches a skill's description, read it with read_skill before acting, and follow it.\n"
        "- file-dialogs: About file-dialogs.\n"
        "- office: Excel and Word."
    )
    (tool,) = SkillsMiddleware("computer", tmp_path).tools
    assert read(tool, name="python").status == "error"


def test_an_agents_skill_named_as_a_shared_one_stops_the_runtime(tmp_path):
    write_skill(tmp_path / "shared", "office", skill_text("office"))
    write_skill(tmp_path / "computer", "office", skill_text("office"))

    with pytest.raises(ValueError, match="must not share a name"):
        SkillsMiddleware("computer", tmp_path)
    assert SkillsMiddleware("coding", tmp_path).section  # the other agents have only the shared one


def test_without_skills_an_agent_gets_no_list_and_no_tool(tmp_path):
    for folder in (tmp_path, tmp_path / "missing"):
        middleware = SkillsMiddleware("computer", folder)
        assert (middleware.section, middleware.tools) == ("", [])


def test_read_skill_reads_the_instructions_and_files_of_the_skill_only(tmp_path):
    write_skill(tmp_path, "office", "---\nname: office\ndescription: Excel.\n---\n\nUse the Name Box.\n")
    (tmp_path / "office" / "references").mkdir()
    (tmp_path / "office" / "references" / "excel.md").write_text("Ranges start at B.", encoding="utf-8")
    (tmp_path / "secret.md").write_text("not a skill's", encoding="utf-8")
    tool = read_skill_tool(catalog(tmp_path))

    assert read(tool, name="office").content == "Use the Name Box."
    assert read(tool, name="office", file="references/excel.md").content == "Ranges start at B."
    for file in ("../secret.md", str(tmp_path / "secret.md"), "references", "missing.md"):
        refused = read(tool, name="office", file=file)
        assert refused.status == "error" and "not a file of skill 'office'" in refused.content
    unknown = read(tool, name="excel")
    assert unknown.status == "error" and "Skills: office." in unknown.content


@pytest.mark.usefixtures("the_log_is_the_whole_record")
async def test_the_computer_agent_is_told_its_skills_and_reads_one(settings, computer, monkeypatch, tmp_path):
    write_skill(tmp_path / "computer", "windows", "---\nname: windows\ndescription: Windows.\n---\n\nUse the Run dialog (win+r).\n")
    monkeypatch.setattr(computer_agent, "SkillsMiddleware", lambda agent: SkillsMiddleware(agent, tmp_path))
    computer_model, _ = use_script(monkeypatch, [
        reading("windows"),
        AIMessage(content="Read it."),
    ])

    result = await run_turn(settings, "open notepad", max_steps=5, computer=computer)

    system = computer_model.received[0][0]
    assert isinstance(system, SystemMessage) and system.text.endswith(SkillsMiddleware("computer", tmp_path).section)
    skill = computer_model.received[1][-1]
    assert isinstance(skill, ToolMessage) and skill.status == "success" and "Run dialog (win+r)" in skill.text
    (action,) = logged(result, "action")
    assert (action["tool"], action["args"], action["status"]) == ("read_skill", {"name": "windows"}, "success")
    assert computer.calls == []  # read on the runtime, nothing sent to the desktop


@pytest.mark.usefixtures("the_log_is_the_whole_record")
async def test_the_main_agent_is_told_its_skills_and_reads_one(settings, computer, monkeypatch, tmp_path):
    write_skill(tmp_path / "main", "planning", skill_text("planning"))
    monkeypatch.setattr(main_agent, "SkillsMiddleware", lambda agent: SkillsMiddleware(agent, tmp_path))
    _, main_model = use_script(monkeypatch, [], main=[
        reading("planning"),
        AIMessage("Planned."),
    ])

    result = await run_turn(settings, "plan it", max_steps=5, computer=computer)

    assert result.reply == "Planned."
    assert "- planning: About planning." in main_model.received[0][0].text
    skill = main_model.received[1][-1]
    assert isinstance(skill, ToolMessage) and skill.status == "success" and "How to planning." in skill.text
    assert [(action["tool"], action["status"]) for action in logged(result, "action", MAIN)] == [("read_skill", "success")]


@pytest.mark.usefixtures("the_log_is_the_whole_record")
async def test_the_coding_agent_is_told_its_skills_and_reads_one(settings, computer, code_runner, monkeypatch, tmp_path):
    write_skill(tmp_path / "coding", "python", skill_text("python"))
    monkeypatch.setattr(coding_agent, "SkillsMiddleware", lambda agent: SkillsMiddleware(agent, tmp_path))
    coding_model = ScriptedModel(messages=iter([
        reading("python"),
        AIMessage("Read it."),
    ]), received=[], bindings=[])
    monkeypatch.setattr(coding_agent, "build_chat_model", lambda _spec, _settings: coding_model)
    use_script(monkeypatch, [], main=[
        AIMessage(content="", tool_calls=[tool_call("m1", "start_task", agent="coding", title="Task", task="Use Python.")]),
        AIMessage("Done."),
    ])

    await run_turn(settings, "use python", max_steps=5, computer=computer, code_runner=code_runner)

    assert "- python: About python." in coding_model.received[0][0].text
    skill = coding_model.received[1][-1]
    assert isinstance(skill, ToolMessage) and skill.status == "success" and "How to python." in skill.text
