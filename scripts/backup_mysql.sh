#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?Configure DATABASE_URL}"
backup_dir="${BACKUP_DIR:-./backups}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"
mkdir -p "$backup_dir"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$backup_dir/erp_auto_center_$stamp.sql.gz"

python - "$DATABASE_URL" "$target" <<'PY'
import gzip
import subprocess
import sys
from sqlalchemy.engine import make_url

url = make_url(sys.argv[1])
if url.get_backend_name() != "mysql":
    raise SystemExit("O backup automatizado aceita apenas MySQL.")
command = ["mysqldump", "--single-transaction", "--routines", "--triggers",
           "-h", url.host or "localhost", "-P", str(url.port or 3306),
           "-u", url.username or "root", f"-p{url.password or ''}", url.database]
with gzip.open(sys.argv[2], "wb") as output:
    subprocess.run(command, stdout=output, check=True)
PY

find "$backup_dir" -type f -name 'erp_auto_center_*.sql.gz' -mtime "+$retention_days" -delete
echo "Backup criado: $target"
