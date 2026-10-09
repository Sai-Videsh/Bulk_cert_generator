"""Small Streamlit GUI for the Bulk Certificate Generator API (stdlib HTTP client)."""
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Bulk Certificate Generator", layout="wide")

BASE = st.sidebar.text_input("API base URL", "http://127.0.0.1:8000")
API = BASE.rstrip("/") + "/api/v1"


def api(method: str, path: str, body: dict | None = None, headers: dict | None = None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode() or "{}")
        except Exception:
            detail = {"detail": "request failed"}
        raise RuntimeError(f"HTTP {e.code}: {detail}")


def download_bytes(path: str) -> tuple[bytes, str]:
    with urllib.request.urlopen(API + path, timeout=60) as r:
        return r.read(), r.headers.get_content_type()


st.title("Bulk Certificate Generator")
tab1, tab2 = st.tabs(["Submit job", "Track & download"])

with tab1:
    st.subheader("1. Job details")
    c1, c2, c3 = st.columns(3)
    title = c1.text_input("Title", "Python Workshop 2026")
    course = c2.text_input("Course", "Advanced Python")
    issuer = c3.text_input("Issuer", "Acme Academy")

    st.subheader("2. Recipients")
    up = st.file_uploader("Upload CSV (columns: name,email) or JSON list", type=["csv", "json"])
    pasted = st.text_area("Or paste one per line:  Name, email", "Aarav Sharma, aarav@example.com\nDiya Patel, diya@example.com")
    preview: list[dict] = []
    if up:
        raw = up.read().decode()
        if up.name.endswith(".json"):
            preview = json.loads(raw)
            if isinstance(preview, dict) and "recipients" in preview:
                preview = preview["recipients"]
        else:
            for line in raw.splitlines()[1:]:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2 and parts[0] and parts[1]:
                    preview.append({"name": parts[0], "email": parts[1]})
    else:
        for line in pasted.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2 and parts[0] and parts[1]:
                preview.append({"name": parts[0], "email": parts[1]})
    st.write(f"{len(preview)} recipients")
    st.dataframe(preview[:50])
    key = st.text_input("Idempotency-Key (optional)", "")
    if st.button("Submit bulk job", type="primary", disabled=not preview):
        try:
            status, out = api("POST", "/jobs", {"title": title, "course_name": course, "issuer": issuer, "recipients": preview},
                              {"Idempotency-Key": key} if key else None)
            st.success(f"Accepted (HTTP {status}) — job `{out['id']}`")
            st.code(out["id"])
            st.session_state["job_id"] = out["id"]
        except Exception as e:
            st.error(str(e))

with tab2:
    job_id = st.text_input("Job ID", st.session_state.get("job_id", ""))
    auto = st.checkbox("Auto-refresh while processing", True)
    if job_id and st.button("Fetch status", type="primary"):
        st.session_state["job_id"] = job_id
    job_id = st.session_state.get("job_id", "")
    if job_id:
        try:
            _, job = api("GET", f"/jobs/{job_id}")
            st.progress(min(1.0, job["progress_percent"] / 100), f"{job['status']} — {job['progress_percent']}% ({job['succeeded']}/{job['total']} ok, {job['failed']} failed)")
            st.json({k: job[k] for k in ("id", "title", "status", "total", "succeeded", "failed", "progress_percent")})
            _, certs = api("GET", f"/jobs/{job_id}/certificates?limit=100"), None
            rows = [{"name": c["recipient_name"], "email": c["recipient_email"], "status": c["status"], "error": c.get("error_message") or "", "id": c["id"]} for c in _[1]]
            st.dataframe(rows, use_container_width=True)
            col1, col2 = st.columns(2)
            if job["status"] in ("completed", "completed_with_errors") and col1.button("Download ZIP"):
                data, _ = download_bytes(f"/jobs/{job_id}/download")
                st.download_button("Save certificates.zip", data, "certificates.zip", "application/zip")
            ok = [c for c in _[1] if c["status"] == "succeeded"][:5]
            if ok:
                sel = col2.selectbox("Preview single PDF", [c["id"] for c in ok])
                if sel and col2.button("Download PDF"):
                    data, _ = download_bytes(f"/certificates/{sel}/download")
                    st.download_button("Save certificate.pdf", data, "certificate.pdf", "application/pdf")
            if job["status"] not in ("completed", "completed_with_errors", "failed") and auto:
                time.sleep(2)
                st.rerun()
        except Exception as e:
            st.error(str(e))
    st.caption("Tip: start API first — `python -m app.cli serve --port 8000`, then `streamlit run streamlit_app.py`.")
