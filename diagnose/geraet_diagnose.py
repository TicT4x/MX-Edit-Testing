#!/usr/bin/env python3
"""MX5 Bridge - Geraete-Diagnose fuer Tester mit HeadRush Pedalboard / Gigboard (auch MX5).

Liest ueber die Bruecke nur aus (nichts wird geschrieben, kein Rig geladen) und schreibt eine
Logdatei MX5Bridge_Diagnose_<Geraet>_<Zeit>.txt, die Tester einreichen koennen: welche
Engine-Pfade es gibt (Fussschalter, Bank-Rigs, Dialogtasten, Pedale, Meter ...) mit ihren
Werten und Auswahllisten, Firmware-/Systemangaben und das DB-Schema. Auf Wunsch fragt das
Programm danach, was das Display zeigt, und zeichnet auf, welche Pfade sich beim Druecken der
Fussschalter aendern (das Druecken macht der Tester selbst am Geraet).

Texte fuer Tester englisch (oeffentlich), Kommentare deutsch.

    python geraet_diagnose.py            Ausgabe + Fragen
    python geraet_diagnose.py --auto     nur auslesen, keine Fragen
    python geraet_diagnose.py --ports    MIDI-Ports anzeigen
"""
import argparse, datetime, json, os, platform, sys, threading, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))   # bridge.py liegt im Editor-Ordner
FROZEN = getattr(sys, 'frozen', False)
DATA = getattr(sys, '_MEIPASS', HERE)
OUT_DIR = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else os.getcwd()

try:
    import mido
except ImportError:
    print('Python package "mido" is missing:  pip install mido python-rtmidi')
    sys.exit(1)
from bridge import Bridge, BridgeError

TOOL_VERSION = '1'
E = '/Engine'
PC, RC, FS = E + '/PresetCtrl', E + '/RedirCtrl', E + '/FootSwitch'

# Nummerierte Pfade: (Muster, hoechste Nummer). Die Firmware baut sie mit %1 zusammen, im
# Binary stehen sie daher nicht vollstaendig (beim Pedalboard z. B. RigName%1).
NUMBERED = [
    (PC + '/RigName%d', 16), (PC + '/RigColour%d', 16), (PC + '/LoadRig%d', 16),
    (PC + '/SetRigName%d', 16), (PC + '/SetRigColour%d', 16), (PC + '/LoadSetRig%d', 16),
    (PC + '/SetName%d', 8), (RC + '/AccessSet%d', 8),
    (RC + '/Button%d', 16), (RC + '/ButtonText%d', 16), (RC + '/ButtonTextLow%d', 16),
    (RC + '/ButtonCol%d', 16), (RC + '/ButtonTimer%d', 16),
    (RC + '/RawFootswitches/FS%d', 16), (RC + '/On%d', 16), (RC + '/Encoder%d', 8),
    (RC + '/AccessParam%d', 8), (RC + '/ParamName%d', 16), (RC + '/ParamRedirected%d', 16),
    (FS + '/FootSwitch%d', 16), (FS + '/FootSwitchText%d', 16), (FS + '/FootSwitchColour%d', 16),
    (FS + '/FootSwitchOn%d', 16), (FS + '/FootSwitchTimer%d', 16), (FS + '/ModeNew%d', 16),
    (FS + '/Mode%d', 16), (FS + '/Module%d', 16), (FS + '/ModuleList%d', 16),
    (FS + '/Operation%d', 16), (FS + '/OperationList%d', 16), (FS + '/UserFootSwitchText%d', 16),
    (FS + '/SceneNumberOfStates%d', 16), (FS + '/MacroColour%d', 16), (FS + '/State2MacroColour%d', 16),
    (FS + '/SceneState%d', 16), (FS + '/SceneActive%d', 16), (FS + '/Scene%d', 16),
    (E + '/Patch/Chain/ModuleType%d', 16), (E + '/Patch/Chain/CanDouble%d', 16),
]
for _p in (1, 2, 3, 4):
    NUMBERED += [(E + '/Pedal%d/ModuleList%%d' % _p, 6), (E + '/Pedal%d/ParamList%%d' % _p, 6),
                 (E + '/Pedal%d/Min%%d' % _p, 6), (E + '/Pedal%d/Max%%d' % _p, 6)]
