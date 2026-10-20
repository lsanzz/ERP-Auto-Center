from __future__ import annotations

import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError, generate_csrf
from werkzeug.middleware.proxy_fix import ProxyFix


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
# Fora do repositório: um deploy (git pull) não pode apagar nem conflitar com os contatos.
LEADS_FILE = PROJECT_ROOT / "instance" / "website" / "leads.jsonl"
# Usadas quando o .env não define LANDING_TEAM_OPTIONS / LANDING_PLAN_OPTIONS;
# sem elas os selects obrigatórios ficavam vazios e o formulário não podia ser enviado.
DEFAULT_TEAM_OPTIONS = "Só eu,2 a 5 pessoas,6 a 10 pessoas,Mais de 10 pessoas"
DEFAULT_PLAN_OPTIONS = "Quero orientação,Essencial,Profissional,Gestão"

# A landing fica dentro de lshub_erp/website.
# Carrega primeiro o .env principal do projeto e depois, se existir,
# website/.env. O arquivo local pode sobrescrever variáveis da landing.
load_dotenv(PROJECT_ROOT / ".env", override=False)
load_dotenv(BASE_DIR / ".env", override=True)


def _env_list(name: str, default: str = "") -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _first_form_value(*names: str) -> str:
    for name in names:
        value = request.form.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
    static_url_path="/static",
)

# GoDaddy/cPanel/Passenger fica atrás de proxy.
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1,
)

# IMPORTANTE:
# Não reutilizamos TRUSTED_HOSTS do ERP, pois ele normalmente contém
# apenas app.lshub.com.br. A landing usa sua própria variável.
landing_hosts = _env_list(
    "LANDING_TRUSTED_HOSTS",
    "lshub.com.br,www.lshub.com.br",
)
landing_env = (os.getenv("LANDING_ENV") or os.getenv("APP_ENV") or "development").lower()


def landing_secret_key(environment: str, key_file: Path) -> str:
    """Chave do .env; em produção sem ela, uma chave forte criada uma vez e compartilhada
    pelos processos do Passenger (uma chave por processo derruba sessões e CSRF)."""
    configured = os.getenv("LANDING_SECRET_KEY") or os.getenv("SECRET_KEY")
    if configured:
        if environment == "production" and len(configured) < 32:
            raise RuntimeError("LANDING_SECRET_KEY precisa ter pelo menos 32 caracteres.")
        return configured
    if environment != "production":
        return secrets.token_hex(32)
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        for _ in range(100):  # outro processo pode estar terminando de gravar
            key = key_file.read_text(encoding="utf-8").strip()
            if len(key) >= 32:
                return key
            time.sleep(0.02)
        raise RuntimeError(f"{key_file} está inválido; apague o arquivo ou defina LANDING_SECRET_KEY.")
    except OSError as exc:
        raise RuntimeError(f"Defina LANDING_SECRET_KEY no .env; não foi possível gravar {key_file}: {exc}") from exc
    key = secrets.token_hex(32)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(key)
    return key


app.config.update(
    SECRET_KEY=landing_secret_key(landing_env, PROJECT_ROOT / "instance" / "website" / "landing_secret_key"),
    TRUSTED_HOSTS=landing_hosts,
    WTF_CSRF_ENABLED=os.getenv("LANDING_CSRF_ENABLED", "true").lower() == "true",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

csrf = CSRFProtect(app)


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'",
    )
    if response.mimetype == "text/html":
        response.headers.setdefault("Cache-Control", "no-store")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.context_processor
def landing_context():
    """Variáveis globais disponíveis em todos os templates da landing."""
    whatsapp_number = re.sub(
        r"\D",
        "",
        os.getenv("WHATSAPP_NUMBER", ""),
    )
    whatsapp_message = os.getenv(
        "WHATSAPP_MESSAGE",
        "Olá! Gostaria de conhecer melhor o LS Hub.",
    )

    whatsapp_url = os.getenv("WHATSAPP_URL", "").strip()
    if not whatsapp_url and whatsapp_number:
        whatsapp_url = (
            "https://wa.me/"
            + whatsapp_number
            + "?text="
            + quote(whatsapp_message)
        )

    return {
        # Compatibilidade com templates que usam csrf ou csrf_token().
        "csrf": generate_csrf(),
        "app_url": os.getenv("ERP_URL", "https://app.lshub.com.br"),
        "login_url": os.getenv("ERP_URL", "https://app.lshub.com.br"),
        "whatsapp_url": whatsapp_url or "#",
        "sales_email": os.getenv("SALES_EMAIL", "contato@lshub.com.br"),
        "company_legal_name": os.getenv("COMPANY_LEGAL_NAME", "LS Hub"),
        "company_cnpj": os.getenv("COMPANY_CNPJ", ""),
        "current_year": datetime.now().year,
    }


def _form_options() -> dict[str, list[str]]:
    return {
        "teams": _env_list("LANDING_TEAM_OPTIONS", DEFAULT_TEAM_OPTIONS),
        "plans": _env_list("LANDING_PLAN_OPTIONS", DEFAULT_PLAN_OPTIONS),
    }


