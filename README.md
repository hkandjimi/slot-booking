# Presentation Slot Booking (Streamlit)

Students book 15-minute presentation slots between 10:00 and 12:00 with the
lecturer of their choice. Lecturers (and the slots each can attend) are set in
the **Admin** tab; the **Schedule** tab shows who booked which time and lecturer.

## Features
- Book a slot: pick a lecturer, then a free slot. Several lecturers can be
  available at the same time.
- Collects Group Lead Name and Contact (required) and all group members as
  `Name(StudentNumber)`, one per line, e.g. `John Doe(2223544559)`.
- Blocks double-bookings and student numbers that are already in another booking.
- Schedule page: availability grid plus a table of bookings (contacts are private).
- Admin tab: configure lecturers, cancel bookings, download all bookings as CSV.
- Storage: plain CSV files in `data/` (`bookings.csv`, `lecturers.csv`).

## Run locally
    python -m venv .venv
    source .venv/bin/activate        # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    streamlit run app.py

Open http://localhost:8501. Go to **Admin**, log in (default password `admin`),
add lecturers and tick their available slots, then Save.

## Set the admin password / event details (optional)
Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and edit
`ADMIN_PASSWORD`, `EVENT_TITLE`, `EVENT_DATE`. (You can also set the
`ADMIN_PASSWORD` environment variable.) Change the default before sharing!

## Deploy on Streamlit Community Cloud
1. Push this folder to a GitHub repo (`.gitignore` already excludes `data/` and
   `secrets.toml`).
2. Go to https://share.streamlit.io -> **New app** -> choose the repo, branch and
   main file `app.py`.
3. Under **Advanced settings -> Secrets**, paste your `secrets.toml` contents
   (at least `ADMIN_PASSWORD`).
4. Deploy and share the URL with students.

### Important: data persistence on Streamlit Cloud
The CSV files live on the app's temporary disk. They survive normal use but are
**wiped when the app is redeployed, rebooted, or wakes from sleep after
inactivity**. To be safe:
- Download the bookings CSV from the Admin tab regularly (and before any
  redeploy), and
- Re-enter lecturers after a reset (this takes a minute).
For permanent storage later, add a database or Google Sheets backend.

## Files
- `app.py` - the whole app
- `requirements.txt` - streamlit, pandas
- `.streamlit/secrets.toml.example` - settings template
- `data/` - created automatically on first save
