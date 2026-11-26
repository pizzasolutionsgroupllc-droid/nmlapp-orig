import sqlite3, csv, unicodedata

def norm(s):
    s = unicodedata.normalize('NFD', str(s or ''))
    result = ''
    for ch in s:
        if unicodedata.category(ch) != 'Mn':
            result += ch
    s = result
    return ''.join(c for c in s.lower() if c.isalpha() or c == ' ').strip()

DB = '/sessions/gifted-compassionate-wright/mnt/nmlapp/data/nml-backup-20260417-115213.db'
CSV_PATH = '/sessions/gifted-compassionate-wright/mnt/nmlapp/newfranchiseratings.csv'

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute('SELECT id, first_name, last_name, position, age, madden_id, nml_team_id, nfl_team FROM players')
all_p = c.fetchall()
db_by_madden = {}
db_by_name = {}
for r in all_p:
    if r['madden_id']:
        db_by_madden[str(r['madden_id'])] = r
    key = (norm(r['first_name']), norm(r['last_name']))
    db_by_name.setdefault(key, []).append(r)
conn.close()

with open(CSV_PATH) as f:
    rows = list(csv.DictReader(f))

name_matches = []
name_in_db_gaps = []

for row in rows:
    rid = str(row.get('rosterId','') or row.get('id','')).strip()
    fn = norm(row.get('firstName',''))
    ln = norm(row.get('lastName',''))

    # Already matched by madden_id — skip
    if rid in db_by_madden:
        continue

    candidates = db_by_name.get((fn, ln), [])
    pos = row.get('position','')
    age = row.get('age','')
    csv_label = f"{row.get('firstName')} {row.get('lastName')} | pos:{pos} | age:{age} | nfl:{row.get('team')}"

    if len(candidates) == 1:
        db = candidates[0]
        name_matches.append(f"  CSV: {csv_label}\n       DB:  {db['first_name']} {db['last_name']} | pos:{db['position']} | age:{db['age']} | madden_id:{db['madden_id']} | nml_team_id:{db['nml_team_id']}")
    elif len(candidates) > 1:
        pos_matches = [p for p in candidates if p['position'] == pos]
        if len(pos_matches) == 1:
            db = pos_matches[0]
            name_matches.append(f"  CSV: {csv_label}\n       DB:  {db['first_name']} {db['last_name']} | pos:{db['position']} | age:{db['age']} | madden_id:{db['madden_id']} | nml_team_id:{db['nml_team_id']}")
        else:
            for db in candidates:
                name_in_db_gaps.append(f"  CSV: {csv_label}\n       DB:  {db['first_name']} {db['last_name']} | pos:{db['position']} | age:{db['age']} | nfl_team:{db['nfl_team']} | nml_team_id:{db['nml_team_id']}")
    else:
        # Truly not in DB — skip for now
        pass

print(f"=== 5 NAME-MATCHED players (confirm these are correct) ===")
for m in name_matches:
    print(m)

print(f"\n=== NAME-IN-DB but madden_id gap (multiple matches, need manual confirm) ===")
for m in name_in_db_gaps:
    print(m)