EXTRA = [PC + '/Rigs/' + n for n in ('LoadedName', 'LoadedID', 'Dirty', 'LoadedProgNum', 'ReceivePresetIndex',
                                      'SendPresetIndex', 'SelectedID', 'LoadedColor')] + \
        [E + '/Pedal%d/PedalMode' % p for p in (1, 2, 3, 4)] + \
        [RC + '/BoardMode', RC + '/CurModule', RC + '/CurModuleWithDoubled', RC + '/AccessRigView',
         RC + '/AccessTuner', RC + '/ExitTuner', RC + '/EditModeSaveRig', PC + '/NextPreset', PC + '/PrevPreset',
         E + '/Patch/Chain/Routing', E + '/Patch/Rig/Tempo', E + '/Patch/Rig/TempoFromMaster',
         E + '/Patch/Amp/Type', E + '/Patch/Cab/CabType', E + '/InputMeter/Current', E + '/InputMeter/Peak',
         E + '/OutputMeterL/Current', E + '/OutputMeterR/Current', E + '/FFTCtrl/TunerString',
         E + '/FFTCtrl/TunerCents', E + '/FFTCtrl/TunerRef', E + '/AudioCtrl/Input/TunerOn',
         E + '/AudioCtrl/Input/TunerMuting', FS + '/LastScene']

# Auswahllisten, die immer gelesen werden (sonst nur kurze Listen, s. MAX_ENTRIES_AUTO)
ENTRIES_ALWAYS = [RC + '/BoardMode', RC + '/CurModule', RC + '/CurModuleWithDoubled', E + '/Patch/Chain/Routing',
                  E + '/Patch/Chain/ModuleType1', E + '/Patch/Amp/Type', E + '/Patch/Cab/CabType']
MAX_ENTRIES_AUTO = 40
MAX_ENTRIES_CALLS = 400     # MX5: 256 Listen (~1 s); das Pedalboard hat mehr Pfade
# Erster Eintrag von /proc/device-tree/compatible -> Geraet (Patcher: bridgepatch.MODELS)
COMPATIBLE = {'inmusic,hg04': 'MX5', 'inmusic,mg01': 'Pedalboard', 'inmusic,hg02': 'Gigboard'}

# Nur lesende Shell-Befehle (Bruecke 0.3+): Modell, Firmware, USB-Gadget, Speicher
SHELL = [
    "tr '\\0' ' ' < /proc/device-tree/compatible; echo",
    "tr '\\0' ' ' < /proc/device-tree/model; echo",
    "uname -a",
    "cat /etc/os-release 2>/dev/null | head -5",
    "grep -h 'strings/0x409/product' /usr/Evil/Scripts/usb-otg-audio-start.sh /usr/Evil/Scripts/mx5bridge-usb.sh",
    "cat /sys/kernel/config/usb_gadget/*/strings/0x409/product 2>/dev/null",
    "cat /sys/kernel/config/usb_gadget/*/idProduct 2>/dev/null",
    "ls /usr/Evil/Assignments",
    "ls /usr/Evil/Firmware /usr/Evil/Scripts/*.dfu /usr/Evil/Scripts/firmware.json 2>/dev/null",
    "cat /usr/Evil/Scripts/firmware.json /usr/Evil/Firmware/firmware.json 2>/dev/null | head -40",
    "cat /usr/Evil/Scripts/mx5bridge-nam.txt 2>/dev/null",
    "ls /media/az01-internal/Evil",
    "df -k /media/az01-internal 2>/dev/null",
    "free -k",
    "cat /proc/cpuinfo | grep -i -E 'hardware|model name' | sort | uniq -c",
    "ls /media/az01-internal/Evil/usb_mnt 2>/dev/null",
    "ls /NAM /media/az01-internal/Evil/usb_mnt/NAM 2>/dev/null | head -5",
    "cat /tmp/mx5bridge/nam-aktiv 2>/dev/null; ls /tmp/mx5bridge 2>/dev/null | head -20",
]

SQL = [
    ("schema", "select type, name, sql from sqlite_master where sql is not null order by name"),
    ("counts", "select (select count(*) from rigs) as rigs, (select count(*) from setlists) as setlists, "
               "(select count(*) from setlist_rigs) as setlist_rigs, (select count(*) from blocks) as blocks"),
    ("settings", "select name, length(value) as len, case when name in ('db_version', 'RigVersion', 'State_Last') "
                 "then value end as value from settings"),
    ("block_types", "select type, count(*) as n from blocks group by type order by type"),
    ("rig_versions", "select json_extract(content, '$.info.version') as v, count(*) as n from rigs group by v"),
]


