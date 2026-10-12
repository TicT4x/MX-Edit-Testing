#!/usr/bin/env python3
"""HeadRush Bridge - Geraete-Diagnose fuer Tester mit HeadRush Pedalboard / Gigboard (auch MX5).
Fuer Tester heisst die Bruecke "HeadRush Bridge" (Repo MX-Edit-Testing); intern ist es die MX5 Bridge.

Ein Werkzeug, das alles sammelt, was fuer die Unterstuetzung eines Geraets in MX-Edit noetig ist.
Es schreibt nichts aufs Geraet und laedt kein Rig. Teil 1 liest selbststaendig:
  - Engine-Pfade (Liste aus den drei Firmware-Binaries + nummerierte Muster) mit Werten und
    kurzen Auswahllisten; Luecken in nummerierten Reihen werden einzeln nachgeprueft
    (Pedalboard-Log 1: FootSwitch2/4 fehlten, 1/3/5-8 nicht),
  - Fussschalter-Zuweisungen inkl. Scene-Plaetze (translator.slot) und Scene-Presets,
  - System (Modell, Firmware, USB-Gadget), DB: Schema, Zeilen je Tabelle, Rig-Liste (nur Namen,
    Reihenfolge, Farbe, Programmnummer, Version), alle Setlist-/Song-Tabellen (Pedalboard hat
    setlist_songs/setlist_song_rigs), Aufbau (Schluessel ohne Werte) des geladenen Rigs und je
    Rig-Version eines Beispiel-Rigs.
Teil 2 ist eine gefuehrte Runde, in der das Programm nur beobachtet, was der Tester am Geraet tut
(Ansicht wird selbst erkannt): Rig-Ansicht (Namen bestaetigen, eine Bank vor und zurueck),
Stomp-Ansicht (jeden Effekt-/Scene-Schalter einmal; welche, sagt das Programm anhand der
Displaytexte - Rig-/Bank-/Looper-Schalter werden ausgelassen), optional Setlists/Songs. Dabei
werden alle gefundenen Pfade beobachtet; jede neu erreichte Ansicht wird festgehalten.

Das Log wird nach jedem Teil gespeichert (auch bei Absturz/Abbruch vorhanden).
Texte fuer Tester englisch (oeffentlich), Kommentare deutsch.

    python geraet_diagnose.py            Ausgabe + gefuehrte Runde
    python geraet_diagnose.py --auto     nur auslesen, keine Fragen
    python geraet_diagnose.py --ports    MIDI-Ports anzeigen
"""
import argparse, datetime, json, os, platform, re, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))   # bridge.py liegt im Editor-Ordner
FROZEN = getattr(sys, 'frozen', False)
DATA = getattr(sys, '_MEIPASS', HERE)
OUT_DIR = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else os.getcwd()
try:
    sys.stdout.reconfigure(errors='replace')   # Pfeile in Displaytexten auf alten Konsolen
except Exception:
    pass

try:
    import mido
except ImportError:
    print('Python package "mido" is missing:  pip install mido python-rtmidi')
    sys.exit(1)
from bridge import Bridge, BridgeError, sql_lit

TOOL_VERSION = '2'
E = '/Engine'
PC, RC, FS = E + '/PresetCtrl', E + '/RedirCtrl', E + '/FootSwitch'
BOARD = RC + '/BoardMode'
SLOTS = 11

# Nummerierte Pfade: (Muster, hoechste Nummer). Die Firmware baut sie mit %1 zusammen, im
# Binary stehen sie daher nicht vollstaendig (beim Pedalboard z. B. RigName%1).
NUMBERED = [
    (PC + '/RigName%d', 16), (PC + '/RigColour%d', 16), (PC + '/LoadRig%d', 16),
    (PC + '/SetRigName%d', 16), (PC + '/SetRigColour%d', 16), (PC + '/LoadSetRig%d', 16),
    (PC + '/SetName%d', 12), (RC + '/AccessSet%d', 12), (PC + '/SongName%d', 12),
    (RC + '/Button%d', 16), (RC + '/ButtonText%d', 16), (RC + '/ButtonTextLow%d', 16),
    (RC + '/ButtonCol%d', 16), (RC + '/ButtonTimer%d', 16),
    (RC + '/RawFootswitches/FS%d', 16), (RC + '/On%d', 16), (RC + '/Encoder%d', 8),
    (RC + '/AccessParam%d', 8), (RC + '/ParamName%d', 16), (RC + '/ParamRedirected%d', 16),
    (FS + '/FootSwitch%d', 16), (FS + '/FootSwitchText%d', 16), (FS + '/FootSwitchColour%d', 16),
    (FS + '/FootSwitchOn%d', 16), (FS + '/FootSwitchTimer%d', 16), (FS + '/ModeNew%d', 16),
    (FS + '/Mode%d', 16), (FS + '/Module%d', 16), (FS + '/ModuleList%d', 16),
    (FS + '/Operation%d', 16), (FS + '/OperationList%d', 16), (FS + '/UserFootSwitchText%d', 16),
    (FS + '/SceneNumberOfStates%d', 16), (FS + '/MacroColour%d', 16), (FS + '/State2MacroColour%d', 16),
    (FS + '/SceneState%d', 16), (FS + '/SceneActive%d', 16), (FS + '/Scene%d', 16), (FS + '/State2Scene%d', 16),
    (E + '/Patch/Chain/ModuleType%d', 16), (E + '/Patch/Chain/CanDouble%d', 16),
]
for _p in (1, 2, 3, 4):
    NUMBERED += [(E + '/Pedal%d/ModuleList%%d' % _p, 6), (E + '/Pedal%d/ParamList%%d' % _p, 6),
                 (E + '/Pedal%d/Min%%d' % _p, 6), (E + '/Pedal%d/Max%%d' % _p, 6)]
