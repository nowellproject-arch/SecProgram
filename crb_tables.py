import json
from datetime import datetime, timezone
from decimal import Decimal

CHUNK = 300   # rows per INSERT statement (RECORDS is big, one-by-one would be slow)


# ---------- converters: browser value -> database value ----------
def _blank(v):
    return v is None or str(v).strip() == ""

def to_text(v):
    return None if _blank(v) else str(v).strip()

def to_int(v):
    if _blank(v):
        return None
    d = Decimal(str(v).strip())
    if d != d.to_integral_value():
        raise ValueError("not a whole number")
    return int(d)

def to_num(v):
    if _blank(v):
        return None
    d = Decimal(str(v).strip())
    if not d.is_finite():
        raise ValueError("not a number")
    return d


# ---------- converters: database value -> value the browser expects ----------
def out_str(v):
    return str(v)

def out_int(v):
    return int(v)

def out_num(v):
    return format(Decimal(v).normalize(), "f")      # 54 -> "54", 4.5 -> "4.5"


TXT  = ("TEXT",    to_text, out_str)   # text stays text
INTS = ("INT",     to_int,  out_str)   # stored as INT, browser had it as "2012"
INTN = ("INT",     to_int,  out_int)   # stored as INT, browser had a real number
NUMS = ("NUMERIC", to_num,  out_num)   # stored as NUMERIC, browser had it as "54"


# ---------- ONE place that describes every table ----------
# store: (table, columns, primary-key columns besides passcode, single_row)
# column: (json key, sql column, sql type, to_db, from_db)
SPEC = {
    "CongInfo": ("conginfo", [
        ("SO", "so", *TXT), ("SEC", "sec", *TXT), ("CBOE", "cboe", *TXT),
        ("Link", "link", *TXT), ("user", "cong_user", *TXT),
        ("Address", "address", *TXT), ("Province", "province", *TXT),
        ("CongNumber", "congnumber", *TXT), ("Congregation", "congregation", *TXT),
        ("SelectedPubID", "selectedpubid", *TXT)],
        [], True),
    "GROUPS": ("groups", [
        ("Group", "group_no", *TXT), ("id", "id", *TXT), ("Remarks", "remarks", *TXT),
        ("Overseer", "overseer", *TXT), ("Assistant", "assistant", *TXT),
        ("MeetingPlace", "meetingplace", *TXT)],
        ["group_no"], False),
    "PUBLISHERS": ("publishers", [
        ("IDPub", "idpub", *TXT), ("FNAME", "fname", *TXT), ("LName", "lname", *TXT),
        ("MName", "mname", *TXT), ("Nname", "nname", *TXT), ("Fullname", "fullname", *TXT),
        ("GROUP", "grp", *TXT), ("Male", "male", *TXT), ("Female", "female", *TXT),
        ("Elder", "elder", *TXT), ("MS", "ms", *TXT), ("RP", "rp", *TXT), ("SF", "sf", *TXT),
        ("Status", "status", *TXT), ("Birthdate", "birthdate", *TXT),
        ("Baptism", "baptism", *TXT), ("Address", "address", *TXT),
        ("TelCp", "telcp", *TXT), ("TellHome", "tellhome", *TXT),
        ("Started", "started", *INTS), ("MoveOut", "moveout", *TXT)],
        ["idpub"], False),
    "MonthlyRecords": ("monthlyrecords", [
        ("NUMBER", "number", *INTN), ("MONTH_", "month_", *TXT), ("Year", "year", *INTS),
        ("ServiceYear", "serviceyear", *INTS), ("ActivePublishers", "activepublishers", *INTS),
        ("AttendcMidweekTotal", "attendcmidweektotal", *NUMS),
        ("AttendcPublickTotal", "attendcpublicktotal", *NUMS),
        ("NoMtgs1", "nomtgs1", *NUMS), ("NoMtgs2", "nomtgs2", *NUMS),
        ("Closed", "closed", *TXT), ("ACTIVE", "active", *TXT)],
        ["number"], False),
    "RECORDS": ("records", [
        ("IdPubs", "idpubs", *TXT), ("NUMBER", "number", *INTN), ("MINISTRY", "ministry", *TXT),
        ("BS", "bs", *NUMS), ("AUX", "aux", *NUMS), ("HRS", "hrs", *NUMS),
        ("Note", "note", *TXT), ("REMARKS", "remarks", *TXT),
        ("Date_entered", "date_entered", *INTN)],
        ["number", "idpubs"], False),
}