class Log:
    """Sammelt alles fuer die Logdatei; Ausgaben gehen zusaetzlich auf die Konsole."""
    def __init__(self):
        self.data = {'tool': 'MX5Bridge device diagnosis %s' % TOOL_VERSION,
                     'time': datetime.datetime.now().isoformat(timespec='seconds'),
                     'pc': platform.platform(), 'python': sys.version.split()[0], 'errors': []}
        self.lines = []

    def say(self, *a):
        t = ' '.join(str(x) for x in a)
        print(t, flush=True)
        self.lines.append(t)

    def error(self, where, e):
        self.say('  ! %s: %s' % (where, e))
        self.data['errors'].append({'where': where, 'error': str(e), 'trace': traceback.format_exc(limit=3)})


def ask(q, default=''):
    try:
        a = input(q).strip()
    except EOFError:
        return default
    return a or default


def yes(q):
    return ask(q + ' [y/n] ').lower().startswith(('y', 'j'))


def all_paths(log=None):
    paths = []
    try:
        with open(os.path.join(DATA, 'diagnose_pfade.txt'), encoding='ascii') as f:
            paths += [l.strip() for l in f if l.startswith('/Engine/')]
    except OSError as e:
        if log:
            log.error('diagnose_pfade.txt', e)
    if log:
        log.data['fixed_path_list'] = len(paths)
    for pat, n in NUMBERED:
        paths += [pat % i for i in range(1, n + 1)]
    paths += EXTRA
    seen, out = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def open_bridge(log, ports):
    ins, outs = mido.get_input_names(), mido.get_output_names()
    log.data['midi_ports'] = {'in': ins, 'out': outs}
    log.say('MIDI inputs :', ins)
    log.say('MIDI outputs:', outs)
    try:
        pin, pout = Bridge.find_ports()
    except BridgeError:
        if not ports:
            raise BridgeError('Could not find the HeadRush MIDI port automatically. Run with --in "<name>" --out "<name>" '
                              '(names above). Is the bridge firmware installed and the device not in USB audio / '
                              'USB transfer mode?')
        pin, pout = ports
    if ports and ports[0]:
        pin, pout = ports
    log.data['ports_used'] = [pin, pout]
    log.say('Using:', pin, '/', pout)
    br = Bridge(pin, pout)
    for i in range(10):
        try:
            br.ping()
            break
        except BridgeError:
            if i == 9:
                raise BridgeError('The device does not answer. Wait ~15 s after power-on, then try again.')
            time.sleep(1)
    return br


def probe_engine(br, log):
    paths = all_paths(log)
    log.say('Reading %d engine paths (%d from the fixed list) ...' % (len(paths), log.data['fixed_path_list']))
    t = time.time()
    res = {}
    try:
        res = br.get_many(paths)
    except BridgeError as e:
        log.error('get_many', e)
    found = {p: i for p, i in res.items() if isinstance(i, dict) and i.get('ok')}
    log.data['engine'] = found
    log.data['engine_missing'] = sorted(p for p in paths if p not in found)
    log.say('  %d exist, %d do not (%.1f s)' % (len(found), len(paths) - len(found), time.time() - t))

    want = [p for p in ENTRIES_ALWAYS if p in found]
    want += [p for p, i in found.items() if p not in want and 0 < (i.get('numEntries') or 0) <= MAX_ENTRIES_AUTO]
    ent = {}
    for p in want[:MAX_ENTRIES_CALLS]:
        try:
            ent[p] = br.entries(p)
        except BridgeError as e:
            ent[p] = {'error': str(e)}
    log.data['entries'] = ent
    log.say('  %d choice lists read' % len(ent))
    return found


def probe_shell(br, log):
    if not br.v3:
        log.say('Bridge < 0.3: no shell, system info skipped')
        return
    out = {}
    for cmd in SHELL:
        try:
            rc, text = br.shell(cmd)
            out[cmd] = {'rc': rc, 'out': text[-4000:]}
        except BridgeError as e:
            out[cmd] = {'error': str(e)}
    log.data['system'] = out
    comp = out.get(SHELL[0], {}).get('out', '').strip()
    log.data['device'] = COMPATIBLE.get(comp.split(' ')[0], comp.split(' ')[0] if comp else '')
    log.say('Device tree:', comp or '?', '->', log.data['device'] or 'unknown')


def probe_db(br, log):
    if not br.v3:
        return
    db = {}
    for name, q in SQL:
        try:
            db[name] = br.sql(q)
        except BridgeError as e:
            db[name] = {'error': str(e)}
    if br.v4:
        try:
            db['status'] = br.action('status')
        except BridgeError as e:
            db['status'] = {'error': str(e)}
    log.data['db'] = db
    c = db.get('counts')
    if isinstance(c, list) and c:
        log.say('Database: %(rigs)s rigs, %(setlists)s setlists, %(blocks)s block presets' % c[0])


