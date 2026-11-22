"""Build backend/data/catalog_seed.json from the two PDEU spreadsheets.

    .venv\Scripts\python.exe scripts\build_catalog_seed.py ..\sample
"""
import json
import re
import sys
from pathlib import Path

import openpyxl

CODE = re.compile(r"^\d{2}[A-Z]{2}\d{3}[A-Z]?$")


def clean(s) -> str:
    return " ".join(str(s or "").replace("\ufffd", "-").split())


def main(folder: Path) -> None:
    courses: dict[str, dict] = {}
    wb = openpyxl.load_workbook(folder / "PDEU_CSE_Subjects_Course_Codes.xlsx", data_only=True)
    ws = wb.worksheets[0]                       # Subjects Sem I-VIII (2020-24)
    for sem, code, name, *_ in ws.iter_rows(min_row=2, values_only=True):
        code = clean(code).upper()
        if CODE.match(code):
            courses[code] = {"code": code, "name": clean(name), "semester": clean(sem)}
    for _slot, sem, code, name, *_ in wb["Electives (2020-24)"].iter_rows(min_row=2, values_only=True):
        code = clean(code).upper()
        if CODE.match(code) and code not in courses:
            courses[code] = {"code": code, "name": clean(name), "semester": clean(sem)}

    coordinators = []
    wb2 = openpyxl.load_workbook(folder / "PDEU_CSE_Faculty_List.xlsx", data_only=True)
    for sr, name, desig, *_ in wb2.worksheets[0].iter_rows(min_row=2, values_only=True):
        if isinstance(sr, int) and clean(name):
            coordinators.append({"name": clean(name), "designation": clean(desig)})

    out = Path(__file__).resolve().parent.parent / "backend" / "data" / "catalog_seed.json"
    out.write_text(json.dumps({"courses": sorted(courses.values(), key=lambda c: c["code"]),
                               "coordinators": coordinators}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(courses)} courses, {len(coordinators)} coordinators -> {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "../sample"))
