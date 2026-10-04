#!/usr/bin/env python3
"""HeadRush Bridge - Geraete-Diagnose fuer Tester mit HeadRush Pedalboard / Gigboard (auch MX5).
Fuer Tester heisst die Bruecke "HeadRush Bridge" (Repo MX-Edit-Testing); intern ist es die MX5 Bridge.

Liest ueber die Bruecke nur aus (nichts wird geschrieben, kein Rig geladen) und schreibt eine
Logdatei HeadRush_Bridge_Diagnose_<Geraet>_<Zeit>.txt, die Tester einreichen koennen: welche
Engine-Pfade es gibt (Fussschalter, Bank-Rigs, Dialogtasten, Pedale, Meter ...) mit ihren
Werten und Auswahllisten, Firmware-/Systemangaben und das DB-Schema. Auf Wunsch fragt das
Programm danach, was das Display zeigt (die Ansicht des Geraets erkennt es selbst und wartet
darauf), und zeichnet auf, welche Pfade sich beim Druecken der Fussschalter aendern (das Druecken
macht der Tester selbst am Geraet, in der Stomp-Ansicht - dort laedt ein Schalter kein Rig).
Fuer fremde Geraete gebaut: keine Voraussetzungen auf dem Geraet, wartet auf das Geraet, speichert
das Log auch bei Fehlern/Abbruch und oeffnet am Ende das Issue-Formular von MX-Edit-Testing.

Texte fuer Tester englisch (oeffentlich), Kommentare deutsch.

    python geraet_diagnose.py            Ausgabe + Fragen
    python geraet_diagnose.py --auto     nur auslesen, keine Fragen
    python geraet_diagnose.py --ports    MIDI-Ports anzeigen
"""
import argparse, datetime, json, os, platform, sys, time, traceback

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
        self.data = {'tool': 'HeadRush Bridge device diagnosis %s' % TOOL_VERSION,
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


def key_pressed():
    """Taste im Konsolenfenster gedrueckt (nur Windows; sonst nie) - zum Abbrechen von Warteschleifen."""
    try:
        import msvcrt
    except ImportError:
        return False
    hit = False
    while msvcrt.kbhit():
        msvcrt.getwch()
        hit = True
    return hit


def find_ports(ports):
    """(Eingang, Ausgang) des HeadRush-Ports oder None. Mehrere Kandidaten: der Nutzer waehlt."""
    if ports:
        return ports
    ins, outs = mido.get_input_names(), mido.get_output_names()
    try:
        return Bridge.find_ports()
    except BridgeError:
        pass
    hi = [n for n in ins if 'headrush' in n.lower()]
    ho = [n for n in outs if 'headrush' in n.lower()]
    if len(hi) == 1 and len(ho) == 1:
        return hi[0], ho[0]
    if len(hi) > 1 and len(hi) == len(ho):
        print('Several HeadRush MIDI ports found:')
        for i, n in enumerate(hi, 1):
            print('  %d. %s' % (i, n))
        k = ask('Which one is the device to test? Number: ', '1')
        k = int(k) - 1 if k.isdigit() and 0 < int(k) <= len(hi) else 0
        return hi[k], ho[k]
    return None


def open_bridge(log, ports, wait=True):
    """Port suchen und anpingen. wait: bis zu 5 min auf das Geraet warten (Taste = aufgeben)."""
    t0, told = time.time(), False
    while True:
        found = find_ports(ports)
        if found:
            break
        if not wait or time.time() - t0 > 300:
            break
        if not told:
            log.say('Waiting for the device ...\n'
                    '  - connect it to this PC with a USB cable and switch it on,\n'
                    '  - wait about 20 seconds after it has started,\n'
                    '  - do not switch on USB audio or USB transfer mode on the device.\n'
                    '  (Press any key to give up.)')
            told = True
        if key_pressed():
            break
        time.sleep(1)
    ins, outs = mido.get_input_names(), mido.get_output_names()
    log.data['midi_ports'] = {'in': ins, 'out': outs}
    if not found:
        log.say('MIDI inputs :', ins)
        log.say('MIDI outputs:', outs)
        raise BridgeError('No HeadRush MIDI port found. Is the HeadRush Bridge firmware installed? Is the device in '
                          'USB audio or USB transfer mode (then switch that off)? If the device shows up under '
                          'another name above, start this program with --in "<name>" --out "<name>".')
    pin, pout = found
    log.data['ports_used'] = [pin, pout]
    log.say('Found:', pin, '/', pout)
    br = Bridge(pin, pout)
    for i in range(30):
        try:
            br.ping()
            return br
        except BridgeError:
            if i == 0:
                log.say('Waiting for the bridge to answer (up to 30 s) ...')
            time.sleep(1)
    br.close()
    raise BridgeError('The device does not answer bridge requests. Is the HeadRush Bridge firmware installed? '
                      'If you just switched it on, wait a minute and start this program again.')


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
def board_mode(br):
    try:
        return (br.get(RC + '/BoardMode') or {}).get('string') or ''
    except BridgeError:
        return ''


def wait_for_view(br, log, view, how, timeout=180):
    """Warten, bis das Geraet die Ansicht view zeigt (BoardMode). True = da, False = uebersprungen
    (Taste) oder Zeit um. Ist sie schon da, wird nichts gefragt."""
    if board_mode(br) == view:
        return True
    log.say('  -> Please switch the device to the %s view (%s).\n'
            '     The test continues by itself as soon as the device shows it. (Press any key to skip.)' % (view, how))
    t0 = time.time()
    while time.time() - t0 < timeout:
        if board_mode(br) == view:
            log.say('     OK, %s view detected.' % view)
            return True
        if key_pressed():
            break
        time.sleep(0.3)
    log.say('     Skipped.')
    return False


def record(br, paths, log, label, idle_stop=8.0, max_s=120.0):
    """Pfade pollen und Aenderungen mit Zeit aufzeichnen; jeder Tastendruck wird sofort gemeldet.
    Ende: idle_stop s nach dem letzten Druck, nach max_s oder per Taste."""
    events, last = [], {}
    t0, last_press, seen = time.time(), None, []
    while True:
        now = time.time()
        try:
            cur = br.get_many(paths)
        except BridgeError as e:
            events.append({'t': round(now - t0, 2), 'error': str(e)})
            time.sleep(0.3)
            cur = {}
        for p, i in cur.items():
            v = {k: i.get(k) for k in ('value', 'state', 'index', 'string') if k in i}
            if last.get(p) != v:
                if p in last:
                    events.append({'t': round(now - t0, 2), 'path': p, 'from': last[p], 'to': v})
                    if p.startswith(RC + '/RawFootswitches/FS') and v.get('state') is True:
                        last_press = now
                        n = p.rsplit('FS', 1)[1]
                        seen.append(n)
                        print('     press %d detected (switch input %s)' % (len(seen), n), flush=True)
                last[p] = v
        if key_pressed() or now - t0 > max_s or (last_press and now - last_press > idle_stop):
            break
        time.sleep(0.03)
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
    """Gefuehrter Teil: nur Fragen, die das Programm nicht selbst beantworten kann. Die Ansicht des
    Geraets wird selbst erkannt (BoardMode); in der Stomp-Ansicht laedt ein Fussschalter kein Rig
    (am MX5 geprueft) - in der Rig-Ansicht wuerde er, daher dort kein Schaltertest."""
    q = log.data.setdefault('answers', {})
    modes = log.data.get('entries', {}).get(RC + '/BoardMode') or []
    log.say('\n========== Part 2: three short checks with you ==========')
    log.say('(Just press Enter if you do not know an answer.)\n')
    q['footswitch_count'] = ask('1) How many footswitches does your device have? Number: ')

    names = [i for i in range(1, 17) if PC + '/RigName%d' % i in found]
    log.say('\n2) Rig names')
    if names and 'Rig' in modes and wait_for_view(br, log, 'Rig', 'the list of rigs in banks'):
        try:
            cur = br.get_many([PC + '/RigName%d' % i for i in names])
            log.data['rig_view'] = cur
            log.say('   The bridge reads these names for the bank on the display:')
            for i in names:
                log.say('     %d. %s' % (i, (cur.get(PC + '/RigName%d' % i) or {}).get('string')))
        except BridgeError as e:
            log.error('rig view', e)
        q['rigs_per_bank'] = ask('   How many rigs does the display show in one bank? Number: ')
        q['rig_names_match'] = ask('   Are these the same names, in the same order, as on the display? [y/n] ')

    log.say('\n3) Footswitch test')
    if 'Stomp' in modes:
        ok = wait_for_view(br, log, 'Stomp', 'the view where the footswitches switch effects on and off')
    else:
        ok = ask('   Switch the device to the view where the footswitches switch effects on and off, '
                 'then press Enter (or type s to skip): ').lower() != 's'
    if not ok:
        return
    if (found.get(PC + '/Rigs/Dirty') or {}).get('state'):
        log.say('   Note: the current rig has unsaved changes on the device. The test does not change that.')
    paths = [p for p in found if p.startswith((FS + '/FootSwitch', RC + '/RawFootswitches/', FS + '/SceneState',
                                               FS + '/LastScene', RC + '/ButtonText'))]
    paths += [RC + '/BoardMode', PC + '/Rigs/LoadedName', PC + '/Rigs/Dirty']
    log.say('   Now press EACH footswitch once, from left to right (top row first if there are two).\n'
            '   Wait about a second between presses. Every press is confirmed here.\n'
            '   The test ends by itself 8 seconds after your last press.')
    record(br, paths, log, 'footswitches_stomp')
    n = len(log.data.get('press_map', {}).get('footswitches_stomp', []))
    if n == 0:
        log.say('   No press was detected. That is useful information too.')
    q['notes'] = ask('\nAnything else you noticed? (one line, optional): ')


def write(log):
    dev = log.data.get('device') or (log.data.get('answers', {}).get('device') or '').strip() or 'device'
    dev = ''.join(c for c in dev if c.isalnum())[:20] or 'device'
    name = 'HeadRush_Bridge_Diagnose_%s_%s.txt' % (dev, datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    text = '\n'.join(log.lines) + '\n\n===== JSON =====\n' + \
        json.dumps(log.data, indent=1, ensure_ascii=False, sort_keys=True) + '\n'
    # neben der EXE; ist der Ordner schreibgeschuetzt (z. B. Programme), dann Desktop / Dokumente / Temp
    home = os.path.expanduser('~')
    for d in (OUT_DIR, os.path.join(home, 'Desktop'), os.path.join(home, 'Documents'), home,
              os.environ.get('TEMP', '')):
        if not d:
            continue
        try:
            path = os.path.join(d, name)
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
            return path
        except OSError:
            continue
    raise OSError('Could not write the log file anywhere')


ISSUE_URL = 'https://github.com/TicT4x/MX-Edit-Testing/issues/new?template=diagnosis.yml'


def show_file(path):
    """Explorer mit der Logdatei markiert oeffnen (nur Windows)."""
    try:
        import subprocess
        subprocess.Popen(['explorer', '/select,', path])
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description='HeadRush Bridge device diagnosis (read-only)')
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
    log.say('HeadRush Bridge device diagnosis %s' % TOOL_VERSION)
    log.say('This program only READS from your device. It changes nothing: no rigs, no settings.')
    log.say('The log contains rig/setlist names and settings shown by the device, no audio and no rig contents.\n')
    br = None
    rc = 0
    try:
        br = open_bridge(log, (a.pin, a.pout) if a.pin and a.pout else None, wait=not a.auto)
        log.data['bridge'] = {'version': br.version, 'vnum': br.vnum}
        log.say('Bridge:', br.version)
        log.say('\n========== Part 1: reading the device (about 10 seconds) ==========')
        probe_shell(br, log)
        found = probe_engine(br, log)
        probe_db(br, log)
        summary(log, found)
        if not a.auto:
            interactive(br, log, found)
    except KeyboardInterrupt:
        log.say('\nCancelled - the log so far is saved anyway.')
        rc = 1
    except Exception as e:  # noqa: BLE001 - alles soll in die Logdatei
        log.error('main', e)
        log.say('\nThe log is saved anyway - please send it, it helps to find the problem.')
        rc = 1
    finally:
        if br:
            br.close()
    path = write(log)
    log.say('\n========== Done ==========')
    log.say('Log file: %s' % path)
    if a.auto:
        return rc
    show_file(path)
    log.say('\nPlease send it: on the GitHub page that opens, fill in the form and drag this file into the '
            '"Diagnosis log" field.\n(You need a free GitHub account.) Address: %s' % ISSUE_URL)
    if ask('\nPress Enter to open the page in your browser (or type n): ').lower() != 'n':
        import webbrowser
        webbrowser.open(ISSUE_URL)
    return rc


if __name__ == '__main__':
    rc = main()
    if FROZEN and sys.stdin and sys.stdin.isatty():
        try:
            input('\nPress Enter to close this window.')
        except EOFError:
            pass
    sys.exit(rc)
