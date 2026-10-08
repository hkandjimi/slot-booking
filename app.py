"""Presentation slot booking app (Streamlit, local CSV storage).

Slots: 10:00-12:00 in 15-minute blocks. Lecturers and their availability are
set on the Admin tab. Bookings are saved to data/bookings.csv.
"""
import hmac
import os
import re
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

SLOTS = [
    f"{(600 + 15 * i) // 60:02d}:{(600 + 15 * i) % 60:02d} - "
    f"{(615 + 15 * i) // 60:02d}:{(615 + 15 * i) % 60:02d}"
    for i in range(8)
]  # 10:00 - 10:15 ... 11:45 - 12:00
BOOKING_COLS = ["Timestamp", "Lecturer", "Slot", "Group Lead", "Contact", "Members"]
LECTURER_COLS = ["Lecturer", "Slots"]
MEMBER_RE = re.compile(r"^\s*([^()]+?)\s*\(\s*(\d{5,12})\s*\)\s*$")
DATA_DIR = Path(os.environ.get("BOOKING_DATA_DIR", "data"))
BOOKINGS_CSV = DATA_DIR / "bookings.csv"
LECTURERS_CSV = DATA_DIR / "lecturers.csv"

st.set_page_config(page_title="Presentation Booking", page_icon="🗓️", layout="wide")


def secret(key, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, default)


# -------------------------------------------------------------------- storage
@st.cache_resource
def get_lock():
    return threading.Lock()


LOCK = get_lock()


def _read(path, cols):
    if path.exists():
        return pd.read_csv(path, dtype=str).fillna("")[cols]
    return pd.DataFrame(columns=cols)


def _write(path, df):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(path)  # atomic swap so a crash can't corrupt the file


def load_lecturers():
    df = _read(LECTURERS_CSV, LECTURER_COLS)
    return {r.Lecturer: [s for s in r.Slots.split(";") if s in SLOTS]
            for r in df.itertuples() if r.Lecturer}


def save_lecturers(mapping):
    with LOCK:
        _write(LECTURERS_CSV, pd.DataFrame(
            [[n, ";".join(s)] for n, s in mapping.items()], columns=LECTURER_COLS))


def load_bookings():
    df = _read(BOOKINGS_CSV, BOOKING_COLS)
    order = {s: i for i, s in enumerate(SLOTS)}
    return (df.assign(_o=df["Slot"].map(order)).sort_values(["_o", "Lecturer"])
            .drop(columns="_o").reset_index(drop=True))


def add_booking(lecturer, slot, lead, contact, members):
    with LOCK:  # re-check against the file at the moment of saving
        df = load_bookings()
        if ((df.Lecturer == lecturer) & (df.Slot == slot)).any():
            return False, "Sorry, that slot was just taken. Please pick another."
        new_ids = set(re.findall(r"\((\d+)\)", members))
        for existing in df.Members:
            clash = new_ids & set(re.findall(r"\((\d+)\)", existing))
            if clash:
                return False, (f"Student number(s) {', '.join(sorted(clash))} "
                               "already appear in another booking.")
        row = pd.DataFrame([[datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                             lecturer, slot, lead, contact, members]],
                           columns=BOOKING_COLS)
        _write(BOOKINGS_CSV, pd.concat([df, row], ignore_index=True))
        return True, "Booked!"


def cancel_booking(lecturer, slot):
    with LOCK:
        df = load_bookings()
        _write(BOOKINGS_CSV, df[~((df.Lecturer == lecturer) & (df.Slot == slot))])


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
caption = "Slots are 15 minutes, between 10:00 and 12:00."
if secret("EVENT_DATE"):
    caption = f"**{secret('EVENT_DATE')}** · " + caption
st.caption(caption)

tab_book, tab_sched, tab_admin = st.tabs(["📝 Book a slot", "📋 Schedule", "🔐 Admin"])

# ---- Book
with tab_book:
    lect = load_lecturers()
    bookings = load_bookings()
    taken = set(zip(bookings.Lecturer, bookings.Slot))
    free = {n: [s for s in sl if (n, s) not in taken] for n, sl in lect.items()}
    choices = [n for n, f in free.items() if f]

    if not lect:
        st.info("No lecturers have been configured yet. Please check back soon.")
    elif not choices:
        st.warning("All slots are fully booked.")
    else:
        lecturer = st.selectbox(
            "Lecturer", choices, format_func=lambda n: f"{n}  ({len(free[n])} slots free)")
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
                ok, msg = add_booking(lecturer, slot, lead.strip(), contact.strip(),
                                      "\n".join(members))
                if ok:
                    st.success(f"✅ Booked **{slot}** with **{lecturer}** for "
                               f"{lead.strip()}'s group. Please screenshot this for your records.")
                else:
                    st.error(msg)

# ---- Schedule
with tab_sched:
    st.button("🔄 Refresh")
    lect = load_lecturers()
    bookings = load_bookings()
    if lect:
        grid = pd.DataFrame("—", index=SLOTS, columns=list(lect))
        for n, sl in lect.items():
            for s in sl:
                grid.loc[s, n] = "🟢 Free"
        for _, b in bookings.iterrows():
            if b["Lecturer"] in grid.columns and b["Slot"] in grid.index:
                grid.loc[b["Slot"], b["Lecturer"]] = f"🔴 {b['Group Lead']}"
        st.subheader("Availability overview")
        st.caption("🟢 free · 🔴 booked (group lead shown) · — lecturer not available")
        st.dataframe(grid)
    st.subheader("Bookings")
    if bookings.empty:
        st.info("No bookings yet.")
    else:
        view = bookings[["Slot", "Lecturer", "Group Lead", "Members"]].copy()
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
        st.subheader("Lecturer availability")
        st.caption("Add a row per lecturer and tick the slots they can attend. "
                   "Several lecturers can share the same time.")
        lect = load_lecturers()
        df = pd.DataFrame(
            [{"Lecturer": n, **{s: s in sl for s in SLOTS}} for n, sl in lect.items()],
            columns=["Lecturer"] + SLOTS)
        edited = st.data_editor(
            df, num_rows="dynamic", hide_index=True, key="lect_editor",
            column_config={s: st.column_config.CheckboxColumn(s, default=False) for s in SLOTS})
        if st.button("💾 Save lecturers", type="primary"):
            mapping, dup = {}, False
            for _, row in edited.iterrows():
                name = str(row["Lecturer"]).strip() if pd.notna(row["Lecturer"]) else ""
                if not name:
                    continue
                dup = dup or name in mapping
                mapping[name] = [s for s in SLOTS if pd.notna(row[s]) and bool(row[s])]
            if dup:
                st.error("Lecturer names must be unique.")
            else:
                save_lecturers(mapping)
                st.success("Saved.")

        st.subheader("Manage bookings")
        bookings = load_bookings()
        if bookings.empty:
            st.info("No bookings yet.")
        else:
            st.dataframe(bookings, hide_index=True)
            st.download_button("⬇️ Download CSV", bookings.to_csv(index=False),
                               "bookings.csv", "text/csv")
            labels = [f"{r['Slot']} · {r['Lecturer']} · {r['Group Lead']}"
                      for _, r in bookings.iterrows()]
            pick = st.selectbox("Cancel a booking", labels, index=None)
            if pick and st.button("🗑️ Cancel selected booking"):
                r = bookings.iloc[labels.index(pick)]
                cancel_booking(r["Lecturer"], r["Slot"])
                st.rerun()

        if st.button("Log out"):
            st.session_state.is_admin = False
            st.rerun()
