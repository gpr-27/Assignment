"""Streamlit front end. It only talks to the API over HTTP, like any other client would."""

import json
import os

import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(page_title="RAG Assistant", page_icon="📚", layout="wide")


def api(method: str, path: str, **kwargs):
    headers = {"Authorization": f"Bearer {st.session_state.token}"} if "token" in st.session_state else {}
    try:
        response = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=60, **kwargs)
    except requests.ConnectionError:
        st.error(f"Cannot reach the API at {API_URL}")
        st.stop()
    if response.status_code == 401 and "token" in st.session_state:
        del st.session_state.token
        st.rerun()
    return response


def show_error(response) -> None:
    detail = response.json().get("detail", response.text) if response.content else response.reason
    st.error(detail if isinstance(detail, str) else json.dumps(detail))


def stream_answer(session_id: int, question: str, collection_ids: list[int] | None):
    """Reads the SSE stream: yields answer text for st.write_stream and keeps citations aside."""
    st.session_state.last_citations = []
    response = requests.post(
        f"{API_URL}/chat/sessions/{session_id}/ask",
        json={"question": question, "collection_ids": collection_ids or None},
        headers={"Authorization": f"Bearer {st.session_state.token}"},
        stream=True,
        timeout=120,
    )
    if response.status_code != 200:
        yield f"⚠️ {response.json().get('detail')}"
        return
    event = None
    got_text = False
    for line in response.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("event: "):
            event = line.removeprefix("event: ")
        elif line.startswith("data: "):
            try:
                data = json.loads(line.removeprefix("data: "))
            except json.JSONDecodeError:
                continue
            if event == "token":
                text = data.get("text") or ""
                if text:
                    got_text = True
                    yield text
            elif event == "citations":
                st.session_state.last_citations = data
            elif event == "error":
                got_text = True
                yield f"⚠️ {data.get('detail', 'The AI model failed.')}"
    if not got_text:
        yield "⚠️ No response received from the AI. Please try again."


def show_citations(citations) -> None:
    if citations:
        with st.expander(f"Sources ({len(citations)})"):
            for c in citations:
                page = f", page {c['page']}" if c["page"] else ""
                st.markdown(f"**[{c['number']}] {c['filename']}{page}**")
                st.caption(c["snippet"])


# ---------- Login ----------
if "token" not in st.session_state:
    st.title("📚 RAG Assistant")
    login_tab, register_tab = st.tabs(["Log in", "Register"])
    with login_tab, st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Log in"):
            r = api("POST", "/auth/login", data={"username": email, "password": password})
            if r.ok:
                st.session_state.token = r.json()["access_token"]
                st.rerun()
            show_error(r)
    with register_tab, st.form("register"):
        email = st.text_input("Email", key="reg_email")
        password = st.text_input("Password (min 8 characters)", type="password", key="reg_pw")
        if st.form_submit_button("Create account"):
            r = api("POST", "/auth/register", json={"email": email, "password": password})
            if r.ok:
                st.success("Account created, please log in.")
            else:
                show_error(r)
    st.stop()


# ---------- Sidebar: namespace + collection ----------
me = api("GET", "/auth/me").json()
with st.sidebar:
    st.write(f"Signed in as **{me['email']}** ({me['role']})")
    if st.button("Log out"):
        st.session_state.clear()
        st.rerun()
    st.divider()

    namespaces = api("GET", "/namespaces").json()
    with st.popover("➕ New namespace"):
        name = st.text_input("Namespace name")
        if st.button("Create namespace") and name:
            r = api("POST", "/namespaces", json={"name": name})
            if r.ok:
                st.rerun()
            else:
                show_error(r)
    if not namespaces:
        st.info("Create a namespace to get started.")
        st.stop()
    namespace = st.selectbox("Namespace", namespaces, format_func=lambda n: n["name"])

    collections = api("GET", f"/namespaces/{namespace['id']}/collections").json()
    with st.popover("➕ New collection"):
        name = st.text_input("Collection name")
        description = st.text_input("Description (optional)")
        if st.button("Create collection") and name:
            r = api("POST", f"/namespaces/{namespace['id']}/collections",
                    json={"name": name, "description": description or None})
            if r.ok:
                st.rerun()
            else:
                show_error(r)

docs_tab, chat_tab = st.tabs(["📄 Documents", "💬 Chat"])

# ---------- Documents ----------
with docs_tab:
    if not collections:
        st.info("Create a collection in the sidebar first.")
    else:
        collection = st.selectbox("Collection", collections, format_func=lambda c: c["name"])
        uploaded = st.file_uploader("Upload PDF, TXT or MD", type=["pdf", "txt", "md"])
        if uploaded and st.button("Upload"):
            r = api("POST", f"/collections/{collection['id']}/documents",
                    files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)})
            if r.ok:
                st.success(f"Uploaded {uploaded.name}, indexing…")
            else:
                show_error(r)

        st.subheader("Documents")
        if st.button("🔄 Refresh"):
            st.rerun()
        icons = {"ready": "🟢", "processing": "🟡", "failed": "🔴"}
        for doc in api("GET", f"/collections/{collection['id']}/documents").json():
            col1, col2, col3 = st.columns([6, 1, 1])
            col1.write(f"{icons.get(doc['status'], '')} **{doc['filename']}** · {doc['status']} · "
                       f"{doc['num_chunks']} chunks · {doc['size_bytes'] // 1024} KB")
            if doc["error"]:
                col1.caption(f"Error: {doc['error']}")
            if col2.button("Re-index", key=f"re{doc['id']}"):
                api("POST", f"/documents/{doc['id']}/reindex")
                st.rerun()
            if col3.button("Delete", key=f"del{doc['id']}"):
                api("DELETE", f"/documents/{doc['id']}")
                st.rerun()

# ---------- Chat ----------
with chat_tab:
    sessions = [s for s in api("GET", "/chat/sessions").json() if s["namespace_id"] == namespace["id"]]
    left, right = st.columns([3, 1])
    if right.button("➕ New chat"):
        api("POST", "/chat/sessions", json={"namespace_id": namespace["id"]})
        st.rerun()
    if not sessions:
        st.info("Start a new chat.")
        st.stop()
    session = left.selectbox("Chat", sessions, format_func=lambda s: s["title"] or f"New chat #{s['id']}")
    selected = st.multiselect("Search only in (optional)", collections, format_func=lambda c: c["name"])

    for message in api("GET", f"/chat/sessions/{session['id']}/messages").json():
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            show_citations(message["citations"])

    if question := st.chat_input("Ask a question about your documents"):
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            st.write_stream(stream_answer(session["id"], question, [c["id"] for c in selected]))
            show_citations(st.session_state.get("last_citations"))