EXTRA = [PC + '/Rigs/' + n for n in ('LoadedName', 'LoadedID', 'Dirty', 'LoadedProgNum', 'ReceivePresetIndex',
                                      'SendPresetIndex', 'SelectedID', 'LoadedColor')] + \
        [E + '/Pedal%d/PedalMode' % p for p in (1, 2, 3, 4)] + \
        [BOARD, RC + '/CurModule', RC + '/CurModuleWithDoubled', RC + '/AccessRigView',
         RC + '/AccessTuner', RC + '/ExitTuner', RC + '/EditModeSaveRig', PC + '/NextPreset', PC + '/PrevPreset',
         E + '/Patch/Chain/Routing', E + '/Patch/Rig/Tempo', E + '/Patch/Rig/TempoFromMaster',
         E + '/Patch/Amp/Type', E + '/Patch/Cab/CabType', E + '/InputMeter/Current', E + '/InputMeter/Peak',
         E + '/OutputMeterL/Current', E + '/OutputMeterR/Current', E + '/FFTCtrl/TunerString',
         E + '/FFTCtrl/TunerCents', E + '/FFTCtrl/TunerRef', E + '/AudioCtrl/Input/TunerOn',
         E + '/AudioCtrl/Input/TunerMuting', FS + '/LastScene', FS + '/LastSceneState']

# Auswahllisten, die immer gelesen werden (sonst nur kurze Listen, s. MAX_ENTRIES_AUTO)
ENTRIES_ALWAYS = [BOARD, RC + '/CurModule', RC + '/CurModuleWithDoubled', E + '/Patch/Chain/Routing',
                  E + '/Patch/Chain/ModuleType1', E + '/Patch/Amp/Type', E + '/Patch/Cab/CabType']
MAX_ENTRIES_AUTO = 40
MAX_ENTRIES_CALLS = 500
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
    "ls /media/az01-internal/Evil/usb_mnt/Setlists 2>/dev/null | head -30",
    "ls /NAM /media/az01-internal/Evil/usb_mnt/NAM 2>/dev/null | head -5",
    "cat /tmp/mx5bridge/nam-aktiv 2>/dev/null; ls /tmp/mx5bridge 2>/dev/null | head -20",
]

SQL = [
    ("schema", "select type, name, sql from sqlite_master where sql is not null order by name"),
    ("settings", "select name, length(value) as len, case when name in ('db_version', 'RigVersion', 'State_Last') "
                 "then value end as value from settings"),
    ("block_types", "select type, count(*) as n from blocks group by type order by type"),
    ("rig_versions", "select json_extract(content, '$.info.version') as v, count(*) as n from rigs group by v"),
]
# Tabellen, die nicht vollstaendig ins Log kommen (Inhalte bzw. schon oben zusammengefasst)
DB_SKIP = ('rigs', 'blocks', 'settings')
DB_BIG_COLS = ('content', 'data', 'blob', 'value')

# Beobachtung waehrend der gefuehrten Runde: Pfade, die sich von allein aendern
NOISY = re.compile(r'Meter|Tuner|FFTCtrl|/Looper/(RelativPos|LengthText|Remaining)|CPU|Timer|Peak|Current')
# Displaytexte von Schaltern, die beim Schaltertest ausgelassen werden (laden ein Rig/Ansicht wechseln)
BROAD_CHUNK = 80
SKIP_LABEL = re.compile(r'\b(rig|bank|looper|tuner|exit|set|setlist|song|tempo|tap|mode|edit)\b', re.I)
VIEW_PATHS = re.compile(r'/RedirCtrl/(Button|ButtonText|ButtonTextLow|ButtonCol|On)\d+$|/BoardMode$|'
                        r'/PresetCtrl/(RigName|RigColour|SetName|SetRigName|SetRigColour|SongName)\d+$|'
                        r'/Rigs/(LoadedName|LoadedID|Dirty)$|/FootSwitch/(FootSwitchText|FootSwitchColour|'
                        r'FootSwitch|FootSwitchOn)\d+$|/FootSwitch/LastScene')