def create_tables(conn):
    """conginfo = parent table (one row per congregation, passcode is the key).
    The other 4 tables point to it. Built from SPEC so they never disagree."""
    for store, (table, cols, pk, single) in SPEC.items():
        if single:
            lines = ["passcode TEXT NOT NULL PRIMARY KEY"]
        else:
            lines = ["passcode TEXT NOT NULL REFERENCES conginfo(passcode) ON DELETE CASCADE"]
        for jk, col, typ, _, _ in cols:
            lines.append(f"{col} {typ}" + (" NOT NULL" if col in pk else ""))
        if single:
            lines.append("created_at TIMESTAMPTZ NOT NULL DEFAULT now()")
            lines.append("updated_at TIMESTAMPTZ")
        lines.append("extra JSONB")
        if not single:
            lines.append("PRIMARY KEY (" + ", ".join(["passcode"] + pk) + ")")
        conn.run(f"CREATE TABLE IF NOT EXISTS {table} (\n  " + ",\n  ".join(lines) + "\n)")


def _split(row, cols):
    """Row from the browser -> (converted values, leftovers for the extra column)."""
    known = {c[0] for c in cols}
    extra = {k: v for k, v in row.items() if k not in known}
    vals = []
    for jk, _, _, to_db, _ in cols:
        raw = row.get(jk)
        try:
            vals.append(to_db(raw))
        except (ValueError, TypeError, ArithmeticError):
            vals.append(None)
            extra[jk] = raw          # keep the original value, nothing is lost
    return vals, extra


def save_payload(conn, passcode, data):
    """Save one congregation into the 5 tables. Call inside a transaction."""
    now = datetime.now(timezone.utc)
    for store, (table, cols, pk, single) in SPEC.items():
        rows = data.get(store) or []

        # ---- parent row: insert or update, keeps created_at ----
        if single:
            row = dict(rows[0]) if rows and isinstance(rows[0], dict) else {}
            row.pop("passcode", None)     # passcode is the table key, not a normal field
            vals, extra = _split(row, cols)
            names = [c[1] for c in cols]
            col_sql = ", ".join(["passcode"] + names + ["extra", "updated_at"])
            marks = ", ".join([":passcode"] + [f":v{i}" for i in range(len(names))]
                              + ["CAST(:extra AS JSONB)", ":updated_at"])
            sets = ", ".join(f"{n} = EXCLUDED.{n}" for n in names + ["extra", "updated_at"])
            params = {f"v{i}": v for i, v in enumerate(vals)}
            conn.run(
                f"INSERT INTO {table} ({col_sql}) VALUES ({marks}) "
                f"ON CONFLICT (passcode) DO UPDATE SET {sets}",
                passcode=passcode, extra=json.dumps(extra, default=str),
                updated_at=now, **params)
            continue

        # ---- child tables: delete this congregation's rows, insert again ----
        conn.run(f"DELETE FROM {table} WHERE passcode = :p", p=passcode)

        pk_idx = [i for i, c in enumerate(cols) if c[1] in pk]
        unique = {}                       # last row wins, same as IndexedDB "put"
        skipped = []
        for n, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            vals, extra = _split(row, cols)
            key = tuple(vals[i] for i in pk_idx)
            if any(k is None for k in key):
                skipped.append((n, row))      # can't be stored without its key
                continue
            unique[key] = vals + [json.dumps(extra, default=str)]

        if skipped:
            print(f"⚠️ {store}: skipped {len(skipped)} row(s) without a valid key")
            for n, row in skipped[:5]:
                print(f"   row {n}: {row}")

        names = ", ".join(["passcode"] + [c[1] for c in cols] + ["extra"])
        items = list(unique.values())
        for s in range(0, len(items), CHUNK):
            params, groups = {}, []
            for r, vals in enumerate(items[s:s + CHUNK]):
                ph = [":passcode"]
                for c, v in enumerate(vals):
                    params[f"v{r}_{c}"] = v
                    ph.append(f"CAST(:v{r}_{c} AS JSONB)" if c == len(vals) - 1 else f":v{r}_{c}")
                groups.append("(" + ", ".join(ph) + ")")
            conn.run(f"INSERT INTO {table} ({names}) VALUES " + ", ".join(groups),
                     passcode=passcode, **params)


def load_payload(conn, passcode):
    """Rebuild the same JSON the browser/IndexedDB expects."""
    data = {}
    for store, (table, cols, pk, single) in SPEC.items():
        names = ", ".join([c[1] for c in cols] + ["extra"])
        order = (" ORDER BY " + ", ".join(pk)) if pk else ""
        rows = conn.run(f"SELECT {names} FROM {table} WHERE passcode = :p{order}", p=passcode)
        out = []
        for r in rows:
            extra = r[-1] or {}
            if isinstance(extra, str):
                extra = json.loads(extra)
            row = dict(extra)
            for (jk, _, _, _, from_db), v in zip(cols, r[:-1]):
                if v is not None:
                    row[jk] = from_db(v)
                else:
                    row.setdefault(jk, "")
            if single:
                row["passcode"] = passcode
            out.append(row)
        data[store] = out
    return data