r"""End-to-end API tests. Starts its own backend on port 8765 with an isolated storage folder.

Run from the project root:   .venv\Scripts\python.exe tests\run_tests.py
Requires LibreOffice for the conversion tests.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
STORAGE = Path(tempfile.mkdtemp(prefix="cfg_test_"))
FACULTY = Path(tempfile.mkdtemp(prefix="cfg_fac_")) / "faculty.txt"
FACULTY.write_text("# test list" + chr(10) + "Test User One" + chr(10) + "Second Person" + chr(10), encoding="utf-8")
USER = STORAGE / "users" / "testuserone"   # private folder of "Test User One"
LETTERS = [chr(c) for c in range(65, 91)]
passed = failed = 0
server = None


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name} {extra}")


def start_server():
    global server
    env = dict(os.environ, CFG_STORAGE_DIR=str(STORAGE), CFG_FACULTY_FILE=str(FACULTY))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=env)
    for _ in range(60):
        try:
            if httpx.get(f"{BASE}/api/health", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


def client(password="Test USER one", login_id="PDEU@facultycse"):
    c = httpx.Client(base_url=BASE, timeout=240)
    r = c.post("/api/auth/login", json={"login_id": login_id, "password": password})
    assert r.status_code == 200, r.text
    return c


def stop_server():
    global server
    if server:
        server.terminate()
        server.wait(10)
        server = None


# ---------------------------------------------------------- sample files
def make_pdf(marker, pages=1):
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(pages):
        c.drawString(100, 750, f"{marker} page {i + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


def make_docx(marker):
    d = Document(); d.add_paragraph(marker)
    b = io.BytesIO(); d.save(b); return b.getvalue()


def make_xlsx(marker):
    w = Workbook(); w.active["A1"] = marker
    b = io.BytesIO(); w.save(b); return b.getvalue()


def make_pptx(marker):
    p = Presentation(); s = p.slides.add_slide(p.slide_layouts[5]); s.shapes.title.text = marker
    b = io.BytesIO(); p.save(b); return b.getvalue()


def make_encrypted_pdf():
    r = PdfReader(io.BytesIO(make_pdf("SECRET")))
    w = PdfWriter(); w.append(r); w.encrypt("pw")
    b = io.BytesIO(); w.write(b); return b.getvalue()


def pdf_text(data: bytes):
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages]


def up(client, name, data, ctype="application/octet-stream"):
    r = client.post("/api/files/upload", files=[("files", (name, data, ctype))])
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def slots(client):
    return client.get("/api/slots").json()


def view(client):
    return [(s["letter"], s["description"], s["file"]["original_name"] if s["file"] else None)
            for s in slots(client)["slots"]]


def main():
    start_server()
    anon = httpx.Client(base_url=BASE, timeout=30)
    try:
        print("[Login]")
        check("API blocked without login (401)", anon.get("/api/slots").status_code == 401 and anon.get("/api/files").status_code == 401
              and anon.post("/api/generate").status_code == 401)
        check("preview blocked without login", anon.get("/api/files/" + "0" * 32 + "/preview").status_code == 401)
        check("health is public", anon.get("/api/health").status_code == 200)
        check("/me without login -> 401", anon.get("/api/auth/me").status_code == 401)
        check("wrong password rejected", anon.post("/api/auth/login", json={"login_id": "pdeu@facultycse", "password": "nobody"}).status_code == 401)
        check("wrong login id rejected", anon.post("/api/auth/login", json={"login_id": "someone@else", "password": "testuserone"}).status_code == 401)
        check("empty password rejected", anon.post("/api/auth/login", json={"login_id": "pdeu@facultycse", "password": "  "}).status_code == 401)
        check("forged cookie rejected", httpx.get(BASE + "/api/slots", cookies={"cfg_session": "abc.def"}).status_code == 401)
        c = client()   # login id caps ignored; password "Test USER one" == name without spaces, caps ignored
        me = c.get("/api/auth/me")
        check("login ok (caps/spaces ignored) and /me returns name", me.status_code == 200 and me.json()["name"] == "Test User One", me.text)
        other = client("secondperson")
        check("second faculty logs in", other.get("/api/auth/me").json()["name"] == "Second Person")
        up(c, "mine.txt", b"only user one sees this", "text/plain")
        check("each faculty has private files", len(c.get("/api/files").json()) == 1 and other.get("/api/files").json() == [])
        pid = c.get("/api/files").json()[0]["id"]
        check("other faculty cannot preview my file", other.get(f"/api/files/{pid}/preview").status_code == 404)
        other.put("/api/slots/A", json={"description": "second person's"})
        check("descriptions are private too", slots(c)["slots"][0]["description"] == "")
        check("private folders created", (STORAGE / "users" / "secondperson" / "project.json").exists() and (USER / "project.json").exists())
        c.post("/api/auth/logout")
        check("logout ends session", c.get("/api/slots").status_code == 401)
        c = client()
        # (restart below wipes storage so later sections start from a known state)
        stop_server(); shutil.rmtree(STORAGE, ignore_errors=True); STORAGE.mkdir(parents=True); start_server()
        c = client()
        print()
        h = c.get("/api/health").json()
        print("LibreOffice:", h["libreoffice"])
        check("health ok", h["status"] == "ok")
        check("LibreOffice available", h["libreoffice"]["available"])

        print("\n[Initial state]")
        s = slots(c)
        check("26 slots A..Z", [x["letter"] for x in s["slots"]] == LETTERS)
        check("descriptions blank", all(x["description"] == "" for x in s["slots"]))

        print("\n[TEST 6 / uploads + conversion of every format]")
        samples = {
            "A": ("vision.pdf", make_pdf("MARK_A_PDF", 2), "application/pdf"),
            "B": ("syllabus.docx", make_docx("MARK_B_DOCX"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "C": ("academic_calendar.xlsx", make_xlsx("MARK_C_XLSX"), ""),
            "D": ("timetable.pptx", make_pptx("MARK_D_PPTX"), "application/octet-stream"),
            "E": ("notes.txt", b"MARK_E_TXT hello world\nsecond line\n", "text/plain"),
        }
        ids = {}
        for L, (n, d, ct) in samples.items():
            r = up(c, n, d, ct)
            check(f"upload {n}", r["ok"], r.get("error"))
            ids[L] = r["file"]["id"]
            pv = c.get(f"/api/files/{ids[L]}/preview")
            check(f"  preview of {n} is a PDF with marker",
                  pv.status_code == 200 and pv.headers["content-type"] == "application/pdf"
                  and f"MARK_{L}" in "".join(pdf_text(pv.content)))
        check("library lists 5 files", len(c.get("/api/files").json()) == 5)

        print("\n[Dedicated conversion endpoints]")
        for ep, (n, d, ct) in {"word": ("x.docx", samples["B"][1], ""), "excel": ("x.xlsx", samples["C"][1], ""),
                               "ppt": ("x.pptx", samples["D"][1], ""), "txt": ("x.txt", samples["E"][1], "text/plain"),
                               "pdf": ("x.pdf", samples["A"][1], "application/pdf")}.items():
            r = c.post(f"/api/convert/{ep}", files={"file": (n, d, ct)})
            check(f"POST /api/convert/{ep}", r.status_code == 200 and r.json()["status"] == "ready", r.text)
        r = c.post("/api/convert/word", files={"file": ("x.xlsx", samples["C"][1], "")})
        check("wrong endpoint category -> 400", r.status_code == 400, r.text)
        extra_ids = [f["id"] for f in c.get("/api/files").json() if f["id"] not in ids.values()]

        print("\n[Error handling]")
        r = up(c, "bad.exe", b"MZ....", "application/x-msdownload")
        check("unsupported type", not r["ok"] and "Unsupported" in r["error"], r)
        r = up(c, "empty.pdf", b"", "application/pdf")
        check("empty upload", not r["ok"] and "empty" in r["error"].lower(), r)
        r = up(c, "fake.docx", b"this is not a zip file at all", "")
        check("corrupted docx", not r["ok"] and "corrupt" in r["error"].lower(), r)
        r = up(c, "fake.pdf", b"not a pdf", "application/pdf")
        check("corrupted pdf", not r["ok"], r)
        r = up(c, "locked.pdf", make_encrypted_pdf(), "application/pdf")
        check("password-protected pdf", not r["ok"] and "password" in r["error"].lower(), r)
        r = up(c, "image.pdf", make_pdf("x"), "image/png")
        check("invalid MIME type", not r["ok"] and "MIME" in r["error"], r)
        r = up(c, "../../evil.txt", b"hello", "text/plain")
        check("path traversal name sanitised", r["ok"] and r["file"]["original_name"] == "evil.txt", r)
        extra_ids.append(r["file"]["id"])
        big = c.post("/api/files/upload", files=[("files", ("big.pdf", b"%PDF-" + b"0" * (51 * 1024 * 1024), "application/pdf"))])
        check("oversized file", not big.json()["results"][0]["ok"] and "too large" in big.json()["results"][0]["error"], big.text[:200])
        check("invalid letter -> 400", c.put("/api/slots/1", json={"description": "x"}).status_code == 400)
        check("invalid file id -> 400", c.post("/api/slots/A/assign", json={"file_id": "nope"}).status_code == 400)
        check("unknown file id -> 404", c.post("/api/slots/A/assign", json={"file_id": "0" * 32}).status_code == 404)
        check("failed uploads left nothing behind", len(c.get("/api/files").json()) == 5 + 5 + 1)

        print("\n[Assignment + descriptions]")
        for L in "ABCD":
            r = c.post(f"/api/slots/{L}/assign", json={"file_id": ids[L]})
            check(f"assign {L}", r.status_code == 200, r.text)
            c.put(f"/api/slots/{L}", json={"description": f"Topic {L}"})
        v = view(c)
        check("A..D filled", v[0] == ("A", "Topic A", "vision.pdf") and v[3] == ("D", "Topic D", "timetable.pptx"))
        r = c.post("/api/slots/B/assign", json={"file_id": ids["A"]})
        check("move file assigned elsewhere needs confirmation (409)", r.status_code == 409 and r.json()["code"] == "file_assigned_elsewhere")
        r = c.post("/api/slots/F/assign", json={"file_id": ids["A"]})
        check("same: assigning to empty slot also 409 while assigned", r.status_code == 409)
        r = c.post("/api/slots/F/assign", json={"file_id": ids["A"], "force": True})
        v = view(c)
        check("forced move removes it from A (never in two sections)", v[0][2] is None and v[5][2] == "vision.pdf")
        check("description stayed in A when file left", v[0][1] == "Topic A")
        c.post("/api/slots/A/assign", json={"file_id": ids["A"], "force": True})
        c.post("/api/slots/F/assign", json={"file_id": extra_ids[0], "force": True})
        r = c.post("/api/slots/F/assign", json={"file_id": extra_ids[1]})
        check("replace occupied slot needs confirmation (409)", r.status_code == 409 and r.json()["code"] == "slot_occupied")

        print("\n[TEST 1-4: drag/swap semantics]")
        # Build a clean scenario using the swap API on slots P..S, independent of the above
        c.put("/api/slots/P", json={"description": "Topic P"})
        c.put("/api/slots/R", json={"description": "Topic R"})
        c.post("/api/slots/P/assign", json={"file_id": ids["E"], "force": True})
        c.post("/api/slots/R/assign", json={"file_id": extra_ids[2], "force": True})
        before = {x["letter"]: x for x in slots(c)["slots"]}
        c.post("/api/slots/swap", json={"from": "P", "to": "R"})
        after = {x["letter"]: x for x in slots(c)["slots"]}
        check("TEST 2 swap: descriptions swapped", after["P"]["description"] == before["R"]["description"] and after["R"]["description"] == before["P"]["description"])
        check("TEST 2 swap: files swapped", after["P"]["file_id"] == before["R"]["file_id"] and after["R"]["file_id"] == before["P"]["file_id"])
        # TEST 3: destination empty
        before = {x["letter"]: x for x in slots(c)["slots"]}
        c.post("/api/slots/swap", json={"from": "P", "to": "T"})
        after = {x["letter"]: x for x in slots(c)["slots"]}
        check("TEST 3 move: source emptied", after["P"]["description"] == "" and after["P"]["file_id"] is None)
        check("TEST 3 move: destination has content", after["T"]["description"] == before["P"]["description"] and after["T"]["file_id"] == before["P"]["file_id"])
        # TEST 4: description only
        c.put("/api/slots/U", json={"description": "Only text"})
        before = {x["letter"]: x for x in slots(c)["slots"]}
        c.post("/api/slots/swap", json={"from": "U", "to": "T"})
        after = {x["letter"]: x for x in slots(c)["slots"]}
        check("TEST 4 description-only swap", after["U"]["file_id"] == before["T"]["file_id"] and after["U"]["description"] == before["T"]["description"]
              and after["T"]["description"] == "Only text" and after["T"]["file_id"] is None)
        # both empty
        pre = slots(c)
        r = c.post("/api/slots/swap", json={"from": "X", "to": "Y"})
        check("both-empty swap is a no-op", r.status_code == 200 and slots(c)["slots"] == pre["slots"])
        check("swap invalid letter -> 400", c.post("/api/slots/swap", json={"from": "A", "to": "??"}).status_code == 400)
        for _ in range(5):
            c.post("/api/slots/swap", json={"from": "A", "to": "C"})
            c.post("/api/slots/swap", json={"from": "B", "to": "Z"})
        check("TEST 1 letters still A..Z in order", [x["letter"] for x in slots(c)["slots"]] == LETTERS)
        c.post("/api/slots/swap", json={"from": "A", "to": "C"})
        c.post("/api/slots/swap", json={"from": "B", "to": "Z"})

        print("\n[TEST 5: replacement via slot upload]")
        f1 = c.post("/api/slots/V/upload", files={"file": ("file1.pdf", make_pdf("MARK_FILE1"), "application/pdf")}, data={"replace": "false"})
        check("upload into empty slot", f1.status_code == 200 and slots(c)["slots"][21]["file"]["original_name"] == "file1.pdf", f1.text)
        file1_id = slots(c)["slots"][21]["file_id"]
        r = c.post("/api/slots/V/upload", files={"file": ("file2.pdf", make_pdf("MARK_FILE2"), "application/pdf")}, data={"replace": "false"})
        check("occupied slot upload w/o replace -> 409", r.status_code == 409 and r.json()["code"] == "slot_occupied")
        r = c.post("/api/slots/V/upload", files={"file": ("file2.pdf", make_pdf("MARK_FILE2"), "application/pdf")}, data={"replace": "true"})
        v = slots(c)
        check("replace: V now holds file2.pdf", r.status_code == 200 and v["slots"][21]["file"]["original_name"] == "file2.pdf")
        old = [f for f in v["files"] if f["id"] == file1_id][0]
        check("replace: file1.pdf stays in library, unassigned", old["assigned_to"] is None)
        r = c.post("/api/slots/W/upload", files={"file": ("w.docx", make_docx("MARK_W_DOCX"), "")}, data={"replace": "false"})
        check("slot upload converts non-PDF and assigns", r.status_code == 200 and slots(c)["slots"][22]["file"]["file_type"] == "DOCX", r.text)

        print("\n[TEST 7/8: final merge in A-Z order, skipping empty slots]")
        # Fresh deterministic layout through the public API
        # Files cannot be deleted in v1, so restart on empty storage for a deterministic layout
        stop_server(); shutil.rmtree(STORAGE, ignore_errors=True); STORAGE.mkdir(parents=True)
        start_server()
        c = client()
        # upload in REVERSE order to prove upload order is irrelevant
        order = ["D", "C", "B", "A"]
        fid = {}
        for L in order:
            n, d, ct = samples[L]
            fid[L] = up(c, n, d, ct)["file"]["id"]
        c.put("/api/project", json={"course_code": "24CP101T", "course_name": "Test"})
        for L in "ABCD":
            c.post(f"/api/slots/{L}/assign", json={"file_id": fid[L]})
        g = c.post("/api/generate")
        check("generate ok", g.status_code == 200, g.text)
        gj = g.json()
        check("filename uses course code", gj["filename"] == "24CP101T_Course_File.pdf", gj["filename"])
        check("4 documents", gj["total_documents"] == 4)
        dl = c.get("/api/generate/download")
        texts = pdf_text(dl.content)
        check("download is PDF attachment", dl.status_code == 200 and "attachment" in dl.headers["content-disposition"])
        check("page count matches (2+1+1+1)", gj["total_pages"] == len(texts) == 5, f"{gj['total_pages']} vs {len(texts)}")
        joined = [next((m for m in ("MARK_A", "MARK_B", "MARK_C", "MARK_D") if m in t), None) for t in texts]
        check("order is A,A,B,C,D (alphabet, not upload order)", joined == ["MARK_A", "MARK_A", "MARK_B", "MARK_C", "MARK_D"], joined)
        # swap A and C then regenerate: content order follows letters
        c.post("/api/slots/swap", json={"from": "A", "to": "C"})
        c.post("/api/generate")
        texts = pdf_text(c.get("/api/generate/download").content)
        joined = [next((m for m in ("MARK_A", "MARK_B", "MARK_C", "MARK_D") if m in t), None) for t in texts]
        check("after A<->C swap: C,B,A,A,D", joined == ["MARK_C", "MARK_B", "MARK_A", "MARK_A", "MARK_D"], joined)
        check("no blank pages", all(t.strip() for t in texts))
        c.put("/api/project", json={"course_code": ""})
        g2 = c.post("/api/generate").json()
        check("filename without course code", g2["filename"] == "FINAL_COURSE_FILE.pdf")
        check("old output removed on rename", not (USER / "output" / "24CP101T_Course_File.pdf").exists())

        print("\n[TEST 9: restart + state recovery]")
        c.put("/api/slots/B", json={"description": "Persisted description"})
        c.put("/api/project", json={"course_code": "ZZ9", "course_coordinator": "Dr. X"})
        before = c.get("/api/slots").json()
        stop_server(); start_server()
        c = client()
        after = c.get("/api/slots").json()
        check("state identical after restart", before == after)
        check("course details restored", after["course"]["course_code"] == "ZZ9" and after["course"]["course_coordinator"] == "Dr. X")
        check("last output restored", after["last_output"] and c.get("/api/generate/download").status_code == 200)
        pj = json.loads((USER / "project.json").read_text(encoding="utf-8"))
        check("project.json has 26 slots and file records", len(pj["slots"]) == 26 and len(pj["files"]) == 4
              and {"id", "original_name", "file_type", "mime_type", "size", "original_path", "converted_path", "status"} <= set(pj["files"][0]))

        print("\n[Missing / corrupted stored files]")
        fid_b = [s for s in after["slots"] if s["letter"] == "B"][0]["file_id"]
        conv = [f for f in pj["files"] if f["id"] == fid_b][0]["converted_path"]
        (USER / conv).unlink()
        r = c.get(f"/api/files/{fid_b}/preview")
        check("missing converted PDF -> 404 friendly", r.status_code == 404 and "missing" in r.json()["detail"], r.text)
        r = c.post("/api/generate")
        check("generate with missing file -> 409 friendly", r.status_code == 409 and "missing" in r.json()["detail"], r.text)
        check("no traceback leaked", "Traceback" not in r.text)

        print("\n[Frontend served]")
        r = c.get("/")
        check("index.html served", r.status_code == 200 and "COURSE FILE GENERATOR" in r.text)
        check("pdf.js vendored", c.get("/vendor/pdfjs/pdf.min.mjs").status_code == 200)
    finally:
        stop_server()
        shutil.rmtree(STORAGE, ignore_errors=True)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
