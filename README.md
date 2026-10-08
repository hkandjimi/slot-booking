# Presentation Slot Booking (Streamlit)

Groups book 15-minute presentation slots, between **08:00 and 21:30**, on any
of the dates you set up, with the lecturer of their choice. The **Schedule** tab
shows, per date, which time is booked by whom and with which lecturer.

## Features
- **Multiple dates**: add a single date or a date range (optionally skipping
  weekends); remove dates that have no bookings.
- **Lecturer availability per date**: pick a lecturer, a From/To time and a
  date (or several dates at once). Add several windows per lecturer (e.g.
  08:00-10:00 and 13:00-17:00). Several lecturers can be available at the same
  time; students choose whom to book.
- **Booking form**: Date -> Lecturer -> Time slot, plus Group Lead Name and
  Contact (required) and members as `Name(StudentNumber)`, one per line, e.g.
  `John Doe(2223544559)`.
- Blocks double-bookings and student numbers already in another booking.
- Removing availability never deletes slots that already have a booking.
- **Schedule page**: grid per date + table of all bookings (contacts are private).
- **Admin**: manage dates, availability and bookings; download bookings as CSV.
- Storage: CSV files in `data/` (`dates.csv`, `availability.csv`, `bookings.csv`).

## Run locally
    python -m venv .venv
    source .venv/bin/activate        # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    streamlit run app.py

Open http://localhost:8501, go to **Admin** (default password `admin`), then:
1. Add the presentation date(s).
2. Add each lecturer's availability.
3. Share the link; students book from the **Book a slot** tab.

Lecturers who should set their own times can be given the admin password,
or the admin can enter their times for them.

## Settings (optional)
Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and set
`ADMIN_PASSWORD` and `EVENT_TITLE`. `ADMIN_PASSWORD` can also be an environment
variable. Change the default password before sharing the app.

## Deploy on Streamlit Community Cloud
1. Push this folder to GitHub (`.gitignore` excludes `data/` and `secrets.toml`).
2. share.streamlit.io -> **New app** -> pick the repo and main file `app.py`.
3. **Advanced settings -> Secrets**: paste your `secrets.toml` contents
   (at least `ADMIN_PASSWORD`).
4. Deploy and share the URL.

### Important: data persistence on Streamlit Cloud
CSV files live on temporary disk and are **wiped on redeploy, reboot, or after
the app sleeps from inactivity**. Download the bookings CSV from the Admin tab
regularly and before any redeploy, and be ready to re-enter dates/availability.
For permanent storage, add a database or Google Sheets backend later.

## Upgrading from the previous version
The data format changed (dates were added). Delete the old `data/` folder
before first run.

## Files
- `app.py` - the whole app
- `requirements.txt` - streamlit, pandas
- `.streamlit/secrets.toml.example` - settings template
