"""The Streamlit page.  Run with:

    uv run streamlit run src/jobscout/app.py

Streamlit re-runs this whole script on every click. Anything you want to
survive between runs goes in st.session_state (none needed here: the database
is our state).
"""

from datetime import date

import pandas as pd
import streamlit as st

from jobscout import store, tracker

st.set_page_config(page_title="JobScout", layout="wide")
st.title("JobScout")

# ---- Sidebar: add an application by hand ----------------------------------
with st.sidebar:
    st.header("Add application")
    with st.form("add", clear_on_submit=True):   # a form submits all fields at once
        title = st.text_input("Title")
        employer = st.text_input("Employer")
        location = st.text_input("Location")
        url = st.text_input("Link")
        status = st.selectbox("Status", tracker.STATUSES, index=1)
        applied = st.date_input("Applied on", value=date.today())
        follow_up = st.date_input("Follow up on", value=None)
        if st.form_submit_button("Add") and title and employer:
            tracker.add(
                title, employer, location=location, url=url, status=status,
                applied_date=applied.isoformat() if status != "saved" else None,
                follow_up_date=follow_up.isoformat() if follow_up else None,
            )
            st.rerun()

    st.header("Import fetched jobs")
    if st.button("Import from data/jobs.csv"):
        try:
            n = tracker.import_jobs(store.load())
            st.success(f"{n} new job(s) added as 'saved'.")
        except FileNotFoundError:
            st.warning("No data/jobs.csv yet. Run `uv run jobscout --sample` first.")

apps = tracker.list_all()

# ---- Summary ----------------------------------------------------------------
counts = apps["status"].value_counts()
cols = st.columns(len(tracker.STATUSES))
for col, status_name in zip(cols, tracker.STATUSES):
    col.metric(status_name.title(), int(counts.get(status_name, 0)))

# ---- Follow-ups due ---------------------------------------------------------
due = tracker.due()
if not due.empty:
    st.warning(f"{len(due)} follow-up(s) due")
    st.dataframe(due[["title", "employer", "status", "follow_up_date", "contact"]],
                 hide_index=True, width="stretch")

# ---- Main table (editable) ----------------------------------------------------
st.subheader("Applications")
chosen = st.multiselect("Filter by status", tracker.STATUSES)
view = apps[apps["status"].isin(chosen)] if chosen else apps

# data_editor is an editable grid. It returns the edited frame, so we diff
# against the original to find what changed. Dates are stored as text, so we
# convert for display and back on save.
date_cols = ["applied_date", "follow_up_date"]
shown = view.drop(columns=["created_at"]).copy()
for c in date_cols:
    shown[c] = pd.to_datetime(shown[c])

edited = st.data_editor(
    shown,
    hide_index=True,
    width="stretch",
    disabled=["id", "job_id"],
    column_config={
        "status": st.column_config.SelectboxColumn(options=tracker.STATUSES, required=True),
        "applied_date": st.column_config.DateColumn(),
        "follow_up_date": st.column_config.DateColumn(),
        "url": st.column_config.LinkColumn(),
        "job_id": None,        # None hides a column
    },
    key="editor",
)

if st.button("Save changes"):
    changed = 0
    for (_, old), (_, new) in zip(shown.iterrows(), edited.iterrows()):
        diff = {}
        for col in tracker.EDITABLE:
            a, b = old[col], new[col]
            if pd.isna(a) and pd.isna(b):
                continue
            if a != b:
                diff[col] = b.date().isoformat() if col in date_cols and pd.notna(b) else (None if pd.isna(b) else b)
        if diff:
            tracker.update(int(old["id"]), **diff)
            changed += 1
    st.success(f"Saved {changed} row(s).")
    st.rerun()

with st.expander("Delete an application"):
    del_id = st.number_input("Application id", min_value=1, step=1)
    if st.button("Delete"):
        tracker.delete(int(del_id))
        st.rerun()
