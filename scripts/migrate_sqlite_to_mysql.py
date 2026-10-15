import argparse

from app.config import CFG
from app.services.migration import migrate_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate application data to MySQL")
    parser.add_argument("--source", default="sqlite:///./data.db")
    parser.add_argument("--target", default=CFG.database_url)
    args = parser.parse_args()
    if not args.target or not args.target.startswith("mysql+"):
        raise SystemExit("target must be a MySQL SQLAlchemy URL")
    result = migrate_database(args.source, args.target)
    print("migration_ok")
    for table, count in result.items():
        print(f"{table}={count}")


if __name__ == "__main__":
    main()
