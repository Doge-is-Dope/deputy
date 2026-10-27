"""The instructions of the model that names conversations."""

TITLE_PROMPT = """\
Write a short title for the conversation that opens with the user's message, so the user can recognize it in a \
sidebar list.
Name what the user asks for, and a question by its subject. Do not answer the request or carry it out.
2 to 5 words, in sentence case: capitalize only the first word and proper nouns.
Write in the predominant language of the message; keep names, file names and code terms as written.
No quotes, markdown or ending punctuation.

Examples:
"Can you rename every photo in my Downloads folder by the date it was taken?" → Rename photos by date
"write a short poem about autumn" → Autumn poem
"Which moons of Mars are the largest?" → Largest moons of Mars
"幫我把這份報告轉成 PDF 寄給 Amy" → 報告轉 PDF 寄給 Amy
"""
