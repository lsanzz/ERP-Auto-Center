#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?Configure DATABASE_URL}"
backup_file="${1:?Uso: scripts/restore_mysql.sh arquivo.sql.gz}"
test -f "$backup_file"

python - "$DATABASE_URL" "$backup_file" <<'PY'
import gzip
import subprocess
import sys
from sqlalchemy.engine import make_url

url = make_url(sys.argv[1])
if url.get_backend_name() != "mysql":
    raise SystemExit("A restauração automatizada aceita apenas MySQL.")
command = ["mysql", "-h", url.host or "localhost", "-P", str(url.port or 3306),
           "-u", url.username or "root", f"-p{url.password or ''}", url.database]
with gzip.open(sys.argv[2], "rb") as source:
    subprocess.run(command, stdin=source, check=True)
PY
echo "Restauração concluída. Execute flask --app run.py db upgrade."
