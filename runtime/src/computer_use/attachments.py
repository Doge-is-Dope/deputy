"""What the user attaches to a message: each file is uploaded first and waits in the file store until a message names
it, which turns it into content blocks. An image or a PDF goes to the model as it is; any other file, and a PDF too large
for a model, only code opens, so the model is told of it instead, a short text one shown whole. With a coding agent,
every file is also in its working folder (tools.coding). The page sends each image already shrunk to MAX_SIDE, so only
headers are read here, and a PDF's count of pages: nothing is decoded."""

import base64
import io
import json
import re
import uuid
from datetime import date, timedelta

import pypdfium2
from PIL import Image

from computer_use.files import FileStore, upload_key
from computer_use.tools.coding import ATTACHED
from computer_use.tools.common import EXTENSION, MEDIA_TYPES

MAX_FILES = 5
# An image or a PDF, which goes to the model: a model API takes an image of up to 10 MB of base64 (Anthropic).
MAX_BYTES = 5 * 1024 * 1024
# Pages of a PDF that goes to the model, each 1,500 to 3,000 tokens: Anthropic takes 100 to a request whose context is
# under 1M tokens, 600 above.
MAX_PAGES = 100
# Any other file, which only code opens.
MAX_KEPT = 20 * 1024 * 1024
MAX_SIDE = 2048
MAX_NAME = 240  # bytes of a file's name
# A text file this short is shown to the model whole, besides being in the folder.
MAX_SHOWN = 100 * 1024
ANY = "application/octet-stream"
PDF = "application/pdf"
IMAGE_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
UPLOAD_ID = re.compile(r"(\d{8})-([0-9a-f]{32})")
# An upload no message took is erased once this many days old; days further back than KEPT_DAYS are never looked at.
STALE_DAYS, KEPT_DAYS = 2, 30


def checked(name: str, mime_type: str, data: bytes) -> str:
    """The file's name as shown, once its type and size are right; ValueError saying why it cannot go."""
    name = shortened(CONTROL.sub("", name.replace("\\", "/").rsplit("/", 1)[-1]).strip())
    if not name or name in (".", ".."):
        raise ValueError("a file needs a name")
    if mime_type not in MEDIA_TYPES:
        if len(data) > MAX_KEPT:
            raise ValueError(f"{name} is over {MAX_KEPT // 2**20} MB")
        return name
    if len(data) > MAX_BYTES:
        raise ValueError(f"{name} is over {MAX_BYTES // 2**20} MB")
    if mime_type == PDF:
        if not data.startswith(b"%PDF-"):
            raise ValueError(f"{name} is not a PDF")
        return name
    try:
        with Image.open(io.BytesIO(data), formats=(IMAGE_FORMATS[mime_type],)) as image:
            size = image.size
    except (OSError, Image.DecompressionBombError):
        raise ValueError(f"{name} is not a {IMAGE_FORMATS[mime_type]} image") from None
    if max(size) > MAX_SIDE:
        raise ValueError(f"{name} is over {MAX_SIDE} pixels on its long side")
    return name


