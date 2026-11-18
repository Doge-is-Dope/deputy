import base64
import io
from datetime import date, timedelta

import pytest
import pypdfium2

from langchain_core.messages import HumanMessage

from computer_use.agent.models import AgentChatAnthropic, FullResolutionChatOpenAI
from computer_use.attachments import (
    KEPT_DAYS, MAX_BYTES, MAX_FILES, MAX_KEPT, MAX_NAME, MAX_PAGES, MAX_SHOWN, MAX_SIDE, STALE_DAYS, Uploads, checked,
)
from computer_use.files import upload_key
from computer_use.files.local import LocalFileStore
from computer_use.tools.common import extension_of, for_model
from conftest import image


def pdf(pages: int) -> bytes:
    document = pypdfium2.PdfDocument.new()
    for _ in range(pages):
        document.new_page(612, 792)
    out = io.BytesIO()
    document.save(out)
    document.close()
    return out.getvalue()


PDF = pdf(1)
TODAY = date(2026, 11, 12)


def test_a_file_goes_once_its_type_and_size_are_right_and_keeps_its_name_without_its_folder():
    assert checked("scans\\收據.jpg", "image/jpeg", image("JPEG")) == "收據.jpg"
    assert checked("shots/screen.png", "image/png", image("PNG")) == "screen.png"
    assert checked("logo.webp", "image/webp", image("WEBP", (MAX_SIDE, 10))) == "logo.webp"
    assert checked("報價\x07單.pdf", "application/pdf", PDF) == "報價單.pdf"
    long = checked("報" * 300 + ".xlsx", "application/octet-stream", b"x")  # cut to fit a folder, its kind kept
    assert len(long.encode()) <= MAX_NAME and long.endswith("報.xlsx")


@pytest.mark.parametrize("name, mime_type, data, why", [
    ("a.jpg", "image/jpeg", image("PNG"), "a.jpg is not a JPEG image"),
    ("wide.png", "image/png", image("PNG", (MAX_SIDE + 1, 1)), "over 2048 pixels"),
    ("a.pdf", "application/pdf", image("PNG"), "a.pdf is not a PDF"),
    ("big.pdf", "application/pdf", PDF + b"0" * MAX_BYTES, "over 5 MB"),
    ("big.zip", "application/zip", b"0" * (MAX_KEPT + 1), "over 20 MB"),
    ("\x01", "application/pdf", PDF, "needs a name"),
])
def test_what_cannot_go_is_turned_away_saying_why(name, mime_type, data, why):
    with pytest.raises(ValueError, match=why):
        checked(name, mime_type, data)


async def test_an_upload_waits_until_a_message_takes_it_as_a_block_named_by_its_file(tmp_path):
    uploads = Uploads(LocalFileStore(tmp_path))
    photo = image("JPEG")

    ids = [await uploads.put("me", "收據.jpg", "image/jpeg", photo, TODAY),
           await uploads.put("me", "報價單.pdf", "application/pdf", PDF, TODAY)]
    blocks = await uploads.blocks("me", ids, coding=False)

    assert blocks == [
        {"type": "text", "text": "收據.jpg:"},
        {"type": "image", "base64": base64.b64encode(photo).decode(), "mime_type": "image/jpeg", "filename": "收據.jpg"},
        {"type": "text", "text": "報價單.pdf:"},
        {"type": "file", "base64": base64.b64encode(PDF).decode(), "mime_type": "application/pdf", "filename": "報價單.pdf"},
    ]
    with pytest.raises(ValueError, match="no such upload"):  # one user's upload is not another's
        await uploads.blocks("you", ids[:1], coding=False)
    await uploads.delete("me", ids)
    with pytest.raises(ValueError, match="no such upload"):
        await uploads.blocks("me", ids[:1], coding=False)


@pytest.mark.parametrize("ids, why", [
    (["20261112-" + "0" * 32], "no such upload"),
    (["../../runs/x"], "no such upload"),
    ("20261112-" + "0" * 32, "must be a list"),
    (["20261112-" + "0" * 32] * (MAX_FILES + 1), "at most 5"),
])
async def test_a_message_names_only_uploads_that_are_there(tmp_path, ids, why):
    with pytest.raises(ValueError, match=why):
        await Uploads(LocalFileStore(tmp_path)).blocks("me", ids, coding=False)


async def test_the_days_first_upload_erases_those_no_message_took(tmp_path):
    files = LocalFileStore(tmp_path)
    uploads = Uploads(files)
    days = {age: await uploads.put("me", "a.pdf", "application/pdf", PDF, TODAY - timedelta(days=age))
            for age in (KEPT_DAYS, STALE_DAYS, STALE_DAYS - 1)}

    await uploads.put("me", "b.pdf", "application/pdf", PDF, TODAY)

    assert await uploads.blocks("me", [days[STALE_DAYS - 1]], coding=False)  # yesterday's may still be sent
    for age in (STALE_DAYS, KEPT_DAYS):
        with pytest.raises(ValueError, match="no such upload"):
            await uploads.blocks("me", [days[age]], coding=False)
    assert not (tmp_path / upload_key("me", (TODAY - timedelta(days=STALE_DAYS)).strftime("%Y%m%d"))).exists()


