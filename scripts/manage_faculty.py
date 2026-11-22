"""Create / list / reset faculty accounts in Appwrite Auth.

Run from the project root (needs APPWRITE_API_KEY in .env):
    .venv\Scripts\python.exe scripts\manage_faculty.py add "Dr Jane Doe" jane@university.edu
    .venv\Scripts\python.exe scripts\manage_faculty.py list
    .venv\Scripts\python.exe scripts\manage_faculty.py reset-password jane@university.edu
`add` and `reset-password` print a generated password once; hand it to the faculty member.
"""
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from appwrite.id import ID                      # noqa: E402
from appwrite.query import Query                # noqa: E402

from backend import config                      # noqa: E402
from backend.services import appwrite_client    # noqa: E402


def new_password(n: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def find(email: str):
    res = appwrite_client.users().list([Query.equal("email", [email.lower()])])
    users = [u.to_dict() for u in res.users]
    return users[0] if users else None


def main(argv: list[str]) -> int:
    if not config.appwrite_configured():
        print("Set APPWRITE_PROJECT_ID and APPWRITE_API_KEY in .env first.")
        return 1
    users = appwrite_client.users()
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "add" and len(argv) == 4:
        name, email = argv[2], argv[3].lower()
        pw = new_password()
        user = users.create(ID.unique(), email=email, password=pw, name=name)
        users.update_labels(user.id, [config.FACULTY_LABEL])
        print(f"Created {name} <{email}>\nPassword: {pw}")
    elif cmd == "reset-password" and len(argv) == 3:
        u = find(argv[2])
        if not u:
            print("No such user.")
            return 1
        pw = new_password()
        users.update_password(u["$id"], pw)
        print(f"New password for {argv[2]}: {pw}")
    elif cmd == "list":
        for u in users.list().users:
            d = u.to_dict()
            flag = "faculty" if config.FACULTY_LABEL in (d.get("labels") or []) else "NOT faculty"
            print(f"{d.get('name', ''):30} {d.get('email', ''):35} {flag}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