def summary(log, found):
    """Kurze lesbare Zusammenfassung oben in der Logdatei."""
    def nums(pat, n=16):
        return [i for i in range(1, n + 1) if pat % i in found]
    s = {
        'bank_rig_slots': nums(PC + '/RigName%d'),
        'setlist_bank_slots': nums(PC + '/SetRigName%d'),
        'footswitches': nums(FS + '/FootSwitch%d'),
        'footswitch_modes': nums(FS + '/ModeNew%d'),
        'raw_footswitches': nums(RC + '/RawFootswitches/FS%d'),
        'dialog_buttons': nums(RC + '/ButtonText%d'),
        'chain_slots': nums(E + '/Patch/Chain/ModuleType%d'),
        'param_names': nums(RC + '/ParamName%d'),
        'pedals': [p for p in (1, 2, 3, 4) if (E + '/Pedal%d/ModuleList1' % p) in found],
        'board_modes': log.data.get('entries', {}).get(RC + '/BoardMode'),
        'board_mode_now': (found.get(RC + '/BoardMode') or {}).get('string'),
        'meters': [p.split('/')[2] for p in (E + '/InputMeter/Current', E + '/OutputMeterL/Current') if p in found],
    }
    log.data['summary'] = s
    log.say('')
    for k, v in s.items():
        log.say('  %-20s %s' % (k, v))
    return s


# ---------- Fragen an den Tester ----------
def watch(br, paths, log, label):
    """Pfade pollen, bis der Tester Enter drueckt; Aenderungen mit Zeit aufzeichnen."""
    stop = threading.Event()
    events, last = [], {}

    def loop():
        t0 = time.time()
        while not stop.is_set():
            try:
                cur = br.get_many(paths)
            except BridgeError as e:
                events.append({'t': round(time.time() - t0, 2), 'error': str(e)})
                time.sleep(0.3)
                continue
            for p, i in cur.items():
                v = {k: i.get(k) for k in ('value', 'state', 'index', 'string') if k in i}
                if last.get(p) != v:
                    if p in last:
                        events.append({'t': round(time.time() - t0, 2), 'path': p, 'from': last[p], 'to': v})
                    last[p] = v
            time.sleep(0.03)
    th = threading.Thread(target=loop, daemon=True)
    th.start()
    ask('')
    stop.set()
    th.join(2)
    log.data.setdefault('watch', {})[label] = events
    changed = sorted({e['path'] for e in events if 'path' in e})
    log.say('  %d changes in %d paths' % (len(events), len(changed)))
    presses = press_map(events)
    log.data.setdefault('press_map', {})[label] = presses
    for p in presses:
        log.say('  %-6s -> %s' % (p['raw'], ', '.join(p['effects']) or '(nothing seen)'))
    return events


def press_map(events):
    """Je Druck (RawFootswitches/FS<n> wird Down) die Aenderungen bis zum naechsten Druck:
    welche FootSwitch<n> angehen, welches Rig geladen wird, welche Szene. Am MX5 (2026-10-04):
    FS1-3 -> FootSwitch5-7 / LastScene 0-2 (Stomp), Bank-Rig 1-3 (Rig)."""
    downs = [e for e in events if e.get('path', '').startswith(RC + '/RawFootswitches/FS')
             and (e.get('to') or {}).get('state') is True]
    out = []
    for i, d in enumerate(downs):
        end = downs[i + 1]['t'] if i + 1 < len(downs) else float('inf')
        eff = []
        for e in events:
            if not (d['t'] <= e.get('t', -1) < end) or 'path' not in e:
                continue
            p, to = e['path'], e.get('to') or {}
            name = p.rsplit('/', 1)[1]
            if name.startswith('FootSwitch') and name[10:].isdigit() and to.get('state') is True:
                eff.append(name + ' on')
            elif name == 'LastScene':
                eff.append('LastScene ' + str(to.get('string')))
            elif name == 'LoadedName':
                eff.append('loads ' + str(to.get('string')))
            elif name == 'BoardMode':
                eff.append('view ' + str(to.get('string')))
        out.append({'raw': d['path'].rsplit('/', 1)[1], 't': d['t'], 'effects': eff})
    return out


