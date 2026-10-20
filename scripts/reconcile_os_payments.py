"""Preview receivables-to-OS payment recovery; --apply commits verified matches."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.models import db
from app.data_migration.payments import reconcile_os_payments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    app = create_app({'AUTO_CREATE_SCHEMA': False})
    with app.app_context():
        try:
            report = reconcile_os_payments(args.file, apply=args.apply)
            if args.apply:
                db.session.commit()
            else:
                db.session.rollback()
            print(json.dumps(report, ensure_ascii=True, indent=2))
        except Exception:
            db.session.rollback()
            raise


if __name__ == '__main__':
    main()