_COMPACT_JS = ('var P = %s, F = ["value", "unnormalized", "state", "index", "string"], o = []; '
               'function f(t, k) { try { var v = t[k], y = typeof v; '
               '  return y == "number" || y == "boolean" || y == "string" ? v : null; } catch (e) { return null; } } '
               'for (var i = 0; i < P.length; i++) { var p = null; try { p = App.getProperty(P[i]); } catch (e) {} '
               '  var t = p && p.translator; if (!t) { o.push(0); continue; } var r = []; '
               '  for (var k = 0; k < F.length; k++) r.push(f(t, F[k])); o.push(r); } '
               'return JSON.stringify(o);')
_FIELDS = ('value', 'unnormalized', 'state', 'index', 'string')
_EXIST_JS = ('var P = %s, o = {}; for (var i = 0; i < P.length; i++) { try { var p = App.getProperty(P[i]); '
             'o[P[i]] = !p ? "none" : (p.translator ? "translator" : "property"); } catch (e) { o[P[i]] = "error " + e; } } '
             'return JSON.stringify(o);')
_SCENE_JS = ('var N = %s, o = {}; for (var i = 0; i < N.length; i++) { try { '
             'var t = App.getProperty(N[i]).translator, l = []; '
             'for (var k = 0; k < %d; k++) { var x = t.slot(k); l.push([String(x.effect), Number(x.mode)]); } o[N[i]] = l; '
             '} catch (e) { o[N[i]] = "error " + e; } } return JSON.stringify(o);')


class Log:
    """Sammelt alles fuer die Logdatei; Ausgaben gehen zusaetzlich auf die Konsole."""
    def __init__(self):
        self.data = {'tool': 'HeadRush Bridge device diagnosis %s' % TOOL_VERSION,
                     'time': datetime.datetime.now().isoformat(timespec='seconds'),
                     'pc': platform.platform(), 'python': sys.version.split()[0], 'errors': []}
        self.lines = []
        self.path = None

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


def guarded(log, where, fn, *a):
    """Ein Teil der Diagnose; ein Fehler darin bricht die anderen nicht ab (Verbindungsverlust schon)."""
    try:
        return fn(*a)
    except KeyboardInterrupt:
        raise
    except Exception as e:  # noqa: BLE001 - alles soll in die Logdatei
        log.error(where, e)
        if isinstance(e, BridgeError) and str(e).startswith(('Keine Antwort', 'MIDI-Port')):
            raise
        return None


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
    return list(dict.fromkeys(paths))


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
                    '  - do not switch on USB audio or USB transfer mode on the device,\n'
                    '  - close MX-Edit if it is open.\n'
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
    br = None
    for i in range(30):
        try:
            if br is None:
                br = Bridge(pin, pout)
            br.ping()
            return br
        except BridgeError as e:
            if i == 0:
                log.say('Waiting for the bridge to answer (up to 30 s) ...')
            if 'Port' in str(e) and br is None:   # Port belegt (z. B. MX-Edit offen)
                log.say('  The MIDI port is busy - is MX-Edit or another MIDI program open? Please close it.')
            time.sleep(1)
    if br:
        br.close()
    raise BridgeError('The device does not answer bridge requests. Is the HeadRush Bridge firmware installed? '
                      'If you just switched it on, wait a minute and start this program again.')


# ---------- Lesen ----------
def compact(br, paths, group=250):
    """Werte vieler Pfade in wenigen evals (nur value/unnormalized/state/index/string); fehlende
    Pfade fehlen im Ergebnis. Faellt auf get_many zurueck, wenn eval scheitert."""
    out = {}
    paths = list(dict.fromkeys(paths))
    for i in range(0, len(paths), group):
        part = paths[i:i + group]
        try:
            vals = json.loads(br.eval(_COMPACT_JS % json.dumps(part)))
        except (BridgeError, ValueError):
            for p, v in br.get_many(part).items():
                if isinstance(v, dict) and v.get('ok'):
                    out[p] = {k: v[k] for k in _FIELDS if k in v}
            continue
        for p, v in zip(part, vals):
            if v:
                out[p] = {k: x for k, x in zip(_FIELDS, v) if x is not None}
    return out


