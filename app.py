"""Presentation slot booking app (Streamlit, local CSV storage).

* 15-minute slots between 08:00 and 21:30 on any number of dates.
* Availability is configured per date and per lecturer in the Admin tab.
* Data is stored in data/dates.csv, data/availability.csv, data/bookings.csv.
"""
import hmac
import os
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# ------------------------------------------------------------------ constants
DAY_START, DAY_END, SLOT_MIN = 8 * 60, 21 * 60 + 30, 15  # 08:00 .. 21:30


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


STARTS = [hhmm(m) for m in range(DAY_START, DAY_END, SLOT_MIN)]
ENDS = [hhmm(m + SLOT_MIN) for m in range(DAY_START, DAY_END, SLOT_MIN)]
SLOTS = [f"{a} - {b}" for a, b in zip(STARTS, ENDS)]  # 54 slots
BOOKING_COLS = ["Timestamp", "Date", "Lecturer", "Slot", "Group Lead", "Contact", "Members"]
AVAIL_COLS = ["Date", "Lecturer", "Slots"]
DATE_COLS = ["Date"]
MEMBER_RE = re.compile(r"^\s*([^()]+?)\s*\(\s*(\d{5,12})\s*\)\s*$")
DATA_DIR = Path(os.environ.get("BOOKING_DATA_DIR", "data"))
BOOKINGS_CSV = DATA_DIR / "bookings.csv"
AVAIL_CSV = DATA_DIR / "availability.csv"
DATES_CSV = DATA_DIR / "dates.csv"

st.set_page_config(page_title="Presentation Booking", page_icon="🗓️", layout="wide")


def secret(key, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, default)


