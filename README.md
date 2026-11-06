# Ievan Polkka PV mod for Hatsune Miku: Project DIVA (PSP)

On the PSP, *Ievan Polkka* only had a slideshow of illustrations. This mod gives it a full 3D PV:

- Miku dancing the Project DIVA Ievan Polkka choreography, in sync with the song
- PV camera work: cuts, close-ups and zoom shots
- a bright grass-field stage with sky, clouds, hills, grass and flowers
- leeks in her hands during the leek sections
- lip sync while she sings
- Ievan Polkka unlocked from the start on a new save

The rhythm game keeps the original PSP Easy / Normal / Hard note charts.

## Download

**[Download the latest release](https://github.com/HimariHikari/ievan-polkka-psp-mod/releases/latest)**: get the `.zip` file under *Assets*.

The download is about 2 MB. It does **not** include the game; you apply it to your own copy.

## What you need

- A Windows 10 or 11 PC to run the installer. You can play the result anywhere.
- Your own ISO of **Hatsune Miku: Project DIVA (Japan, ULJM-05472) with the English patch v1.0** applied.

The installer checks your ISO and refuses anything else, such as another version, an untranslated ISO or an ISO that's already modded. It can't produce a broken file.

## How to install

1. Unzip the download and double-click `IevanPolkkaPatcher.exe`.
   - Windows may say **"Windows protected your PC"** because the program isn't signed. Click **More info → Run anyway**.
2. Click **Browse...** and pick your game ISO.
3. Check where the modded ISO will be saved. By default it goes next to yours, named `... (Ievan Polkka mod).iso`.
4. Click **Install mod**. It takes a few seconds to a minute.

Your original ISO is never changed. You get a second, modded ISO of about 1.7 GB.

Command line (optional):

```
IevanPolkkaPatcher.exe "C:\path\to\your.iso" ["C:\path\to\output.iso"]
```

## How to play

- Load the modded ISO in PPSSPP. A real PSP with custom firmware should work too, but hasn't been tested yet.
- Start a **new** game. An existing save keeps its own unlocks.
- Go to Free Play and pick **Ievan Polkka**.

## Known limitations

- PV Mode (watching without notes) follows the game's normal unlock rules. You unlock it by clearing the song.
- Only tested in PPSSPP so far.

## Credits

- Dance motion: Unity humanoid conversion of the Project DIVA Ievan Polkka motion (`project-diva-motion-ievan-polkka` package)
- PV camera: "MMD Ievan Polka Camera DL" by erictep123 (DeviantArt)
- Stage textures: from the Project DIVA Future Tone grass stage (ns016) MMD conversion
- Game, songs and characters: © SEGA / Crypton Future Media. Ievan Polkka arrangement: Otomania.
- English translation patch: the Project DIVA English patch team

This is an unofficial fan mod, not affiliated with SEGA or Crypton Future Media. Please don't share game ISOs; share only this installer.

## For modders

The `tools/` folder holds the Python build pipeline: the IGB model/animation writer, DSC script editor, AFS archive tools, camera and stage converters. `installer/` holds the patcher's C# source. See [BUILDING.md](BUILDING.md) for how the mod is built.
