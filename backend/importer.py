import openpyxl
import io
from database import get_db

REQUIRED_COLUMNS = ['position', 'first_name', 'last_name']
OPTIONAL_COLUMNS = ['age', 'nfl_team', 'overall_rating', 'madden_id']
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

VALID_POSITIONS = {
    'QB','HB','FB','WR','TE','LT','LG','C','RG','RT',
    'LE','RE','DT','LOLB','MLB','ROLB','CB','FS','SS','K','P'
}

def get_team_map():
    """Return dict of full_name -> id and abbreviation -> id"""
    conn = get_db()
    teams = conn.execute('SELECT id, full_name, short_name, abbreviation FROM teams').fetchall()
    conn.close()
    m = {}
    for t in teams:
        m[t['full_name'].lower()] = t['id']
        m[t['short_name'].lower()] = t['id']
        m[t['abbreviation'].lower()] = t['id']
    return m

def validate_import(file_bytes, target_team_id=None):
    """
    Parse Excel file and return a validation preview before committing.
    Returns: { valid: [...], errors: [...], warnings: [...], summary: {...} }
    """
    conn = get_db()
    team_map = get_team_map()

    # Get existing players for duplicate detection
    existing = {}
    for row in conn.execute('SELECT id, first_name, last_name, position, nml_team_id FROM players').fetchall():
        key = f"{row['first_name'].lower()}_{row['last_name'].lower()}_{row['position'].lower()}"
        existing[key] = dict(row)

    conn.close()

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
    except Exception as e:
        return {'error': f'Could not read Excel file: {e}'}

    # Try to find the right sheet
    ws = None
    for name in wb.sheetnames:
        if name.lower() not in ['log', 'count', 'l_teams']:
            ws = wb[name]
            break

    if not ws:
        return {'error': 'No valid sheet found in Excel file'}

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {'error': 'Sheet is empty'}

    # Detect header row
    header_row = None
    data_start = 0
    for i, row in enumerate(rows[:5]):
        row_lower = [str(c).lower().strip() if c else '' for c in row]
        if 'pos' in row_lower or 'position' in row_lower or 'first' in row_lower:
            header_row = row_lower
            data_start = i + 1
            break

    # Map columns
    col_map = {}
    if header_row:
        for i, h in enumerate(header_row):
            if h in ('pos', 'position'): col_map['position'] = i
            elif h in ('first', 'first_name', 'firstname'): col_map['first_name'] = i
            elif h in ('last', 'last_name', 'lastname'): col_map['last_name'] = i
            elif h in ('age',): col_map['age'] = i
            elif h in ('ovr', 'overall', 'overall_rating', 'rating'): col_map['overall_rating'] = i
            elif h in ('nfl_team', 'nfl', 'real_team'): col_map['nfl_team'] = i
            elif h in ('madden_id', 'id', 'player_id'): col_map['madden_id'] = i
    else:
        # Default column order: POS, FIRST, LAST, AGE, NFL_TEAM, OVR, MADDEN_ID
        col_map = {'position': 0, 'first_name': 1, 'last_name': 2, 'age': 3,
                   'nfl_team': 4, 'overall_rating': 5, 'madden_id': 6}

    valid = []
    errors = []
    warnings = []
    duplicates = []

    for row_num, row in enumerate(rows[data_start:], start=data_start + 1):
        if not any(row):
            continue

        def get_col(field):
            idx = col_map.get(field)
            if idx is None or idx >= len(row):
                return None
            val = row[idx]
            return str(val).strip() if val is not None else None

        pos = get_col('position')
        first = get_col('first_name')
        last = get_col('last_name')
        age_raw = get_col('age')
        ovr_raw = get_col('overall_rating')
        nfl_team = get_col('nfl_team')
        madden_id = get_col('madden_id')

        row_errors = []

        # Required field checks
        if not pos:
            row_errors.append('Missing position')
        elif pos.upper() not in VALID_POSITIONS:
            row_errors.append(f'Unknown position: {pos}')

        if not first:
            row_errors.append('Missing first name')
        if not last:
            row_errors.append('Missing last name')

        if row_errors:
            errors.append({'row': row_num, 'data': f'{first} {last}', 'errors': row_errors})
            continue

        # Age validation
        age = None
        if age_raw:
            try:
                age = int(float(age_raw))
                if age < 18 or age > 50:
                    warnings.append({'row': row_num, 'player': f'{first} {last}', 'warning': f'Unusual age: {age}'})
            except ValueError:
                warnings.append({'row': row_num, 'player': f'{first} {last}', 'warning': f'Invalid age value: {age_raw}'})

        # OVR validation
        ovr = None
        if ovr_raw:
            try:
                ovr = int(float(ovr_raw))
                if ovr < 40 or ovr > 99:
                    warnings.append({'row': row_num, 'player': f'{first} {last}', 'warning': f'Unusual OVR: {ovr}'})
            except ValueError:
                warnings.append({'row': row_num, 'player': f'{first} {last}', 'warning': f'Invalid OVR: {ovr_raw}'})

        # Duplicate check
        key = f"{first.lower()}_{last.lower()}_{pos.upper().lower()}"
        if key in existing:
            dup = existing[key]
            duplicates.append({
                'row': row_num,
                'player': f'{pos.upper()} {first} {last}',
                'existing_id': dup['id'],
                'action': 'update'  # will update existing record
            })

        valid.append({
            'row': row_num,
            'position': pos.upper(),
            'first_name': first,
            'last_name': last,
            'age': age,
            'overall_rating': ovr,
            'nfl_team': nfl_team,
            'madden_id': madden_id,
            'target_team_id': target_team_id,
            'is_duplicate': key in existing,
            'existing_id': existing[key]['id'] if key in existing else None,
        })

    return {
        'valid': valid,
        'errors': errors,
        'warnings': warnings,
        'duplicates': duplicates,
        'summary': {
            'total_rows': row_num if rows[data_start:] else 0,
            'valid_count': len(valid),
            'error_count': len(errors),
            'warning_count': len(warnings),
            'duplicate_count': len(duplicates),
            'new_count': len([p for p in valid if not p['is_duplicate']]),
        }
    }

