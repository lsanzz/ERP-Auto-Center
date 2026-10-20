from __future__ import annotations

import json
import os
import re
import secrets
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
from flask_wtf.csrf import generate_csrf
from werkzeug.middleware.proxy_fix import ProxyFix


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

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
landing_secret = os.getenv("LANDING_SECRET_KEY") or os.getenv("SECRET_KEY")
if landing_env == "production" and (not landing_secret or len(landing_secret) < 32):
    raise RuntimeError("Configure LANDING_SECRET_KEY com pelo menos 32 caracteres antes de publicar.")

app.config.update(
    SECRET_KEY=landing_secret or secrets.token_hex(32),
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


@app.get("/")
def index():
    # values/errors são enviados para compatibilidade com formulários
    # que preservam dados/erros após validação.
    return render_template(
        "index.html",
        values={},
        errors={},
        submission_id=secrets.token_urlsafe(12),
        teams=_env_list("LANDING_TEAM_OPTIONS"),
        plans=_env_list("LANDING_PLAN_OPTIONS"),
    )


@app.get("/recursos")
@app.get("/features")
def features():
    return render_template("features.html")


@app.get("/privacidade")
@app.get("/privacy")
def privacy():
    return render_template("privacy.html")


@app.get("/obrigado")
@app.get("/thanks")
def thanks():
    return render_template("thanks.html")


@app.route("/demonstracao", methods=["GET", "POST"])
@app.route("/demonstration", methods=["GET", "POST"])
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

    # Aceita nomes de campos em PT ou EN sem obrigar o template a mudar.
    name = _first_form_value("name", "nome", "full_name", "nome_completo")
    email = _first_form_value("email", "email_address")
    phone = _first_form_value("phone", "telefone", "whatsapp", "celular")
    company = _first_form_value("company", "empresa", "business", "razao_social")
    message = _first_form_value("message", "mensagem", "notes", "observacoes")
    plan = _first_form_value("plan", "plano")
    team = _first_form_value("team", "team_size", "equipe", "tamanho_equipe")

    # Mantemos a validação deliberadamente simples para não quebrar
    # formulários já existentes na landing.
    errors: dict[str, str] = {}

    if email and ("@" not in email or "." not in email.rsplit("@", 1)[-1]):
        errors["email"] = "Informe um e-mail válido."

    if errors:
        return (
            render_template(
                "index.html",
                values=values,
                errors=errors,
                submission_id=values.get("submission_id", ""),
                teams=_env_list("LANDING_TEAM_OPTIONS"),
                plans=_env_list("LANDING_PLAN_OPTIONS"),
            ),
            400,
        )

    # Guarda o lead localmente para a solicitação não se perder.
    # Arquivo fica fora da pasta static e não é servido pelo navegador.
    data_dir = BASE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    leads_file = data_dir / "leads.jsonl"

    lead = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "name": name[:160],
        "email": email[:254],
        "phone": phone[:40],
        "company": company[:160],
        "message": message[:2000],
        "plan": plan[:80],
        "team": team[:80],
        "ip": (request.remote_addr or "")[:64],
        "user_agent": request.headers.get("User-Agent", "")[:512],
        "form": {
            key: values[key][:255]
            for key in ("submission_id", "utm_source", "utm_medium", "utm_campaign")
            if key in values
        },
    }

    with leads_file.open("a", encoding="utf-8") as fp:
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
