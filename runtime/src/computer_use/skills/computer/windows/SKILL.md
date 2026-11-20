---
name: windows
description: Using Windows. Read before looking for an app or file on this computer, before opening a file in an app, before changing a document that is open in an app with a command, before reporting that something is not on this computer, and when an animated screen refuses your keys.
---

## Finding what is on this computer

Start search shows installed apps, indexed places and web results. It misses portable programs and folders it has not indexed, so an empty result does not mean the thing is absent.

Before you say an app or file is not on this computer, look in these places, in order:

1. The folder where a related file was found, its parent folder and the folders beside it.
2. Desktop, Downloads, Documents, and the top-level folders of each drive.
3. PowerShell, by name: `Get-ChildItem C:\ -Recurse -Depth 4 -Filter "name*" -ErrorAction SilentlyContinue | Select-Object -First 20 FullName`

A README or web page says what its author suggests, not what this computer has. When you do report something missing, say where you looked.

## Opening a file in an app

- Double-clicking a file with no associated app opens a prompt to choose one. Close it, start the app, and load the file from the app's own Open command.
- An app left open may hold another file. Load the file you were asked for, even when the app looks ready, and do not report it as open until the app shows it.

## Changing an open document with a command

To fill in or change more than a few cells or lines, a command is faster and surer than typing them into the app.

A document open on the screen belongs to the app showing it. To change it with a command, reach that open document by its full path and save it there: `[Runtime.InteropServices.Marshal]::BindToMoniker('C:\full\path\file.xlsx')` returns the workbook (a Word file gives its document) in the app showing it. `GetActiveObject('Excel.Application')` fails with MK_E_UNAVAILABLE until a just-opened app has lost focus once. A new instance (`New-Object -ComObject Excel.Application`) gets only a read-only copy of a file another instance holds, so what it writes never reaches the file. Check the change on the screen afterwards.

## Screens that keep moving

Games, videos and animations change the screen on their own, so keys can come back with "the screen changed since your last screenshot". When one does, send that key again in a computer_batch right after a left click on a still part of the window, since a click on the moving part is refused too; the click also confirms the window has the focus. Do this only after a refusal: the extra click makes every input slower.
