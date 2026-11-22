# Course File Generator — Version 1

A local web app for course coordinators. Upload documents of different formats, file them into fixed
**A–Z sections**, and generate **one consolidated PDF** containing every assigned document in A–Z order.

Uses **Appwrite** for login (Auth), data (TablesDB) and files (Storage). Runs locally or on any Docker host — see *Appwrite setup* and *Hosting* below.

## Version 1 scope

Included: multi-file upload, automatic type detection, conversion of Word/Excel/PowerPoint/TXT to PDF
(LibreOffice), a fixed A–Z table with editable descriptions, Select / View / Upload / Drag actions per
section, one universal PDF preview panel, final PDF generation, and JSON-file persistence.

Deliberately **not** included: login, database, multiple projects, page selection, multiple files per
section, file sorting, reordering of A–Z rows, trash, cover/divider pages, deployment.

## Technology

| Layer | Tech |
|---|---|
| Frontend | HTML5, CSS3, vanilla JavaScript (ES modules), PDF.js (vendored in `frontend/vendor/pdfjs`, works offline) |
| Backend | Python 3.12+, FastAPI, Uvicorn, Pydantic, python-multipart |
| Conversion | LibreOffice headless (via `subprocess`, argument list, no `shell=True`) |
| PDF merge | pypdf |
| Auth / DB / Files | Appwrite Auth, TablesDB (`projects`, `files`), Storage bucket `course-files` |

## Setup (Windows PowerShell)

1. **Python 3.12+** – install from <https://www.python.org/downloads/> (tick *Add python.exe to PATH*).
   Node.js is **not** required.
2. **Virtual environment and dependencies** (from the `course-file-generator` folder):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r backend\requirements.txt
   ```
   (If script activation is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or skip
   activation and call `.\.venv\Scripts\python.exe` directly.)
   `requirements.txt` also lists packages used only by the test script (`httpx`, `reportlab`, `python-docx`,
   `openpyxl`, `python-pptx`).
3. **LibreOffice** – install from <https://www.libreoffice.org/download/>. The app looks for `soffice.exe`:
   1. in the `LIBREOFFICE_PATH` environment variable (path to `soffice.exe`, or to the `program` folder),
   2. on `PATH`,
   3. in `C:\Program Files\LibreOffice\program` and `C:\Program Files (x86)\LibreOffice\program`.

   To configure a custom location for the current session:
   ```powershell
   $env:LIBREOFFICE_PATH = "D:\Apps\LibreOffice\program\soffice.exe"
   ```
   Permanently: `setx LIBREOFFICE_PATH "D:\Apps\LibreOffice\program\soffice.exe"` (then open a new terminal).
   If LibreOffice is missing the app shows a clear banner; PDFs still work, other formats are rejected with a
   message (a conversion is never faked).

## Appwrite setup

Project `6b03285a00183e69a96f` (Frankfurt) already contains: database `coursefile` with tables `projects` and
`files`, and the private bucket `course-files`. Nothing in the browser talks to Appwrite directly — the FastAPI
backend does everything with a server API key, so the key never reaches users.

1. Appwrite console → **Overview → Integrations → API keys → Create API key**. Scopes: `users.read`, `users.write`,
   `sessions.write`, `databases.read`, `databases.write`, `tables.read`, `tables.write`, `rows.read`, `rows.write`,
   `files.read`, `files.write`, `buckets.read`. Put it in `.env` as `APPWRITE_API_KEY` (copy `.env.example`).
2. Create faculty accounts (replaces `faculty.txt`; login is now **email + password**):
   ```powershell
   .\.venv\Scripts\python.exe scripts\manage_faculty.py add "Dr Jane Doe" jane@university.edu
   .\.venv\Scripts\python.exe scripts\manage_faculty.py list
   ```
   Only users with the `faculty` label can use the app, even if Appwrite sign-ups are open.
3. `pip install -r backendequirements.txt`, then run uvicorn as below.

Per-file limit is 50,000,000 bytes (Appwrite free plan). LibreOffice is still required wherever the backend runs.

## Hosting

The backend needs LibreOffice, so it runs as a container (`Dockerfile`) on a Docker host (Render, Railway, Fly.io,
a VPS…), not on Appwrite Functions/Sites. The same container serves the frontend. On the host:
set the `APPWRITE_*` variables from `.env.example` (leave `CFG_COOKIE_SECURE_AUTO` unset so cookies are `Secure`),
expose the port in `$PORT`, and use `/api/health` as the health check. Run a single instance (writes are
serialised per user inside the process). In Appwrite console → **Overview → Platforms**, nothing needs adding
because the browser never calls Appwrite itself.

## Running

**Backend + frontend together (simplest):**
```powershell
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
Open <http://127.0.0.1:8000> — FastAPI also serves the frontend.