def probe_engine(br, log):
    paths = all_paths(log)
    log.say('Reading %d engine paths ...' % len(paths))
    t = time.time()
    res = {}
    try:
        res = br.get_many(paths)
    except BridgeError as e:
        log.error('get_many', e)
    found = {p: i for p, i in res.items() if isinstance(i, dict) and i.get('ok')}
    # Scene-Presets je Fussschalter (n aus ModeNew<n>) - 2 x 11 Pfade je Schalter
    nums = [n for n in range(1, 17) if FS + '/ModeNew%d' % n in found]
    more = ['%s/%sScene%dSlot%dPreset' % (FS, st, n, k) for n in nums for st in ('', 'State2')
            for k in range(1, SLOTS + 1)]
    if more:
        try:
            r = br.get_many(more)
            found.update({p: i for p, i in r.items() if isinstance(i, dict) and i.get('ok')})
            paths += more
        except BridgeError as e:
            log.error('scene presets', e)
    log.data['engine'] = found
    log.data['engine_missing'] = sorted(p for p in paths if p not in found)
    log.say('  %d exist, %d do not (%.1f s)' % (len(found), len(paths) - len(found), time.time() - t))
    recheck_gaps(br, log, found)

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


def recheck_gaps(br, log, found):
    """Luecken in nummerierten Reihen (z. B. FootSwitch1, 3, 5 da, 2 und 4 nicht) einzeln pruefen:
    gibt es das Property ueberhaupt (App.getProperty), und was antwortet ein einzelnes get?"""
    gaps = []
    for pat, n in NUMBERED:
        have = [i for i in range(1, n + 1) if pat % i in found]
        if have:
            gaps += [pat % i for i in range(1, max(have)) if i not in have]
    out = {}
    if gaps:
        try:
            out = json.loads(br.eval(_EXIST_JS % json.dumps(gaps[:300])))
        except (BridgeError, ValueError) as e:
            log.error('gap check', e)
        for p in gaps[:40]:
            try:
                single = br.get(p)
            except BridgeError as e:
                single = {'error': str(e)}
            if isinstance(single, dict) and single.get('ok'):
                found[p] = single
            out[p] = {'exists': out.get(p), 'get': single}
    log.data['gaps'] = out
    if gaps:
        log.say('  %d gaps in numbered paths checked one by one' % len(gaps))


def probe_hardware(br, log, found):
    """Scene-Plaetze aller Fussschalter (Zustand 1 und 2): je Platz (Block, Modus)."""
    scenes = [p for p in found if re.search(r'/FootSwitch/(State2)?Scene\d+$', p)]
    if not scenes:
        return
    r = json.loads(br.eval(_SCENE_JS % (json.dumps(sorted(scenes)), SLOTS)))
    log.data['scenes'] = r
    log.say('  scene slots of %d footswitch states read' % len(r))


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
    log.say('Device:', log.data['device'] or 'unknown', '(%s)' % (comp or '?'))


def sql_all(br, q, page=None):
    """Alle Zeilen einer Abfrage, seitenweise (aeltere Bruecken: Antwort hoechstens ~48 KB)."""
    page = page or (2000 if br.long else 200)
    rows, off = [], 0
    while True:
        r = br.sql('%s limit %d offset %d' % (q, page, off))
        rows += r
        if len(r) < page:
            return rows
        off += page


def skeleton(o, key=''):
    """Aufbau eines Rigs ohne Einstellungen: Schluessel und Typen bleiben, Werte werden zu
    Platzhaltern (Text: Laenge). Fuer den Vergleich der Rig-Formate MX5/Pedalboard/Gigboard."""
    if isinstance(o, dict):
        return {k: skeleton(v, k) for k, v in o.items()}
    if isinstance(o, list):
        if key == 'childorder':          # Parameternamen = Aufbau, keine Einstellung
            return o
        return {'<list>': len(o), 'first': skeleton(o[0], key) if o else None}
    if key in ('type', 'version', 'valueType'):
        return o
    if isinstance(o, bool):
        return '<bool>'
    if isinstance(o, (int, float)):
        return '<num>'
    if isinstance(o, str):
        return '<str %d>' % len(o)
    return None if o is None else '<%s>' % type(o).__name__


