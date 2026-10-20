import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.models import db
from app.data_migration.detailed_orders import complete_orders

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('file', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    app = create_app({'AUTO_CREATE_SCHEMA': False})
    with app.app_context():
        try:
            report = complete_orders(args.file, apply=args.apply)
            if args.apply:
                db.session.commit()
            else:
                db.session.rollback()
            print(json.dumps(report, indent=2))
        except Exception:
            db.session.rollback()
            raise
