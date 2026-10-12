# MX-Edit Testing – HeadRush Pedalboard & Gigboard

This repository collects test reports for running the **HeadRush Bridge** on the HeadRush
**Pedalboard** and **Gigboard**. The bridge and the editor themselves live in
[TicT4x/MX-Edit](https://github.com/TicT4x/MX-Edit). They were developed and tested on a
HeadRush **MX5**. There the bridge is called *MX5 Bridge*. It is the same firmware add-on,
here built for all three devices.

The Pedalboard and the Gigboard run the same firmware line (2.7) as the MX5: the same start
scripts, the same Linux kernel, the same rig database. The bridge changes the same files on all
three devices. **It runs on a real Pedalboard (first report); the Gigboard has not been tested
yet.** If you own one and want to help, this page explains how.

## Status

| | MX5 | Pedalboard | Gigboard |
|---|---|---|---|
| Patcher builds an updater | yes | yes (testing patcher) | yes (testing patcher) |
| Bridge firmware runs on the device | tested | **runs** (first report, thank you!) | **unknown – please test** |
| MX5 Editor | full | refuses to connect for now | refuses to connect for now |

The editor knows only the MX5's hardware: three footswitches and banks of three rigs. The
Gigboard has four of each, and the Pedalboard has more switches. Until your diagnosis logs show
how these devices behave, the editor does not connect to them. If it did, it would load the
wrong rigs and press the wrong switches. Editing `.rig` files offline works on every device.

## Risks – please read

* **Pedalboard:** if the device does not start after the update, hold **footswitches 1 and 8**
  while you switch it on. It then goes into recovery mode, and you can flash the official
  HeadRush updater again.
* **Gigboard:** it has **no recovery mode** that can re-flash the firmware. A firmware that does
  not start cannot be fixed with a footswitch combination. The changes are small and the same
  as on the MX5, but you are among the first to try them.
* Back up your rigs first (USB transfer mode, copy the drive).
* Unofficial, no warranty, use at your own risk.

## Steps

1. Download `HeadRush_Bridge_Testing_Patcher.exe` and `HeadRush_Bridge_Diagnose.exe` from the
   [releases of this repository](https://github.com/TicT4x/MX-Edit-Testing/releases).
2. Start the patcher, pick your device, tick *I understand the risk …* and click
   **Build updater**. The patcher downloads the official 2.7 updater for your device from
   inMusic and adds the bridge. You can add the
   [NAM mod](https://github.com/lolgab/headrush-nam-mod) too.
3. Put the device into firmware update mode (Global Settings › ⋯ › Firmware Update), start the
   new updater and install it.
4. After the device has restarted, connect it to the PC via USB. Do not switch on USB audio or
   USB transfer mode.
5. Double-click `HeadRush_Bridge_Diagnose.exe` and follow the window. You need nothing special on the
   device: no test rig and no particular setlist. The program **only reads** and changes nothing.
   * It waits until the device is connected and reads it (about 20 seconds).
   * Then it watches while you use the device, in three short steps (about 2 minutes). It
     always tells you which view to open and notices by itself when you are there:
     1. **Rig view:** it shows the rig names it reads. Say whether they match the display, then
        page one bank down and up again. This does not load a rig.
     2. **Stomp view:** it shows the switches with their display texts and tells you which ones
        to press: the effect and scene switches. Leave out the switches that change the rig or
        the view. Every press is confirmed on screen, and the step ends by itself.
     3. **Setlists (optional):** if you use setlists, open one and switch to the next song or rig.
        This loads a rig, so save unsaved changes first. You can skip this step.
6. At the end the program saves `HeadRush_Bridge_Diagnose_<device>_<time>.txt`, shows it in Explorer
   and opens the *Diagnosis log* form of this repository in your browser. Fill in the form and
   drag the file into it. You need a free GitHub account. The log is also saved if something
   goes wrong. Please send it then too.

The log contains the names of your rigs, setlists and songs, the device settings, the database
layout and the layout of a rig: which settings a rig has, but not their values. It does **not**
contain your sounds or any audio.

If you already sent a log with an older version of the diagnosis, please run the new one once
more. It collects a lot more.

## If something goes wrong

* **The diagnosis does not find the device:** check the MIDI port list it prints. If you see
  the device under another name, run
  `HeadRush_Bridge_Diagnose.exe --in "<input name>" --out "<output name>"`.
* **USB audio or USB transfer mode stopped working:** please report it. To switch the bridge's
  USB-MIDI off, put a file `usb_midi_aus.txt` into the `MX5Bridge` folder (its internal name) of the
  device's USB drive and restart the device.
* **The device does not start any more:** see *Risks* above. Then please report what you saw.

## What is in this repository

* `diagnose/` – source of `HeadRush_Bridge_Diagnose.exe` (Python, needs `pip install mido python-rtmidi`;
  `python diagnose/geraet_diagnose.py`). It uses `bridge.py` from MX-Edit.
* The testing patcher is the same source as the patcher in
  [MX-Edit/firmware](https://github.com/TicT4x/MX-Edit/tree/main/firmware). It is built with a
  flag that also offers the Pedalboard and the Gigboard.

No HeadRush firmware is distributed here. The patcher downloads the official updater from
inMusic on your computer.

MIT licence (see `LICENSE`). HeadRush is a trademark of inMusic Brands; this project is not
affiliated with or endorsed by inMusic.