def probe_db(br, log, found):
    if not br.v3:
        return
    db = {}
    log.data['db'] = db
    for name, q in SQL:
        try:
            db[name] = br.sql(q)
        except BridgeError as e:
            db[name] = {'error': str(e)}
    tables = [r['name'] for r in br.sql("select name from sqlite_master where type = 'table' "
                                        "and name not like 'sqlite_%' order by name")]
    counts = {}
    for t in tables:
        try:
            counts[t] = br.sql('select count(*) as n from "%s"' % t)[0]['n']
        except BridgeError as e:
            counts[t] = str(e)
    db['counts'] = counts
    log.say('Database: ' + ', '.join('%s %s' % (n, t) for t, n in counts.items()))
    # Rig-Liste: nur Namen und Ordnung (All-Rigs-Reihenfolge = rowid), keine Inhalte
    try:
        db['rigs'] = sql_all(br, "select rowid as r, id, name, show_order, color, prog_num, is_readonly, "
                                 "json_extract(content, '$.info.version') as v from rigs order by rowid")
    except BridgeError as e:
        log.error('rig list', e)
        db['rigs'] = sql_all(br, 'select rowid as r, id, name from rigs order by rowid')
    # Setlist-/Song-Tabellen und alles Unbekannte vollstaendig, ohne grosse Spalten
    db['tables'] = {}
    for t in tables:
        if t in DB_SKIP:
            continue
        try:
            cols = [r['name'] for r in br.sql("select name from pragma_table_info('%s')" % t)]
            keep = [c for c in cols if c.lower() not in DB_BIG_COLS] or cols[:1]
            db['tables'][t] = {'columns': cols,
                               'rows': sql_all(br, 'select rowid as _rowid, %s from "%s" order by rowid'
                                               % (', '.join('"%s"' % c for c in keep), t))}
        except BridgeError as e:
            db['tables'][t] = {'error': str(e)}
    # Aufbau des geladenen Rigs + je Rig-Version eines Beispiels
    ids = []
    loaded = (found.get(PC + '/Rigs/LoadedID') or {}).get('string')
    if loaded:
        ids.append(('loaded', loaded))
    for row in db.get('rig_versions') or []:
        if isinstance(row, dict):
            r = br.sql("select id from rigs where json_extract(content, '$.info.version') is %s limit 1"
                       % (sql_lit(row['v']) if row.get('v') is not None else 'null'))
            if r and r[0]['id'] != loaded:
                ids.append(('version %s' % row.get('v'), r[0]['id']))
    db['rig_structure'] = {}
    for label, rid in ids[:4]:
        try:
            r = br.sql('select content from rigs where id = %s' % sql_lit(rid))
            db['rig_structure'][label] = skeleton(json.loads(r[0]['content'])) if r else 'not found'
        except (BridgeError, ValueError, KeyError) as e:
            db['rig_structure'][label] = 'error %s' % e
    if br.v4:
        try:
            db['status'] = br.action('status')
        except BridgeError as e:
            db['status'] = {'error': str(e)}


def nums(found, pat, n=16):
    return [i for i in range(1, n + 1) if pat % i in found]


def summary(log, found):
    """Kurze lesbare Zusammenfassung oben in der Logdatei."""
    s = {
        'bank_rig_slots': nums(found, PC + '/RigName%d'),
        'setlist_bank_slots': nums(found, PC + '/SetRigName%d'),
        'setlist_names_shown': nums(found, PC + '/SetName%d'),
        'footswitches': nums(found, FS + '/FootSwitch%d'),
        'footswitch_modes': nums(found, FS + '/ModeNew%d'),
        'raw_footswitches': nums(found, RC + '/RawFootswitches/FS%d'),
        'display_buttons': nums(found, RC + '/ButtonText%d'),
        'encoders': nums(found, RC + '/Encoder%d'),
        'chain_slots': nums(found, E + '/Patch/Chain/ModuleType%d'),
        'pedals': [p for p in (1, 2, 3, 4) if (E + '/Pedal%d/ModuleList1' % p) in found],
        'board_modes': log.data.get('entries', {}).get(BOARD),
        'board_mode_now': (found.get(BOARD) or {}).get('string'),
    }
    log.data['summary'] = s
    log.say('')
    for k, v in s.items():
        log.say('  %-20s %s' % (k, v))
    return s


# ---------- gefuehrte Runde: beobachten, was der Tester am Geraet tut ----------
def board_mode(br):
    try:
        return (br.get(BOARD) or {}).get('string') or ''
    except BridgeError:
        return ''


def wait_for_view(br, log, views, how, timeout=240):
    """Warten, bis das Geraet eine der Ansichten views zeigt (BoardMode). Liefert die Ansicht oder
    '' (Taste/Zeit um). Ist sie schon da, wird nichts gefragt."""
    views = (views,) if isinstance(views, str) else tuple(views)
    key_pressed()   # Reste der letzten Eingabe (Enter nach input()) verwerfen
    now = board_mode(br)
    if now in views:
        return now
    log.say('   -> Please switch the device to %s.\n'
            '      This continues by itself as soon as the device shows it. (Press any key to skip.)' % how)
    t0 = time.time()
    while time.time() - t0 < timeout:
        now = board_mode(br)
        if now in views:
            log.say('      OK, detected.')
            return now
        if key_pressed():
            break
        time.sleep(0.3)
    log.say('      Skipped.')
    return ''