def _render_index(values: dict, errors: dict, status: int = 200):
    return render_template(
        "index.html",
        values=values,
        errors=errors,
        submission_id=values.get("submission_id") or secrets.token_urlsafe(12),
        **_form_options(),
    ), status


@app.get("/")
def index():
    return _render_index({}, {})


@app.get("/features")
@app.get("/recursos")
def features():
    # features.html é um trecho da página inicial, sem layout próprio.
    return redirect(url_for("index") + "#recursos")


@app.errorhandler(CSRFError)
def csrf_error(_error):
    # Sessão expirada ou formulário antigo: mostra o formulário com os dados digitados.
    values = request.form.to_dict(flat=True) if request.method == "POST" else {}
    return _render_index(values, {"form": "Sua sessão expirou. Confira os dados e envie novamente."}, 400)


@app.get("/privacy")
@app.get("/privacidade")
def privacy():
    return render_template("privacy.html")


@app.get("/thanks")
@app.get("/obrigado")
def thanks():
    return render_template("thanks.html")


@app.route("/demonstration", methods=["GET", "POST"])
@app.route("/demonstracao", methods=["GET", "POST"])
def demonstration():
    if request.method == "GET":
        return redirect(url_for("index"))

    # Honeypot: bots costumam preencher campos escondidos.
    honeypot = _first_form_value(
        "website",
        "company_website",
        "site_confirm",
        "fax",
    )
    if honeypot:
        return redirect(url_for("thanks"))

    values = request.form.to_dict(flat=True)

    # Aceita nomes de campos em PT ou EN; o formulário atual usa workshop/city/challenge.
    name = _first_form_value("name", "nome", "full_name", "nome_completo")
    email = _first_form_value("email", "email_address")
    phone = _first_form_value("phone", "telefone", "whatsapp", "celular")
    company = _first_form_value("workshop", "company", "empresa", "business", "razao_social")
    city = _first_form_value("city", "cidade")
    message = _first_form_value("challenge", "message", "mensagem", "notes", "observacoes")
    plan = _first_form_value("plan", "plano")
    team = _first_form_value("team", "team_size", "equipe", "tamanho_equipe")
    options = _form_options()

    errors: dict[str, str] = {}
    if not name:
        errors["name"] = "Informe seu nome."
    if not company:
        errors["workshop"] = "Informe o nome da oficina."
    if len(re.sub(r"\D", "", phone)) < 10:
        errors["phone"] = "Informe um WhatsApp com DDD."
    if email and ("@" not in email or "." not in email.rsplit("@", 1)[-1]):
        errors["email"] = "Informe um e-mail válido."
    if not city:
        errors["city"] = "Informe a cidade."
    if team not in options["teams"]:
        errors["team"] = "Selecione o tamanho da equipe."
    if plan not in options["plans"]:
        errors["plan"] = "Selecione um plano."
    if request.form.get("privacy") != "accepted":
        errors["privacy"] = "É preciso autorizar o contato para enviarmos a demonstração."

    if errors:
        return _render_index(values, errors, 400)

    LEADS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lead = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "name": name[:160],
        "email": email[:254],
        "phone": phone[:40],
        "company": company[:160],
        "city": city[:100],
        "message": message[:2000],
        "plan": plan[:80],
        "team": team[:80],
        "privacy_accepted": True,
        "ip": (request.remote_addr or "")[:64],
        "user_agent": request.headers.get("User-Agent", "")[:512],
        "form": {
            key: values[key][:255]
            for key in ("submission_id", "utm_source", "utm_medium", "utm_campaign")
            if key in values
        },
    }

    with LEADS_FILE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(lead, ensure_ascii=False) + "\n")

    return redirect(url_for("thanks"))


@app.get("/favicon.ico")
def favicon():
    svg = BASE_DIR / "static" / "favicon.svg"
    if svg.exists():
        return send_from_directory(
            str(BASE_DIR / "static"),
            "favicon.svg",
            mimetype="image/svg+xml",
        )
    abort(404)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "lshub-landing",
        "host": request.host,
    }


@app.errorhandler(404)
def not_found(_error):
    # Se o template de erro não existir, retorna texto simples sem gerar
    # uma nova exceção.
    error_template = BASE_DIR / "templates" / "error.html"
    if error_template.exists():
        return render_template(
            "error.html",
            code=404,
            message="Página não encontrada.",
        ), 404
    return "Página não encontrada.", 404


@app.errorhandler(500)
def server_error(_error):
    error_template = BASE_DIR / "templates" / "error.html"
    if error_template.exists():
        return render_template(
            "error.html",
            code=500,
            message="Ocorreu um erro interno.",
        ), 500
    return "Ocorreu um erro interno.", 500


if __name__ == "__main__":
    # Apenas para teste local. Em produção o Passenger usa passenger_wsgi.py.
    debug = os.getenv("LANDING_DEBUG", "false").lower() == "true" and landing_env == "development"
    app.run(host="127.0.0.1", port=5000, debug=debug)