class Uploads:
    """Uploaded files waiting for a message, by user. Each sits in a folder of its own under its day, so a taken one
    and the stale ones are erased by prefix."""

    def __init__(self, files: FileStore):
        self.files = files
        self.swept: dict[str, date] = {}  # the day each user's stale uploads were last erased

    async def put(self, user: str, name: str, mime_type: str, data: bytes, today: date | None = None) -> str:
        """Keeps a checked file and returns its id; ValueError if it cannot go. The day's first upload erases stale ones."""
        # A PDF too large for the model is a file like any: the coding agent reads the pages it needs.
        mime_type = ANY if not mime_type or (mime_type == PDF and not model_reads(data)) else mime_type
        name = checked(name, mime_type, data)
        today = today or date.today()
        day, upload = today.strftime("%Y%m%d"), uuid.uuid4().hex
        meta = json.dumps({"name": name, "mime_type": mime_type}).encode()
        await self.files.put(upload_key(user, day, upload, "meta.json"), meta)
        await self.files.put(upload_key(user, day, upload, "data"), data)
        await self.sweep(user, today)
        return f"{day}-{upload}"

    async def blocks(self, user: str, ids, coding: bool) -> list[dict]:
        """The content blocks of the uploads a message names, each file named by its `filename`, unique in the
        message, and by a text ahead of it for the model, which reads no block's file name; ValueError if one is not
        there or cannot go. With a `coding` agent each file is also in its folder, under ATTACHED, and the model is
        told so; without one, a file only code opens cannot go."""
        if not isinstance(ids, list) or len(ids) > MAX_FILES or not all(isinstance(each, str) for each in ids):
            raise ValueError(f"attachments must be a list of at most {MAX_FILES} upload ids")
        blocks, names = [], set()
        for each in ids:
            if not (found := UPLOAD_ID.fullmatch(each)):
                raise ValueError(f"no such upload: {each}")
            try:
                meta = json.loads(await self.files.get(upload_key(user, *found.groups(), "meta.json")))
                data = await self.files.get(upload_key(user, *found.groups(), "data"))
            except FileNotFoundError:
                raise ValueError(f"no such upload: {each}") from None
            mime_type = meta["mime_type"]
            name = unique(meta["name"], names)  # checked when it was kept
            readable = mime_type in MEDIA_TYPES
            if not readable and not coding:
                raise ValueError(f"{name} can be opened only by the coding agent, which this runtime does not have")
            # Ahead of it: a name after a file reads as the next one's.
            blocks.append({"type": "text", "text": told_of(name, data, readable, coding)})
            blocks.append({
                "type": "image" if mime_type.startswith("image/") and readable else "file",
                "base64": base64.b64encode(data).decode(), "mime_type": mime_type, "filename": name,
            })
        if coding and blocks:
            # Once for them all: a label ahead of a picture that also says where it is reads less as its name.
            folder = f"The attached files are also in the coding agent's working folder, under {ATTACHED}/."
            blocks.append({"type": "text", "text": folder})
        return blocks

    async def get(self, user: str, upload_id: str) -> tuple[str, bytes]:
        """An upload's type and bytes, for the user to look at before it goes; FileNotFoundError if there is none."""
        if not (found := UPLOAD_ID.fullmatch(upload_id)):
            raise FileNotFoundError(upload_id)
        meta = json.loads(await self.files.get(upload_key(user, *found.groups(), "meta.json")))
        return meta["mime_type"], await self.files.get(upload_key(user, *found.groups(), "data"))

    async def delete(self, user: str, ids) -> None:
        """Erases uploads a message took: the run keeps its own copies."""
        for each in ids:
            if found := UPLOAD_ID.fullmatch(each):
                await self.files.delete_prefix(upload_key(user, *found.groups()))

    async def sweep(self, user: str, today: date) -> None:
        """Erases the folders of the user's days whose uploads are stale, as far back as KEPT_DAYS; once a day."""
        if self.swept.get(user) == today:
            return
        for days in range(STALE_DAYS, KEPT_DAYS + 1):
            await self.files.delete_prefix(upload_key(user, (today - timedelta(days=days)).strftime("%Y%m%d")))
        self.swept[user] = today


def model_reads(pdf: bytes) -> bool:
    """Whether a model takes the PDF whole: at most MAX_BYTES and MAX_PAGES, and one that opens without a password."""
    if len(pdf) > MAX_BYTES:
        return False
    if not pdf.startswith(b"%PDF-"):  # no PDF at all, which checked() turns away
        return True
    try:
        document = pypdfium2.PdfDocument(pdf)
    except pypdfium2.PdfiumError:
        return False
    try:
        return len(document) <= MAX_PAGES
    finally:
        document.close()


def shortened(name: str) -> str:
    """The name cut to MAX_NAME bytes, its extension kept: a folder takes a name of up to 255 bytes, and unique() may
    add a number."""
    if len(name.encode()) <= MAX_NAME:
        return name
    extension = found[0] if (found := EXTENSION.search(name)) else ""
    stem = name[: len(name) - len(extension)].encode()[: MAX_NAME - len(extension)]
    return stem.decode(errors="ignore").rstrip() + extension


def unique(name: str, taken: set[str]) -> str:
    """The name, numbered when the message has a file of that name already: report.xlsx, report (2).xlsx."""
    stem, dot, extension = name.rpartition(".")
    stem, dot = (stem, dot) if stem else (name, "")
    number, chosen = 1, name
    while chosen in taken:
        number += 1
        chosen = f"{stem} ({number}){dot}{extension if dot else ''}"
    taken.add(chosen)
    return chosen


def told_of(name: str, data: bytes, readable: bool, coding: bool) -> str:
    """What the model is told of a file ahead of its block: its name, and for one it cannot read itself, that it was
    attached, where the coding agent finds it, and its text when that is short."""
    if readable:
        return f"{name}:"
    where = f"It is in the coding agent's working folder as {ATTACHED}/{name}." if coding else ""
    told = f"The user attached {name} ({size(len(data))}). {where}"
    if len(data) <= MAX_SHOWN and (text := as_text(data)) is not None:
        told += f" It reads:\n<file name=\"{name}\">\n{text}\n</file>"
    return told


def as_text(data: bytes) -> str | None:
    """The file as text, when it is UTF-8 with no NUL; None for anything else."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if "\x00" in text else text


def size(count: int) -> str:
    return f"{count} bytes" if count < 1024 else f"{count / 1024:.0f} KB" if count < 2**20 else f"{count / 2**20:.1f} MB"
