import sqlite3

db_path = r"instance\erp_auto_center.db"
output_path = "dump_sqlite.sql"

conn = sqlite3.connect(db_path)

with open(output_path, "w", encoding="utf-8") as f:
    for line in conn.iterdump():
        f.write(f"{line}\n")

conn.close()

print(f"Dump criado em: {output_path}")