def fmt_date(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%a %d %b %Y")


def summarize(slots):
    """['08:00 - 08:15', '08:15 - 08:30', '09:00 - 09:15'] -> '08:00–08:30, 09:00–09:15'"""
    idx = sorted(SLOTS.index(s) for s in slots if s in SLOTS)
    runs, start, prev = [], None, None
    for i in idx:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            runs.append((start, prev))
            start = prev = i
    if start is not None:
        runs.append((start, prev))
    return ", ".join(f"{STARTS[a]}–{ENDS[b]}" for a, b in runs)


# -------------------------------------------------------------------- storage
@st.cache_resource
def get_lock():
    return threading.Lock()


LOCK = get_lock()


def _read(path, cols):
    if path.exists():
        df = pd.read_csv(path, dtype=str).fillna("")
        for c in cols:
            if c not in df:
                df[c] = ""
        return df[cols]
    return pd.DataFrame(columns=cols)


def _write(path, df):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(path)  # atomic swap


def load_dates():
    return sorted(_read(DATES_CSV, DATE_COLS)["Date"].tolist())


def add_dates(new):
    with LOCK:
        cur = set(load_dates())
        added = [d for d in new if d not in cur]
        _write(DATES_CSV, pd.DataFrame({"Date": sorted(cur | set(new))}))
        return added


def load_availability():
    """{date: {lecturer: [slots in order]}}"""
    out = {}
    for r in _read(AVAIL_CSV, AVAIL_COLS).itertuples():
        slots = [s for s in SLOTS if s in r.Slots.split(";")]
        if r.Date and r.Lecturer and slots:
            out.setdefault(r.Date, {})[r.Lecturer] = slots
    return out


def load_bookings():
    df = _read(BOOKINGS_CSV, BOOKING_COLS)
    order = {s: i for i, s in enumerate(SLOTS)}
    return (df.assign(_o=df["Slot"].map(order))
            .sort_values(["Date", "_o", "Lecturer"]).drop(columns="_o")
            .reset_index(drop=True))


def update_availability(dates, lecturer, window, add):
    """Add/remove a window of slots. Slots that already have a booking are never
    removed. Returns the list of slots that were kept because they are booked."""
    with LOCK:
        avail, bookings = load_availability(), load_bookings()
        kept = set()
        for d in dates:
            booked = set(bookings[(bookings.Date == d) & (bookings.Lecturer == lecturer)].Slot)
            cur = set(avail.get(d, {}).get(lecturer, []))
            if add:
                cur |= set(window)
            else:
                kept |= booked & set(window)
                cur -= set(window) - booked
            if cur:
                avail.setdefault(d, {})[lecturer] = [s for s in SLOTS if s in cur]
            elif d in avail:
                avail[d].pop(lecturer, None)
        rows = [[d, n, ";".join(sl)] for d, lec in sorted(avail.items())
                for n, sl in sorted(lec.items()) if sl]
        _write(AVAIL_CSV, pd.DataFrame(rows, columns=AVAIL_COLS))
        return sorted(kept, key=SLOTS.index)


def remove_date(d):
    with LOCK:
        if (load_bookings().Date == d).any():
            return False
        _write(DATES_CSV, pd.DataFrame({"Date": [x for x in load_dates() if x != d]}))
        av = _read(AVAIL_CSV, AVAIL_COLS)
        _write(AVAIL_CSV, av[av.Date != d])
        return True


def add_booking(d, lecturer, slot, lead, contact, members):
    with LOCK:  # re-check against the files at the moment of saving
        if slot not in load_availability().get(d, {}).get(lecturer, []):
            return False, "That slot is no longer available. Please pick another."
        df = load_bookings()
        if ((df.Date == d) & (df.Lecturer == lecturer) & (df.Slot == slot)).any():
            return False, "Sorry, that slot was just taken. Please pick another."
        new_ids = set(re.findall(r"\((\d+)\)", members))
        for existing in df.Members:
            clash = new_ids & set(re.findall(r"\((\d+)\)", existing))
            if clash:
                return False, (f"Student number(s) {', '.join(sorted(clash))} "
                               "already appear in another booking.")
        row = pd.DataFrame([[datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                             d, lecturer, slot, lead, contact, members]],
                           columns=BOOKING_COLS)
        _write(BOOKINGS_CSV, pd.concat([df, row], ignore_index=True))
        return True, "Booked!"


def cancel_booking(d, lecturer, slot):
    with LOCK:
        df = load_bookings()
        _write(BOOKINGS_CSV,
               df[~((df.Date == d) & (df.Lecturer == lecturer) & (df.Slot == slot))])


# ----------------------------------------------------------------- validation
def parse_members(text):
    good, bad = [], []
    for line in re.split(r"[\n;]+", text):
        if not line.strip():
            continue
        m = MEMBER_RE.match(line)
        if m:
            good.append(f"{m.group(1)}({m.group(2)})")
        else:
            bad.append(line.strip())
    return good, bad


def valid_contact(c):
    c = c.strip()
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", c)) or len(re.sub(r"\D", "", c)) >= 7


# ------------------------------------------------------------------------ UI
st.title(f"🗓️ {secret('EVENT_TITLE', 'Presentation Booking')}")
st.caption(f"Each group gets a 15-minute slot. Slots are offered between "
           f"{hhmm(DAY_START)} and {hhmm(DAY_END)} on the dates below.")

tab_book, tab_sched, tab_admin = st.tabs(["📝 Book a slot", "📋 Schedule", "🔐 Admin"])

# ---- Book
with tab_book:
    avail, bookings = load_availability(), load_bookings()
    taken = set(zip(bookings.Date, bookings.Lecturer, bookings.Slot))

    def free_for(d):
        f = {n: [s for s in sl if (d, n, s) not in taken] for n, sl in avail.get(d, {}).items()}
        return {n: sl for n, sl in f.items() if sl}

    open_dates = [d for d in load_dates() if free_for(d)]
    if not load_dates():
        st.info("No presentation dates have been set up yet. Please check back soon.")
    elif not open_dates:
        st.warning("There are no free slots available at the moment.")
    else:
        chosen_date = st.selectbox("Date", open_dates, format_func=fmt_date)
        free = free_for(chosen_date)
        lecturer = st.selectbox(
            "Lecturer", list(free),
            format_func=lambda n: f"{n}  ({len(free[n])} slots free)")
        with st.form("booking_form"):
            slot = st.selectbox("Time slot", free[lecturer])
            lead = st.text_input("Group Lead Name *")
            contact = st.text_input("Group Lead Contact (email or phone) *")
            members_txt = st.text_area(
                "Group Members: names and student numbers *",
                placeholder="John Doe(2223544559)\nJane Smith(2223544560)",
                help="One member per line, format: Name(StudentNumber). Include the group lead.",
                height=150)
            submitted = st.form_submit_button("Book slot", type="primary")

        if submitted:
            members, bad = parse_members(members_txt)
            errors = []
            if not lead.strip():
                errors.append("Group Lead Name is required.")
            if not valid_contact(contact):
                errors.append("Enter a valid email address or phone number as contact.")
            if not members:
                errors.append("Add at least one group member.")
            if bad:
                errors.append("These lines don't match `Name(StudentNumber)`: " + "; ".join(bad))
            ids = [re.search(r"\((\d+)\)", m).group(1) for m in members]
            if len(ids) != len(set(ids)):
                errors.append("A student number is listed more than once.")
            if errors:
                for e in errors:
                    st.error(e)
            else:
                ok, msg = add_booking(chosen_date, lecturer, slot, lead.strip(),
                                      contact.strip(), "\n".join(members))
                if ok:
                    st.success(f"✅ Booked **{fmt_date(chosen_date)}, {slot}** with "
                               f"**{lecturer}** for {lead.strip()}'s group. "
                               "Please screenshot this for your records.")
                else:
                    st.error(msg)

# ---- Schedule
with tab_sched:
    st.button("🔄 Refresh")
    avail, bookings = load_availability(), load_bookings()
    dates = load_dates()
    if not dates:
        st.info("No dates set up yet.")
    else:
        today = date.today().isoformat()
        default = next((i for i, d in enumerate(dates) if d >= today), 0)
        d = st.selectbox("Date", dates, index=default, format_func=fmt_date, key="sched_date")
        day_av = avail.get(d, {})
        day_bk = bookings[bookings.Date == d]
        names = sorted(set(day_av) | set(day_bk.Lecturer))
        if names:
            grid = pd.DataFrame("", index=SLOTS, columns=names)
            for n, sl in day_av.items():
                for s in sl:
                    grid.loc[s, n] = "🟢 Free"
            for _, b in day_bk.iterrows():
                grid.loc[b["Slot"], b["Lecturer"]] = f"🔴 {b['Group Lead']}"
            grid = grid[(grid != "").any(axis=1)].replace("", "—")  # hide unused rows
            st.caption("🟢 free · 🔴 booked (group lead shown) · — lecturer not available")
            st.dataframe(grid, height=min(35 * (len(grid) + 1) + 3, 750))
        else:
            st.info("No lecturers are available on this date yet.")

    st.subheader("All bookings")
    if bookings.empty:
        st.info("No bookings yet.")
    else:
        view = bookings[["Date", "Slot", "Lecturer", "Group Lead", "Members"]].copy()
        view["Date"] = view["Date"].map(lambda x: fmt_date(x) if x else "")
        view["Members"] = view["Members"].str.replace("\n", "; ")
        st.dataframe(view, hide_index=True)

# ---- Admin
with tab_admin:
    pw = secret("ADMIN_PASSWORD", "admin")
    if not st.session_state.get("is_admin"):
        if pw == "admin":
            st.warning("Using the default password `admin`. Set `ADMIN_PASSWORD` "
                       "(secrets or environment variable) before sharing the app.")
        entered = st.text_input("Admin password", type="password")
        if st.button("Log in"):
            if hmac.compare_digest(entered, str(pw)):
                st.session_state.is_admin = True
                st.rerun()
            else:
                st.error("Wrong password.")
    else:
        # ---- 1. dates
        st.subheader("1. Presentation dates")
        c1, c2 = st.columns([2, 1])
        picked = c1.date_input("Pick a date, or a start and end date for a range",
                               value=(date.today(), date.today()), key="new_dates")
        skip_we = c2.checkbox("Skip weekends (for ranges)", value=True)
        if st.button("➕ Add date(s)"):
            picked = picked if isinstance(picked, (tuple, list)) else (picked,)
            start, end = picked[0], picked[-1]
            days = [start + timedelta(n) for n in range((end - start).days + 1)]
            if len(days) > 1 and skip_we:
                days = [x for x in days if x.weekday() < 5]
            added = add_dates([x.isoformat() for x in days])
            st.success(f"Added {len(added)} date(s)." if added else "Those dates already exist.")
        dates = load_dates()
        if dates:
            c1, c2 = st.columns([2, 1])
            gone = c1.selectbox("Remove a date", dates, index=None, format_func=fmt_date)
            if gone and c2.button("🗑️ Remove date"):
                if remove_date(gone):
                    st.rerun()
                else:
                    st.error("That date has bookings. Cancel them first.")

        # ---- 2. availability
        st.subheader("2. Lecturer availability")
        if not dates:
            st.info("Add at least one date first.")
        else:
            st.caption(f"Choose times between {hhmm(DAY_START)} and {hhmm(DAY_END)}. "
                       "Add several windows for a lecturer (e.g. morning and afternoon) "
                       "and apply them to one or more dates. Several lecturers can "
                       "be available at the same time.")
            avail = load_availability()
            known = sorted({n for dd in avail.values() for n in dd})
            sel = st.selectbox("Date", dates, format_func=fmt_date, key="admin_date")
            NEW = "➕ New lecturer…"
            c1, c2 = st.columns(2)
            pick = c1.selectbox("Lecturer", [NEW] + known)
            new_name = c2.text_input("New lecturer name") if pick == NEW else ""
            c1, c2, c3 = st.columns(3)
            t_from = c1.selectbox("From", STARTS, index=0)
            t_to = c2.selectbox("To", ENDS, index=ENDS.index("12:00"))
            action = c3.radio("Action", ["Add window", "Remove window"], horizontal=True)
            targets = st.multiselect("Apply to dates", dates, default=[sel],
                                     format_func=fmt_date)
            if st.button("Apply", type="primary"):
                name = new_name.strip() if pick == NEW else pick
                i, j = STARTS.index(t_from), ENDS.index(t_to)
                if not name:
                    st.error("Enter a lecturer name.")
                elif j < i:
                    st.error("'To' must be later than 'From'.")
                elif not targets:
                    st.error("Select at least one date.")
                else:
                    kept = update_availability(targets, name, SLOTS[i:j + 1],
                                              add=(action == "Add window"))
                    st.success(f"Updated {name} for {len(targets)} date(s).")
                    if kept:
                        st.warning("Slots with existing bookings were kept: " + ", ".join(kept))

            avail = load_availability()
            day = avail.get(sel, {})
            bk = load_bookings()
            st.markdown(f"**Availability on {fmt_date(sel)}**")
            if day:
                st.dataframe(pd.DataFrame(
                    [{"Lecturer": n, "Available": summarize(sl), "Slots": len(sl),
                      "Booked": int(((bk.Date == sel) & (bk.Lecturer == n)).sum())}
                     for n, sl in day.items()]), hide_index=True)
            else:
                st.info("No lecturers set for this date yet.")

        # ---- 3. bookings
        st.subheader("3. Manage bookings")
        bookings = load_bookings()
        if bookings.empty:
            st.info("No bookings yet.")
        else:
            st.dataframe(bookings, hide_index=True)
            st.download_button("⬇️ Download CSV", bookings.to_csv(index=False),
                               "bookings.csv", "text/csv")
            labels = [f"{fmt_date(r['Date']) if r['Date'] else '(no date)'} · {r['Slot']} · "
                      f"{r['Lecturer']} · {r['Group Lead']}" for _, r in bookings.iterrows()]
            pick = st.selectbox("Cancel a booking", labels, index=None)
            if pick and st.button("🗑️ Cancel selected booking"):
                r = bookings.iloc[labels.index(pick)]
                cancel_booking(r["Date"], r["Lecturer"], r["Slot"])
                st.rerun()

        if st.button("Log out"):
            st.session_state.is_admin = False
            st.rerun()