def commit_import(validated_players, imported_by_user_id=None):
    """Commit validated player data to the database"""
    conn = get_db()
    created = 0
    updated = 0
    errors = []

    for p in validated_players:
        try:
            if p.get('existing_id'):
                # Update existing player fields (partial import safe)
                updates = {}
                if p.get('overall_rating') is not None:
                    updates['overall_rating'] = p['overall_rating']
                if p.get('age') is not None:
                    updates['age'] = p['age']
                if p.get('nfl_team'):
                    updates['nfl_team'] = p['nfl_team']
                if p.get('madden_id'):
                    updates['madden_id'] = p['madden_id']

                if updates:
                    # Track field history
                    old = dict(conn.execute('SELECT * FROM players WHERE id = ?', (p['existing_id'],)).fetchone())
                    for field, new_val in updates.items():
                        old_val = old.get(field)
                        if str(old_val) != str(new_val):
                            conn.execute('''INSERT INTO player_field_history
                                (player_id, field_name, old_value, new_value, changed_by)
                                VALUES (?, ?, ?, ?, ?)''',
                                (p['existing_id'], field, str(old_val), str(new_val), imported_by_user_id))

                    sets = ', '.join(f'{k} = ?' for k in updates)
                    conn.execute(f'UPDATE players SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                                 list(updates.values()) + [p['existing_id']])
                updated += 1
            else:
                team_id = p.get('target_team_id')
                conn.execute('''INSERT INTO players
                    (first_name, last_name, position, age, overall_rating, nfl_team,
                     nml_team_id, madden_id, is_free_agent, updated_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (p['first_name'], p['last_name'], p['position'],
                     p.get('age'), p.get('overall_rating'), p.get('nfl_team'),
                     team_id, p.get('madden_id'),
                     0 if team_id else 1, imported_by_user_id))
                created += 1
        except Exception as e:
            errors.append(f"{p['first_name']} {p['last_name']}: {e}")

    conn.commit()
    conn.close()
    return {'created': created, 'updated': updated, 'errors': errors}

def generate_import_template():
    """Generate a blank Excel import template"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Players'

    headers = ['POS', 'FIRST', 'LAST', 'AGE', 'NFL_TEAM', 'OVR', 'MADDEN_ID']
    ws.append(headers)

    # Style header row
    from openpyxl.styles import Font, PatternFill
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill(start_color='1a1d24', end_color='1a1d24', fill_type='solid')

    # Example row
    ws.append(['QB', 'Patrick', 'Mahomes', 29, 'Kansas City Chiefs', 97, ''])

    # Column widths
    for col, width in zip('ABCDEFG', [8, 15, 15, 6, 25, 6, 12]):
        ws.column_dimensions[col].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.read()