**Frontend on its own static server (optional, port 5500):**
```powershell
# terminal 1 – backend as above
# terminal 2
python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```
Open <http://127.0.0.1:5500>. The page then calls the backend at `http://127.0.0.1:8000` (CORS is allowed for
localhost origins only). Open it through `http://`, not by double-clicking `index.html` (ES modules need HTTP).

API docs (Swagger): <http://127.0.0.1:8000/docs>

## Using the app

1. Fill in the **Course Details** (saved automatically).
2. **Upload Files** – pick any mix of PDF/DOC/DOCX/XLS/XLSX/PPT/PPTX/TXT. Each is validated, converted to PDF
   if needed, and listed under **Uploaded Files** (a failed file shows an error and is not stored).
3. Each A–Z row has:
   - **Description** – free text, auto-saved (starts blank; nothing is pre-filled).
   - **Select File** – choose an uploaded file (search box). Replacing/moving asks for confirmation.
   - **View File** – opens the preview panel (disabled when the row is empty).
   - **Upload File** – upload straight into that section (asks before replacing; the old file stays in the library, unassigned).
   - **⋮⋮ drag handle** – drag onto another row to swap/move that row's *content*.
4. The **Uploaded Files** table also has an *Assign to…* dropdown for each file.
5. **Generate Final PDF** → shows output name, document count, page count, with **Preview** and **Download**.

## A–Z ordering and drag-and-drop

- The 26 slots are generated in code (`A`…`Z`) and the array position of a slot is never modified.
  A slot = `letter` (immutable) + `description` + `file_id` (or none).
- Dragging moves **content** (description + file) — never the rows. Only the ⋮⋮ handle starts a drag
  (custom pointer-event implementation, no sortable-list library). Esc or dropping outside the table cancels.
- Drop semantics (`POST /api/slots/swap`, one atomic state change):
  both filled → swap; destination empty → move; description-only slots swap like any other; both empty → no-op.
- The UI updates only after the server confirms; on failure the previous state is kept and an error is shown.

## Conversion workflow

`upload → sanitise name → detect by extension + MIME → stream to disk (size limit) → check content signature
(PDF header, OOXML zip structure, OLE header for legacy Office, no binary in TXT) → PDF: validate with pypdf
(rejects corrupt/password-protected) / others: LibreOffice headless → validate resulting PDF → store`.

- Originals are stored once as `storage/uploads/<id>.<ext>` and never modified.
- Converted PDFs: `storage/converted/<id>.pdf`. For PDF uploads the original is used directly.
- Each conversion uses its own temp directory and LibreOffice profile (`-env:UserInstallation`), a 180 s
  timeout, and the whole process tree is killed on timeout.

## Final PDF generation

Slots are read in A→Z order; each assigned file's normalised PDF is appended in full with pypdf; empty
sections are skipped; no cover, divider or blank pages. Output: `storage/output/<CourseCode>_Course_File.pdf`
(e.g. `24CP101T_Course_File.pdf`) or `FINAL_COURSE_FILE.pdf` when no course code is set. If an assigned file
is missing on disk the generation stops with a clear message rather than producing a partial file.