def interactive(br, log, found):
    q = log.data.setdefault('answers', {})
    log.say('\n--- A few questions (just press Enter to skip one) ---')
    q['device'] = ask('Which device is this (MX5 / Pedalboard / Gigboard)? ')
    q['firmware_shown'] = ask('Firmware version shown in Global Settings (e.g. 2.7)? ')
    q['footswitch_count'] = ask('How many footswitches does the device have? ')

    names = [(i, found[PC + '/RigName%d' % i].get('string')) for i in range(1, 17) if PC + '/RigName%d' % i in found]
    if names:
        log.say('\nPut the device into the RIG view (rig/bank list) and press Enter.')
        ask('')
        try:
            cur = br.get_many([PC + '/RigName%d' % i for i, _ in names] + [RC + '/BoardMode', PC + '/Rigs/LoadedName'])
            log.data['rig_view'] = cur
            for i, _ in names:
                log.say('  RigName%d = %r' % (i, (cur.get(PC + '/RigName%d' % i) or {}).get('string')))
            log.say('  view = %r' % (cur.get(RC + '/BoardMode') or {}).get('string'))
        except BridgeError as e:
            log.error('rig view', e)
        q['rigs_per_bank'] = ask('How many rigs does the display show per bank? ')
        q['rig_names_match'] = ask('Are the names above the rigs of the shown bank, in the same order? [y/n/partly] ')

    log.say('\nFootswitch test. Put the device into the STOMP view (block on/off), so pressing a '
            'switch does not change the rig.\nThen press Enter here, press EACH footswitch once from left '
            'to right (top row first, if there are two), wait a second between presses,\nand press Enter '
            'here again when done.')
    if ask('Press Enter to start (or type s to skip): ').lower().startswith('s'):
        return
    paths = [p for p in found if p.startswith((FS + '/FootSwitch', RC + '/RawFootswitches/', FS + '/SceneState',
                                               FS + '/LastScene', RC + '/ButtonText'))]
    paths += [RC + '/BoardMode', PC + '/Rigs/LoadedName', PC + '/Rigs/Dirty']
    log.say('Recording ... press the footswitches now, then Enter.')
    watch(br, paths, log, 'footswitches_stomp')

    if yes('\nOptional: record the footswitches in the RIG view too (each press loads a rig)?'):
        log.say('Switch to the RIG view, then press Enter, press each switch once, then Enter.')
        ask('')
        log.say('Recording ...')
        watch(br, paths + [p for p in found if p.startswith(PC + '/RigName')], log, 'footswitches_rig')
    q['notes'] = ask('\nAnything else you noticed (one line, optional)? ')


def write(log):
    dev = log.data.get('device') or (log.data.get('answers', {}).get('device') or '').strip() or 'device'
    dev = ''.join(c for c in dev if c.isalnum())[:20] or 'device'
    name = 'MX5Bridge_Diagnose_%s_%s.txt' % (dev, datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    path = os.path.join(OUT_DIR, name)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(log.lines) + '\n\n===== JSON =====\n')
        json.dump(log.data, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write('\n')
    return path


def main():
    ap = argparse.ArgumentParser(description='MX5 Bridge device diagnosis (read-only)')
    ap.add_argument('--auto', action='store_true', help='read only, ask no questions')
    ap.add_argument('--ports', action='store_true', help='list MIDI ports and exit')
    ap.add_argument('--in', dest='pin', help='MIDI input port name')
    ap.add_argument('--out', dest='pout', help='MIDI output port name')
    a = ap.parse_args()
    if a.ports:
        print('in :', mido.get_input_names())
        print('out:', mido.get_output_names())
        return 0
    log = Log()
    log.say('MX5 Bridge device diagnosis %s - reads only, changes nothing on the device.' % TOOL_VERSION)
    log.say('The log contains rig/setlist names and settings shown by the device, no audio and no rig contents.\n')
    br = None
    rc = 0
    try:
        br = open_bridge(log, (a.pin, a.pout) if a.pin and a.pout else None)
        log.data['bridge'] = {'version': br.version, 'vnum': br.vnum}
        log.say('Bridge:', br.version)
        probe_shell(br, log)
        found = probe_engine(br, log)
        probe_db(br, log)
        summary(log, found)
        if not a.auto:
            interactive(br, log, found)
    except KeyboardInterrupt:
        log.say('\nCancelled.')
        rc = 1
    except Exception as e:  # noqa: BLE001 - alles soll in die Logdatei
        log.error('main', e)
        rc = 1
    finally:
        if br:
            br.close()
    path = write(log)
    log.say('\nLog written: %s' % path)
    log.say('Please attach this file to a GitHub issue: https://github.com/TicT4x/MX-Edit-Testing/issues')
    return rc


if __name__ == '__main__':
    rc = main()
    if FROZEN and sys.stdin and sys.stdin.isatty():
        try:
            input('\nPress Enter to close this window.')
        except EOFError:
            pass
    sys.exit(rc)
