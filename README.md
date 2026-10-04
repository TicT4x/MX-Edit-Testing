# MX-Edit Testing – HeadRush Pedalboard & Gigboard

This repository collects test reports for running the **MX5 Bridge** on the HeadRush
**Pedalboard** and **Gigboard**. The bridge and the editor themselves live in
[TicT4x/MX-Edit](https://github.com/TicT4x/MX-Edit). They were developed and tested on a
HeadRush **MX5**.

The Pedalboard and the Gigboard run the same firmware line (2.7) as the MX5: the same start
scripts, the same Linux kernel, the same rig database. The bridge changes the same files on all
three devices. **It has not been tested on a real Pedalboard or Gigboard yet.** If you own one
and want to help, this page explains how.

## Status

| | MX5 | Pedalboard | Gigboard |
|---|---|---|---|
| Patcher builds an updater | yes | yes (testing patcher) | yes (testing patcher) |
| Bridge firmware runs on the device | tested | **unknown – please test** | **unknown – please test** |
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

1. Download `MX5Bridge_Testing_Patcher.exe` and `MX5Bridge_Diagnose.exe` from the
   [releases of this repository](https://github.com/TicT4x/MX-Edit-Testing/releases).
2. Start the patcher, pick your device, tick *I understand the risk …* and click
   **Build updater**. The patcher downloads the official 2.7 updater for your device from
   inMusic and adds the bridge. You can add the
   [NAM mod](https://github.com/lolgab/headrush-nam-mod) too.
3. Put the device into firmware update mode (Global Settings › ⋯ › Firmware Update), start the
   new updater and install it.
4. After the device has restarted, wait about 20 seconds. Connect it to the PC via USB. Do not
   switch on USB audio or USB transfer mode.
5. Start `MX5Bridge_Diagnose.exe`. It **only reads** from the device and changes nothing. It
   then asks a few questions about what the display shows. For the footswitch test, press each
   switch once while the program records. Do this in the Stomp view, so that no rig changes.
6. The program writes `MX5Bridge_Diagnose_<device>_<time>.txt` next to itself.
   [Open an issue](https://github.com/TicT4x/MX-Edit-Testing/issues/new/choose) with the
   *Diagnosis log* form and attach that file. Also say whether the device behaved normally after
   the update (sound, footswitches, USB transfer mode, USB audio).

The log contains the rig and setlist names your device shows, the device settings and the
database layout. It does **not** contain your rig contents or any audio.

## If something goes wrong

* **The diagnosis does not find the device:** check the MIDI port list it prints. If you see
  the device under another name, run
  `MX5Bridge_Diagnose.exe --in "<input name>" --out "<output name>"`.
* **USB audio or USB transfer mode stopped working:** please report it. To switch the bridge's
  USB-MIDI off, put a file `usb_midi_aus.txt` into the `MX5Bridge` folder of the device's USB
  drive and restart the device.
* **The device does not start any more:** see *Risks* above. Then please report what you saw.

## What is in this repository

* `diagnose/` – source of `MX5Bridge_Diagnose.exe` (Python, needs `pip install mido python-rtmidi`;
  `python diagnose/geraet_diagnose.py`). It uses `bridge.py` from MX-Edit.
* The testing patcher is the same source as the patcher in
  [MX-Edit/firmware](https://github.com/TicT4x/MX-Edit/tree/main/firmware). It is built with a
  flag that also offers the Pedalboard and the Gigboard.

No HeadRush firmware is distributed here. The patcher downloads the official updater from
inMusic on your computer.

MIT licence (see `LICENSE`). HeadRush is a trademark of inMusic Brands; this project is not
affiliated with or endorsed by inMusic.
