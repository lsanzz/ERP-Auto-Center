import importlib.util
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Import explícito por caminho para evitar conflito com o pacote
# lshub_erp/app existente no projeto principal.
app_file = BASE_DIR / "app.py"
spec = importlib.util.spec_from_file_location("lshub_landing_app", app_file)

if spec is None or spec.loader is None:
    raise RuntimeError("Não foi possível carregar website/app.py")

module = importlib.util.module_from_spec(spec)
sys.modules["lshub_landing_app"] = module
spec.loader.exec_module(module)

application = module.app
