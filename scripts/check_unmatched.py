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
c.execute('SELECT first_name, last_name, position, madden_id FROM players')
all_p = c.fetchall()
db_by_name = {}
db_madden_ids = set()
for r in all_p:
    if r['madden_id']:
        db_madden_ids.add(str(r['madden_id']))
    key = (norm(r['first_name']), norm(r['last_name']))
    db_by_name.setdefault(key, []).append(r)
conn.close()

with open(CSV_PATH) as f:
    rows = list(csv.DictReader(f))

not_in_db = 0
name_in_db = 0
name_in_db_list = []
not_in_db_list = []

for row in rows:
    rid = str(row.get('rosterId','') or row.get('id','')).strip()
    if rid in db_madden_ids:
        continue
    fn = norm(row.get('firstName',''))
    ln = norm(row.get('lastName',''))
    label = f"{row.get('firstName')} {row.get('lastName')} ({row.get('position')}, {row.get('team')})"
    if (fn, ln) in db_by_name:
        name_in_db += 1
        name_in_db_list.append(label)
    else:
        not_in_db += 1
        not_in_db_list.append(label)

print(f"Of unmatched CSV rows:")
print(f"  Name IS in DB (madden_id gap, can fix): {name_in_db}")
print(f"  Truly not in DB at all:                 {not_in_db}")
print(f"\nName-in-DB sample (first 10) — these can be matched by name:")
for u in name_in_db_list[:10]:
    print(f"  {u}")
print(f"\nNot-in-DB sample (first 10) — these are depth/practice squad players:")
for u in not_in_db_list[:10]:
    print(f"  {u}")