class Watcher:
    """Pollt schnell die Schalter-Eingaenge + Ansicht und etwas langsamer alle gefundenen Pfade;
    zeichnet Aenderungen mit Zeit auf. Pfade, die sich ohne Zutun aendern (Meter, Zeiten), werden
    vorab in calibrate() erkannt (bevor eine Anweisung erscheint) und danach uebergangen. Jede neu
    erreichte Ansicht wird festgehalten."""
    def __init__(self, br, log, found):
        self.br, self.log = br, log
        self.fast = [p for p in found if '/RawFootswitches/FS' in p] + [BOARD]
        self.broad = [p for p in found if not NOISY.search(p) and p not in self.fast]
        self.view_paths = [p for p in found if VIEW_PATHS.search(p)]
        self.last, self.noisy = {}, set()
        self.views = log.data.setdefault('views', {})

    def calibrate(self, secs=2.0):
        """Alle Pfade einige Male lesen; was sich ohne Zutun aendert, gilt als Rauschen."""
        first, t0 = compact(self.br, self.broad), time.time()
        while time.time() - t0 < secs:
            for p, v in compact(self.br, self.broad).items():
                if first.get(p) != v:
                    self.noisy.add(p)
        self.broad = [p for p in self.broad if p not in self.noisy]

    def snapshot(self, label):
        try:
            v = compact(self.br, self.view_paths)
        except BridgeError as e:
            self.log.error('snapshot ' + label, e)
            return {}
        self.views[label] = {p.replace(E, ''): x.get('string', x.get('value')) for p, x in v.items()}
        return v

    def run(self, label, idle_stop=8.0, max_s=150.0, presses=True, until_view=None):
        events, t0 = [], time.time()
        last_change, seen, left = None, [], False
        self.last = compact(self.br, self.fast + self.broad)
        # Die vielen uebrigen Pfade in Haeppchen reihum, damit die Schalter-Eingaenge alle ~70 ms
        # gelesen werden (ein Druck dauert ~0.1-0.4 s; ein Durchlauf aller Pfade ~0.3 s)
        chunks = [self.broad[i:i + BROAD_CHUNK] for i in range(0, len(self.broad), BROAD_CHUNK)] or [[]]
        k = 0
        key_pressed()   # Reste der letzten Eingabe verwerfen, sonst endet die Aufnahme sofort
        while True:
            now = time.time()
            paths = self.fast + chunks[k % len(chunks)]
            k += 1
            try:
                cur = compact(self.br, paths)
            except BridgeError as e:
                events.append({'t': round(now - t0, 2), 'error': str(e)})
                if str(e).startswith(('Keine Antwort', 'MIDI-Port')):
                    raise
                time.sleep(0.3)
                cur = {}
            for p, v in cur.items():
                old = self.last.get(p)
                if old == v:
                    continue
                self.last[p] = v
                events.append({'t': round(now - t0, 2), 'path': p, 'from': old, 'to': v})
                if p.startswith(RC + '/RawFootswitches/FS'):
                    if v.get('state') is True:
                        n = p.rsplit('FS', 1)[1]
                        together = last_change and now - last_change < 0.15 and seen
                        last_change = now
                        if together:
                            seen[-1] += '+' + n
                            if presses:
                                print('      ... together with switch input %s' % n, flush=True)
                        else:
                            seen.append(n)
                            if presses:
                                print('      press %d detected (switch input %s)' % (len(seen), n), flush=True)
                elif p == BOARD:
                    view = v.get('string') or '?'
                    print('      view: %s' % view, flush=True)
                    last_change = now
                    if view not in self.views:
                        self.snapshot(view)
                else:
                    last_change = now
            if (key_pressed() and now - t0 > 1.0) or now - t0 > max_s or (last_change and now - last_change > idle_stop):
                break
            # until_view: Ende, sobald das Geraet nach einem Abstecher wieder diese Ansicht zeigt
            view = (self.last.get(BOARD) or {}).get('string')
            left = left or bool(until_view and view and view != until_view)
            if left and view == until_view and last_change and now - last_change > 2.0:
                break
            time.sleep(0.03)
        w = self.log.data.setdefault('watch', {})
        w[label] = events
        self.log.data['noisy_paths'] = sorted(self.noisy)
        changed = sorted({e['path'] for e in events if 'path' in e})
        self.log.say('   %d changes in %d paths' % (len(events), len(changed)))
        pm = press_map(events)
        self.log.data.setdefault('press_map', {})[label] = pm
        for p in pm:
            self.log.say('   %-6s -> %s' % (p['raw'], ', '.join(p['effects']) or '(nothing seen)'))
        return events