async def test_any_file_goes_with_a_coding_agent_and_the_model_is_told_where_it_is(tmp_path):
    uploads = Uploads(LocalFileStore(tmp_path))
    table, sheet = "a,b\n1,2\n".encode(), b"PK\x03\x04" + bytes(range(256))
    ids = [await uploads.put("me", "data.csv", "text/csv", table, TODAY),
           await uploads.put("me", "報表.xlsx", "", sheet, TODAY),
           await uploads.put("me", "報表.xlsx", "", sheet, TODAY),
           await uploads.put("me", "a.pdf", "application/pdf", PDF, TODAY)]

    blocks = await uploads.blocks("me", ids, coding=True)

    kinds = [(block["type"], block.get("filename")) for block in blocks]
    assert kinds == [
        ("text", None), ("file", "data.csv"), ("text", None), ("file", "報表.xlsx"), ("text", None),
        ("file", "報表 (2).xlsx"), ("text", None), ("file", "a.pdf"), ("text", None),
    ]
    assert blocks[3]["mime_type"] == "application/octet-stream"
    # A short text file is shown whole; one that is not text is only said to be there.
    assert "attachments/data.csv" in blocks[0]["text"] and "a,b\n1,2" in blocks[0]["text"]
    assert "attachments/報表.xlsx" in blocks[2]["text"] and "PK" not in blocks[2]["text"]
    assert blocks[6]["text"] == "a.pdf:"
    assert blocks[8]["text"] == "The attached files are also in the coding agent's working folder, under attachments/."
    # The model gets the text, the PDF and the note of each file, never a file only code opens.
    model = for_model(HumanMessage(content=blocks)).content
    assert [block.get("filename") for block in model if block["type"] == "file"] == ["a.pdf"]
    assert [extension_of(block) for block in blocks if block["type"] == "file"] == ["csv", "xlsx", "xlsx", "pdf"]


async def test_a_pdf_too_large_for_the_model_goes_to_the_coding_agent_only(tmp_path):
    uploads = Uploads(LocalFileStore(tmp_path))
    long = await uploads.put("me", "年報.pdf", "application/pdf", PDF + b"0" * MAX_BYTES, TODAY)

    blocks = await uploads.blocks("me", [long], coding=True)

    assert "attachments/年報.pdf" in blocks[0]["text"]
    assert blocks[1]["mime_type"] == "application/octet-stream" and extension_of(blocks[1]) == "pdf"
    assert [block["type"] for block in for_model(HumanMessage(content=blocks)).content] == ["text", "text"]
    with pytest.raises(ValueError, match="only by the coding agent"):
        await uploads.blocks("me", [long], coding=False)


@pytest.mark.parametrize("pages, kept", [(1, False), (MAX_PAGES, False), (MAX_PAGES + 1, True)])
async def test_a_pdf_of_more_pages_than_a_model_takes_goes_to_the_coding_agent_only(tmp_path, pages, kept):
    uploads = Uploads(LocalFileStore(tmp_path))
    upload = await uploads.put("me", "手冊.pdf", "application/pdf", pdf(pages), TODAY)
    block = (await uploads.blocks("me", [upload], coding=True))[1]
    assert (block["mime_type"] == "application/octet-stream") is kept and extension_of(block) == "pdf"


async def test_a_pdf_that_does_not_open_goes_to_the_coding_agent_only(tmp_path):
    uploads = Uploads(LocalFileStore(tmp_path))
    upload = await uploads.put("me", "壞掉.pdf", "application/pdf", b"%PDF-1.7\nno pages, no trailer", TODAY)
    assert (await uploads.blocks("me", [upload], coding=True))[1]["mime_type"] == "application/octet-stream"


async def test_a_long_text_file_is_only_said_to_be_there_and_without_a_coding_agent_it_cannot_go(tmp_path):
    uploads = Uploads(LocalFileStore(tmp_path))
    long = await uploads.put("me", "app.log", "text/plain", b"x" * (MAX_SHOWN + 1), TODAY)
    told = (await uploads.blocks("me", [long], coding=True))[0]["text"]
    assert "attachments/app.log" in told and "xxx" not in told
    with pytest.raises(ValueError, match="only by the coding agent"):
        await uploads.blocks("me", [long], coding=False)


@pytest.mark.parametrize("coding", [True, False])
async def test_each_picture_reaches_either_model_named_just_ahead_of_it(tmp_path, coding):
    # No provider takes a file name in an image block: the model goes by the text before each picture.
    uploads = Uploads(LocalFileStore(tmp_path))
    ids = [await uploads.put("me", name, "image/png", image("PNG"), TODAY) for name in ("a.png", "b.png", "c.png")]
    message = HumanMessage(content=[
        {"type": "text", "text": "b.png: what is this?"}, *await uploads.blocks("me", ids, coding=coding),
    ])
    openai = FullResolutionChatOpenAI(model="gpt-6-luna", use_responses_api=True, api_key="x")
    anthropic = AgentChatAnthropic(model="claude-sonnet-5-5", api_key="x", max_tokens=100)
    sent = {
        "input_image": openai._get_request_payload([message])["input"][0]["content"],
        "image": anthropic._get_request_payload([message])["messages"][0]["content"],
    }

    for kind, content in sent.items():
        ahead = [content[index - 1]["text"] for index, block in enumerate(content) if block["type"] == kind]
        assert [text.split(" ")[0].rstrip(":") for text in ahead] == ["a.png", "b.png", "c.png"]
