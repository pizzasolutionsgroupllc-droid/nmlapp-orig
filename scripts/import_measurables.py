#!/usr/bin/env python3
"""
Import all combine, pro day, and RAS measurables from
imports/footballsheetscombineproday.xlsx into draft_prospects.

Combine and pro day data are stored in SEPARATE columns so the
player modal can show them side-by-side for comparison.

Sheets expected in the XLSX:
  - 'Combine data'   : School, Jersey, Player, Pos, Ht, Wt, Hand, Arm, Wing,
                       10, 20, 40, Bench, 3-Cone, Shuttle, Vertical, Broad, Details
  - 'Pro day data'   : School, Player, Pos, Ht, Wt, Hand, Arm, Wing,
                       10, 20, 40, Bench, 3 Cone, Shuttle, Vertical, Broad, Notes, Details
  - 'RAS'            : Link (HTML <a>), Name, Pos, Year, College, RAS, ALLTIME

Usage:
    python3 scripts/import_measurables.py [--year 2026] [--dry-run]
"""
import openpyxl, sqlite3, os, sys, re, unicodedata

YEAR    = 2026
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'nml.db')
XLSX    = os.path.join(os.path.dirname(__file__), '..', 'imports', 'footballsheetscombineproday.xlsx')


# ── Measurement decoders ──────────────────────────────────────────────────────

def decode_height(val):
    """
    6027 → "6'2 7/8\""
    Format: digit0=feet, digits1-2=whole inches, digit3=eighths numerator
    """
    if val is None:
        return None
    try:
        s = str(int(val)).zfill(4)
        ft      = int(s[0])
        inches  = int(s[1:3])
        eighths = int(s[3])
        if eighths == 0:
            return f"{ft}'{inches}\""
        return f"{ft}'{inches} {eighths}/8\""
    except Exception:
        return None

def decode_body_measure(val):
    """
    Decode hand / arm / wingspan.
    Pattern: all digits except last two encode whole inches;
             second-to-last = eighths numerator; last digit is always 8 or 0.
    Examples: 928→9.25  3178→31.875  7828→78.25  3100→31.0
    """
    if val is None:
        return None
    try:
        s = str(int(val))
        if len(s) < 2:
            return float(val)
        numerator = int(s[-2])   # eighths numerator
        # last digit: 8 means fraction present; 0 means exact
        whole = int(s[:-2]) if len(s) > 2 else 0
        return round(whole + numerator / 8.0, 3)
    except Exception:
        return None

def decode_broad(val):
    """
    Broad jump encoded as feet*100 + inches.
    909  → "9'9\""   (9 ft 9 in)
    1005 → "10'5\""  (10 ft 5 in)
    Returns a display string.
    """
    if val is None:
        return None
    try:
        v = int(val)
        feet   = v // 100
        inches = v % 100
        return f"{feet}'{inches}\""
    except Exception:
        return None

def safe_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except Exception:
        return None

def safe_int(val):
    if val is None:
        return None
    try:
        return int(float(val))
    except Exception:
        return None


# ── Name normalisation ────────────────────────────────────────────────────────

def norm(name):
    if not name:
        return ''
    name = unicodedata.normalize('NFKD', str(name))
    name = name.encode('ascii', 'ignore').decode('ascii')
    name = re.sub(r'[^a-z ]', '', name.lower())
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', name).strip()
    return name

def norm_school(s):
    return re.sub(r'[^a-z]', '', (s or '').lower())


# ── Sheet parsers ─────────────────────────────────────────────────────────────

def parse_combine(ws):
    """
    Cols: School(0) Jersey(1) Player(2) Pos(3) Ht(4) Wt(5) Hand(6) Arm(7)
          Wing(8) 10(9) 20(10) 40(11) Bench(12) 3-Cone(13) Shuttle(14)
          Vertical(15) Broad(16) Details(17)
    """
    records = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = row[2]
        if not name or not isinstance(name, str):
            continue
        records.append({
            'name':          name,
            'school':        str(row[0] or ''),
            'height':        decode_height(row[4]),
            'weight':        safe_int(row[5]),
            'hand_combine':  decode_body_measure(row[6]),
            'arm_combine':   decode_body_measure(row[7]),
            'wing_combine':  decode_body_measure(row[8]),
            'ten_combine':   safe_float(row[9]),
            'twenty_combine':safe_float(row[10]),
            'forty_combine': safe_float(row[11]),
            'bench':         safe_int(row[12]),
            'three_cone':    safe_float(row[13]),
            'shuttle':       safe_float(row[14]),
            'vertical':      safe_float(row[15]),
            'broad':         decode_broad(row[16]),
        })
    return records

def parse_proday(ws):
    """
    Cols: School(0) Player(1) Pos(2) Ht(3) Wt(4) Hand(5) Arm(6) Wing(7)
          10(8) 20(9) 40(10) Bench(11) 3 Cone(12) Shuttle(13) Vertical(14)
          Broad(15) Notes(16) Details(17)
    """
    records = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = row[1]
        if not name or not isinstance(name, str):
            continue
        records.append({
            'name':           name,
            'school':         str(row[0] or ''),
            'height_proday':  decode_height(row[3]),
            'weight_proday':  safe_int(row[4]),
            'hand_proday':    decode_body_measure(row[5]),
            'arm_proday':     decode_body_measure(row[6]),
            'wing_proday':    decode_body_measure(row[7]),
            'ten_proday':     safe_float(row[8]),
            'twenty_proday':  safe_float(row[9]),
            'forty_proday':   safe_float(row[10]),
            'bench_proday':   safe_int(row[11]),
            'three_cone_proday': safe_float(row[12]),
            'shuttle_proday': safe_float(row[13]),
            'vertical_proday':safe_float(row[14]),
            'broad_proday':   decode_broad(row[15]),
        })
    return records