def press_map(events):
    """Je Druck die Aenderungen bis zum naechsten Druck, hoechstens 1.5 s: welche FootSwitch<n>
    angehen, welches Rig geladen wird, welche Szene/Ansicht, welche Aktion (NOOP -> OP, z. B.
    NextBank). Gleichzeitig gedrueckte Schalter (Down innerhalb 0.15 s; am MX5 blaettert FS1+FS2 /
    FS2+FS3 die Bank) zaehlen als ein Druck "FS1+2". Nach einem Rig-Wechsel wird nichts mehr
    zugeordnet (das sind Werte des neuen Rigs)."""
    downs = [e for e in events if e.get('path', '').startswith(RC + '/RawFootswitches/FS')
             and (e.get('to') or {}).get('state') is True]
    groups = []
    for d in downs:
        if groups and d['t'] - groups[-1][0]['t'] <= 0.15:
            groups[-1].append(d)
        else:
            groups.append([d])
    out = []
    for i, g in enumerate(groups):
        t = g[0]['t']
        end = min(groups[i + 1][0]['t'] if i + 1 < len(groups) else float('inf'), t + 1.5)
        eff, loaded = [], False
        for e in events:
            if loaded or not (t <= e.get('t', -1) < end) or 'path' not in e:
                continue
            p, to = e['path'], e.get('to') or {}
            name = p.rsplit('/', 1)[1]
            if re.match(r'FootSwitch(On)?\d+$', name):
                eff.append('%s %s' % (name, 'on' if to.get('state') else 'off'))
            elif name == 'LastScene':
                eff.append('LastScene ' + str(to.get('string')))
            elif name in ('LoadedName', 'LoadedID'):
                if name == 'LoadedName':
                    eff.append('loads ' + str(to.get('string')))
                loaded = True
            elif name == 'BoardMode':
                eff.append('view ' + str(to.get('string')))
            elif re.match(r'(RigName|SetName|SetRigName|SongName)1$', name):
                eff.append('%s -> %s' % (name, to.get('string')))
            elif to.get('string') == 'OP' and '/RawFootswitches/' not in p:
                eff.append(name)
        raw = 'FS' + '+'.join(d['path'].rsplit('FS', 1)[1] for d in g)
        out.append({'raw': raw, 't': t, 'effects': eff})
    return out


def labels(found, br):
    """Displaytext je Schalter-Eingang {n: text} (RedirCtrl/ButtonText<n>)."""
    ns = nums(found, RC + '/ButtonText%d')
    try:
        cur = compact(br, [RC + '/ButtonText%d' % n for n in ns])
    except BridgeError:
        return {}
    return {n: (cur.get(RC + '/ButtonText%d' % n) or {}).get('string') or '' for n in ns}


