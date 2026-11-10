---
name: pokemon-red
description: Pokémon Red, the Game Boy game, played in an emulator. Read before opening the game, continuing a save, or moving or choosing anything in it.
---

## Opening the game

The game is a ROM file (.gb or .gbc) that needs an emulator. An emulator is often a portable program in its own folder, so it may not appear in Start search; the windows skill says where to look. Progress is in the file with the ROM's name and the extension .sav, in the same folder.

## Keys

In mGBA's default keys, A is X, B is Z, Start is Enter, and the direction pad is the arrow keys.

- Use hold_key with a duration of 0.2 for every button. The game can miss the short press that `key` sends.
- To walk several steps in one direction, send one hold of 0.27 × N − 0.13 seconds rather than a hold per step: 0.2 for one step, 0.4 for two, 0.67 for three, 0.93 for four, 1.2 for five, also in a new direction. A wall or a person stops it sooner, so count the steps from how far a landmark moved on the screen after it.
- Dialogue: if press_while is available, move through it with press_while, the key x and the condition "A dialogue text box with text is shown, and no menu, list or YES/NO choice is open". It stops at the next menu or choice, which you then make yourself.

## Continuing a save

Press Start at the title screen, then choose CONTINUE with A, and press A again on the summary.

If the menu shows NEW GAME and no CONTINUE, this copy has no progress. Check first that you loaded the file you were asked for. Never choose NEW GAME to continue a game, and never load another file's save into this copy.

Do not save in the game unless the user asked for that: it overwrites their progress.

## Starting a new game

Only when the user asks, or says this copy has no progress. Move through the dialogue with press_while as above; without it, press A one press per call until the name menus are done: a batch of presses can run past a menu and pick the wrong name. At a name, press Down to a name in the list and press A.

## Battles

Losing does not end the game. The story goes on after the first battle with the rival whether you win or lose, and after a later loss the player wakes at the last Pokémon Center. Keep playing toward the goal.

## Knowing where you are

Check the screen after every step. The player stays at the centre while the map scrolls, so count how far a landmark moved. A hold that left the map as it was did not move, so do not count it.

A new game's opening ends in the player's room: a bed, a TV, a plant and stairs. Something in the way does not end a walk: go around it or take a line with room enough, and count the steps of that line.