def parse_ras(ws):
    """
    Cols: Link(0) Name(1) Pos(2) Year(3) College(4) RAS(5) ALLTIME(6)
    Extracts the href URL from the HTML <a> tag in the Link column.
    """
    url_re = re.compile(r'href=["\']([^"\']+)["\']')
    records = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = row[1]
        if not name or not isinstance(name, str):
            continue
        link_html = str(row[0] or '')
        url_match = url_re.search(link_html)
        url = url_match.group(1).replace('&amp;', '&') if url_match else None
        ras_val = safe_float(row[5])
        if ras_val is not None and not (0 <= ras_val <= 10.1):
            ras_val = None
        records.append({
            'name':     name,
            'school':   str(row[4] or ''),
            'ras':      ras_val,
            'ras_link': url,
        })
    return records


# ── Build lookup indexes ──────────────────────────────────────────────────────

def build_index(records, name_key='name', school_key='school'):
    by_name   = {}
    by_both   = {}
    for r in records:
        nn = norm(r[name_key])
        ns = norm_school(r[school_key])
        if nn:
            by_name.setdefault(nn, r)   # first match wins
            by_both[(nn, ns)] = r
    return by_name, by_both

def lookup(by_name, by_both, prospect_name, prospect_school):
    nn = norm(prospect_name)
    ns = norm_school(prospect_school or '')
    return by_both.get((nn, ns)) or by_name.get(nn)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    year    = YEAR
    dry_run = '--dry-run' in sys.argv
    for arg in sys.argv[1:]:
        if arg.startswith('--year='):
            year = int(arg.split('=')[1])

    print(f"Importing measurables for {year} ({'DRY RUN' if dry_run else 'LIVE'})")

    if not os.path.exists(XLSX):
        print(f"ERROR: {XLSX} not found")
        sys.exit(1)

    wb = openpyxl.load_workbook(XLSX)
    combine = parse_combine(wb['Combine data'])
    proday  = parse_proday(wb['Pro day data'])
    ras     = parse_ras(wb['RAS'])

    print(f"Loaded: {len(combine)} combine | {len(proday)} pro day | {len(ras)} RAS")

    c_by_name, c_by_both = build_index(combine)
    p_by_name, p_by_both = build_index(proday)
    r_by_name, r_by_both = build_index(ras)

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    prospects = conn.execute(
        'SELECT id, name, school FROM draft_prospects WHERE year=?', (year,)
    ).fetchall()
    print(f"DB prospects: {len(prospects)}")

    updated      = 0
    matched_c    = 0
    matched_p    = 0
    matched_r    = 0
    no_match     = 0
    unmatched    = []

    # All fields we might update, grouped for clarity
    COMBINE_FIELDS  = ['height', 'weight', 'hand_combine', 'arm_combine', 'wing_combine',
                       'ten_combine', 'twenty_combine', 'forty_combine',
                       'bench', 'three_cone', 'shuttle', 'vertical', 'broad']
    PRODAY_FIELDS   = ['height_proday', 'weight_proday', 'hand_proday', 'arm_proday',
                       'wing_proday', 'ten_proday', 'twenty_proday', 'forty_proday',
                       'bench_proday', 'three_cone_proday', 'shuttle_proday',
                       'vertical_proday', 'broad_proday']
    RAS_FIELDS      = ['ras', 'ras_link']

    for pid, pname, pschool in prospects:
        c_rec = lookup(c_by_name, c_by_both, pname, pschool)
        p_rec = lookup(p_by_name, p_by_both, pname, pschool)
        r_rec = lookup(r_by_name, r_by_both, pname, pschool)

        if not c_rec and not p_rec and not r_rec:
            no_match += 1
            unmatched.append(pname)
            continue

        if c_rec: matched_c += 1
        if p_rec: matched_p += 1
        if r_rec: matched_r += 1

        fields = {}

        if c_rec:
            for f in COMBINE_FIELDS:
                v = c_rec.get(f)
                if v is not None:
                    fields[f] = v

        if p_rec:
            for f in PRODAY_FIELDS:
                v = p_rec.get(f)
                if v is not None:
                    fields[f] = v

        if r_rec:
            for f in RAS_FIELDS:
                v = r_rec.get(f)
                if v is not None:
                    fields[f] = v

        if not fields:
            continue

        if dry_run:
            print(f"  {pname}: {list(fields.keys())}")
        else:
            sets = ', '.join(f"{k}=?" for k in fields)
            vals = list(fields.values()) + [pid]
            conn.execute(
                f"UPDATE draft_prospects SET {sets}, updated_at=datetime('now') WHERE id=?",
                vals
            )
        updated += 1

    if not dry_run:
        conn.commit()
    conn.close()

    print(f"\n{'[DRY RUN] Would update' if dry_run else 'Updated'}: {updated} prospects")
    print(f"  Combine matched: {matched_c}")
    print(f"  Pro day matched: {matched_p}")
    print(f"  RAS matched:     {matched_r}")
    print(f"  No match at all: {no_match}")

    if unmatched:
        print(f"\nFirst 20 unmatched prospects (no data in any source):")
        for n in unmatched[:20]:
            print(f"  {n}")

if __name__ == '__main__':
    main()
