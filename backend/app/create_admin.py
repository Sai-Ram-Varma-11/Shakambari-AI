"""Create the first super administrator safely (password is prompted, never stored in files).
Usage: python -m app.create_admin --email you@example.org --name "Your Name" [--institution-code MYCODE --institution-name "My Campus"]"""
import argparse, getpass

from .db import Base, SessionLocal, engine
from .models import Institution, User
from .routers.auth import check_pw
from .security import hash_password


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True); ap.add_argument("--name", required=True)
    ap.add_argument("--institution-code", default="MAIN"); ap.add_argument("--institution-name", default="My Institution")
    a = ap.parse_args()
    pw = getpass.getpass("Password: ")
    if pw != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match")
    check_pw(pw)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    inst = db.query(Institution).filter_by(code=a.institution_code).first() or Institution(name=a.institution_name, code=a.institution_code, data_mode="real", settings={})
    db.add(inst); db.flush()
    if db.query(User).filter_by(email=a.email.lower()).first():
        raise SystemExit("A user with this email already exists")
    db.add(User(email=a.email.lower(), name=a.name, role="super_admin", password_hash=hash_password(pw), institution_id=inst.id)); db.commit()
    print("Super administrator created.")


if __name__ == "__main__":
    main()