## API

All errors return `{"detail": "<friendly message>", "code": "<optional>"}`; tracebacks only go to the backend terminal.

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Status + LibreOffice availability/path |
| `POST /api/files/upload` | Multipart `files` (one or many). Returns per-file `results[]` (`ok`, `file`/`error`) |
| `GET /api/files` · `GET /api/files/{id}` | Library / one file (`assigned_to` shows its section) |
| `GET /api/files/{id}/preview` | The normalised PDF, inline (used by PDF.js) |
| `POST /api/convert/word` `/excel` `/ppt` `/txt` | Multipart `file`; accepts only that category (DOC/DOCX, XLS/XLSX, PPT/PPTX, TXT); same shared pipeline; returns file info |
| `POST /api/convert/pdf` | PDF upload + validation only |
| `GET /api/slots` | Full state: `course`, 26 `slots`, `files`, `summary`, `last_output` |
| `PUT /api/slots/{letter}` | Body `{"description": "..."}` |
| `POST /api/slots/{letter}/assign` | Body `{"file_id", "force"}`. `409` (`slot_occupied` / `file_assigned_elsewhere`) unless `force` is true |
| `POST /api/slots/{letter}/upload` | Multipart `file`, form `replace`. `409` if occupied and `replace` is false |
| `POST /api/slots/swap` | Body `{"from": "A", "to": "C"}` — swap/move content |
| `PUT /api/project` | Course details (`course_name`, `course_code`, `department`, `semester`, `academic_year`, `course_coordinator`) |
| `POST /api/generate` | Builds the final PDF → `filename`, `total_documents`, `total_pages` |
| `GET /api/generate/download` | The final PDF (`?inline=true` for preview) |

Slot-modifying endpoints return the complete updated state. Invalid letters/IDs → `400`; unknown file → `404`;
unsupported or invalid type → `415`; too large → `413`; bad/corrupt/password-protected file → `422`;
LibreOffice missing → `503`.

## Storage and persistence (legacy local layout — superseded by Appwrite)

```
storage/
  uploads/      original uploaded files (<uuid>.<ext>)
  converted/    PDFs produced by LibreOffice (<uuid>.pdf)
  output/       generated final PDF
  temp/         scratch space for conversions (cleaned after each one)
  project.json  course details, 26 slots, file records
```
`project.json` is written atomically (temp file → fsync → `os.replace`) after every change; if saving fails the
in-memory state is not changed. If it is ever unreadable it is renamed `project.corrupt-<time>.json` and a fresh
project starts. Delete `storage/project.json` (and the files in the subfolders) to start over.

## Tests

```powershell
.\.venv\Scripts\python.exe tests\run_tests.py
```
Starts an isolated backend (port 8765, temporary storage) and checks uploads of every format, all conversion
endpoints, error cases, assignment/replacement rules, all drag/swap cases, A–Z order, final merge order
(including upload-order independence), restart recovery and missing-file handling. Requires LibreOffice.

## Known limitations

- Single project, single user; one `project.json`. Concurrent browser tabs share the same state.
- Files cannot be deleted from the library in Version 1 (no trash).
- Conversion is synchronous: large Office files can take a while (timeout 180 s). Upload limit 50 MB per file.
- Layout of converted documents is whatever LibreOffice produces; very wide Excel sheets may split across pages.
  Fonts missing on the machine are substituted.
- TXT encoding is auto-detected by LibreOffice; unusual encodings may render incorrectly.
- Password-protected Word/Excel/PowerPoint files fail to convert (reported as a conversion error).
- Drag-and-drop uses pointer events (mouse/touch/pen); there is no keyboard alternative — use *Select File* instead.

## Future versions (not implemented)

Version 2 and later: faculty login and authentication; database connectivity; persistent storage for multiple
projects; global deployment so faculty can use it online; multi-user support; additional course-file templates.