def show_board(log, lab, raw):
    """Schalter wie am Geraet zeigen: bei mehr als 6 Eingaengen zwei Reihen."""
    ns = raw or sorted(lab)
    rows = [ns[:len(ns) // 2], ns[len(ns) // 2:]] if len(ns) > 6 else [ns]
    for row in rows:
        log.say('      ' + '  '.join('[%d %s]' % (n, lab.get(n) or '-') for n in row))


def step_rig(br, log, found, w, q):
    log.say('\nStep 1 of 3 - Rig view')
    if not wait_for_view(br, log, 'Rig', 'the RIG view (the list of rigs in banks)'):
        return
    w.snapshot('Rig')
    names = nums(found, PC + '/RigName%d')
    cur = compact(br, [PC + '/RigName%d' % i for i in names])
    log.say('   The bridge reads these rig names for the bank on the display:')
    log.say('      ' + ' | '.join((cur.get(PC + '/RigName%d' % i) or {}).get('string') or '-' for i in names))
    q['rig_names_match'] = ask('   Are these the names on the display, in the same order? [y/n] ')
    lab = labels(found, br)
    bank = [(n, t) for n, t in lab.items() if re.search(r'bank', t, re.I)]
    which = ' and '.join('"%s" (switch %d)' % (t, n) for n, t in bank) or \
        'the switches for bank down and bank up (on some devices two switches together)'
    log.say('   Now page through the banks: press %s, once each.\n'
            '   This only pages through the banks; it does not load a rig.\n'
            '   (Press any key when done - it also ends by itself 6 seconds after the last press.)' % which)
    w.run('rig_view_banks', idle_stop=6.0, max_s=90.0)


def step_stomp(br, log, found, w, q):
    log.say('\nStep 2 of 3 - Footswitches')
    if not wait_for_view(br, log, 'Stomp', 'the STOMP view (the view where the footswitches switch effects '
                                           'and scenes on and off)'):
        return
    w.snapshot('Stomp')
    raw = nums(found, RC + '/RawFootswitches/FS%d')
    lab = labels(found, br)
    q['footswitch_inputs'] = len(raw)
    if lab:
        log.say('   The display shows these switches (switch number and text):')
        show_board(log, lab, raw)
        press = [n for n in (raw or sorted(lab)) if not SKIP_LABEL.search(lab.get(n) or '')]
        skip = [n for n in (raw or sorted(lab)) if n not in press]
        log.say('   Press these switches one after another, about a second apart: %s'
                % ', '.join(str(n) for n in press))
        if skip:
            log.say('   Leave out: %s (they change the rig, the view or the tempo).'
                    % ', '.join('%d %s' % (n, lab.get(n)) for n in skip))
    else:
        log.say('   Press each switch that turns an effect or a scene on/off, from left to right\n'
                '   (top row first). Leave out switches that change the rig or the view.')
    log.say('   Every press is confirmed here. The test ends 8 seconds after your last press.\n'
            '   Afterwards you can press the switches again to get your sound back as it was.')
    w.run('footswitches_stomp')
    if not log.data['press_map'].get('footswitches_stomp'):
        log.say('   No press was detected. That is useful information too.')


def step_setlists(br, log, found, w, q):
    counts = (log.data.get('db') or {}).get('counts') or {}
    if not counts.get('setlists'):
        return
    log.say('\nStep 3 of 3 - Setlists (optional)')
    log.say('   Your device has %s setlist(s). This step watches how the device shows setlists and songs.\n'
            '   Opening a setlist loads a rig - save unsaved changes first.' % counts.get('setlists'))
    if ask('   Do this step? [y/n] ').lower()[:1] != 'y':
        q['setlist_step'] = 'skipped'
        return
    q['setlist_step'] = 'done'
    # Keine bestimmte Ansicht verlangen: wie man an Pedalboard/Gigboard zu den Setlists kommt, ist
    # nicht bekannt - die Ansichten (BoardMode) erkennt der Watcher selbst.
    log.say('   Now open one of your setlists the way you normally do (footswitches or touchscreen),\n'
            '   switch to the next song or rig once, then go back to the rig view.\n'
            '   The program notices every screen you open and stops by itself when you are back in the\n'
            '   rig view. (Or press any key when done.)')
    w.run('setlists', idle_stop=25.0, max_s=240.0, until_view='Rig')


def interactive(br, log, found):
    """Gefuehrter Teil: nur was das Programm nicht selbst herausfinden kann. Die Ansicht wird selbst
    erkannt (BoardMode); in der Stomp-Ansicht laedt ein Effektschalter kein Rig."""
    q = log.data.setdefault('answers', {})
    log.say('\n========== Part 2: watching while you use the device (about 2 minutes) ==========')
    log.say('This program still changes nothing. It only watches what you do on the device.')
    if (found.get(PC + '/Rigs/Dirty') or {}).get('state'):
        log.say('Note: the current rig has unsaved changes. Nothing here saves or discards them.')
    w = Watcher(br, log, found)
    guarded(log, 'calibrate', w.calibrate)
    for step in (step_rig, step_stomp, step_setlists):
        guarded(log, step.__name__, step, br, log, found, w, q)
        save(log)
    q['notes'] = ask('\nAnything else you noticed? (one line, optional): ')


def save(log):
    """Log schreiben (nach jedem Teil, damit bei Absturz/Abbruch etwas da ist)."""
    if not log.path:
        dev = ''.join(c for c in (log.data.get('device') or 'device') if c.isalnum())[:20] or 'device'
        name = 'HeadRush_Bridge_Diagnose_%s_%s.txt' % (dev, datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
        home = os.path.expanduser('~')
        # neben der EXE; ist der Ordner schreibgeschuetzt (z. B. Programme), dann Desktop / Dokumente / Temp
        for d in (OUT_DIR, os.path.join(home, 'Desktop'), os.path.join(home, 'Documents'), home,
                  os.environ.get('TEMP', '')):
            if d and os.path.isdir(d) and os.access(d, os.W_OK):
                log.path = os.path.join(d, name)
                break
    text = '\n'.join(log.lines) + '\n\n===== JSON =====\n' + \
        json.dumps(log.data, indent=1, ensure_ascii=False, sort_keys=True) + '\n'
    for _ in range(2):
        try:
            with open(log.path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
            return log.path
        except (OSError, TypeError):
            log.path = os.path.join(os.environ.get('TEMP', os.path.expanduser('~')), os.path.basename(log.path or 'x'))
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
    log.say('The log contains the names of your rigs, setlists and songs, the device settings and the layout\n'
            'of a rig (which settings exist, not their values). No audio, no rig sounds.\n')
    br = None
    rc = 0
    try:
        br = open_bridge(log, (a.pin, a.pout) if a.pin and a.pout else None, wait=not a.auto)
        log.data['bridge'] = {'version': br.version, 'vnum': br.vnum}
        log.say('Bridge:', br.version)
        log.say('\n========== Part 1: reading the device (about 20 seconds) ==========')
        guarded(log, 'system', probe_shell, br, log)
        found = guarded(log, 'engine', probe_engine, br, log) or {}
        guarded(log, 'scenes', probe_hardware, br, log, found)
        guarded(log, 'database', probe_db, br, log, found)
        summary(log, found)
        save(log)
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
    log.say('\n========== Done ==========')
    path = save(log)
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
