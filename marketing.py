"""Public LS Hub website. Run separately from the operational ERP."""
from __future__ import annotations

import csv
from contextlib import contextmanager
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlencode

import click
from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template, request, session, url_for

load_dotenv()
ROOT = Path(__file__).resolve().parent
PLANS = ("Essencial", "Profissional", "Gestão", "Quero orientação")
TEAMS = ("Só eu", "2 a 5 pessoas", "6 a 10 pessoas", "Mais de 10 pessoas")


def create_app(test_config=None):
    app = Flask(__name__, template_folder="website/templates", static_folder="website/static",
                static_url_path="/assets", instance_path=str(ROOT / "instance" / "website"))
    production = os.getenv("MARKETING_ENV", "development") == "production"
    app.config.update(
        SECRET_KEY=os.getenv("MARKETING_SECRET_KEY"),
        LEADS_DATABASE=os.getenv("MARKETING_LEADS_DATABASE", str(Path(app.instance_path) / "leads.db")),
        SALES_WHATSAPP=re.sub(r"\D", "", os.getenv("MARKETING_WHATSAPP", "5519992744148")),
        SALES_EMAIL=os.getenv("MARKETING_EMAIL", "lucastango40@gmail.com"),
        COMPANY_LEGAL_NAME=os.getenv("MARKETING_LEGAL_NAME", ""),
        COMPANY_CNPJ=os.getenv("MARKETING_CNPJ", ""),
        SESSION_COOKIE_NAME="lshub_marketing", SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=production,
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    app.config.update(test_config or {})
    if not app.config["SECRET_KEY"]:
        if production:
            raise RuntimeError("Configure MARKETING_SECRET_KEY antes de publicar.")
        app.config["SECRET_KEY"] = secrets.token_hex(32)
    database = Path(app.config["LEADS_DATABASE"])
    database.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect():
        connection = sqlite3.connect(database, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    with connect() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                name TEXT NOT NULL, workshop TEXT NOT NULL, phone TEXT NOT NULL,
                email TEXT NOT NULL, city TEXT NOT NULL, team TEXT NOT NULL,
                plan TEXT NOT NULL, challenge TEXT NOT NULL, source TEXT NOT NULL,
                medium TEXT NOT NULL, campaign TEXT NOT NULL,
                privacy_version TEXT NOT NULL, submission_id TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS rate_limits (
                client_hash TEXT PRIMARY KEY, started_at INTEGER NOT NULL, attempts INTEGER NOT NULL
            );
        """)

    def tokens():
        session.setdefault("csrf", secrets.token_urlsafe(32))
        session.setdefault("submission_id", secrets.token_urlsafe(24))

    def home_response(errors=None, values=None, status=200):
        tokens()
        return render_template("index.html", errors=errors or {}, values=values or {}, plans=PLANS,
                               teams=TEAMS, csrf=session["csrf"], submission_id=session["submission_id"]), status

    @app.context_processor
    def public_settings():
        whatsapp = app.config["SALES_WHATSAPP"]
        return dict(sales_email=app.config["SALES_EMAIL"],
                    whatsapp_url=("https://wa.me/" + whatsapp + "?" + urlencode({"text": "Olá! Quero conhecer o LS Hub para minha oficina."})) if whatsapp else "",
                    company_legal_name=app.config["COMPANY_LEGAL_NAME"], company_cnpj=app.config["COMPANY_CNPJ"])

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/")
    def index():
        if session.pop("lead_received", False):
            session.pop("submission_id", None)
        for key in ("utm_source", "utm_medium", "utm_campaign"):
            if key in request.args:
                session[key] = request.args[key][:160]
        return home_response()

    @app.post("/demonstracao")
    def demonstration():
        expected = session.get("csrf", "")
        if not expected or not hmac.compare_digest(expected.encode(), request.form.get("csrf", "").encode()):
            return home_response({"form": "Sua sessão expirou. Confira os dados e envie novamente."}, request.form, 400)
        if request.form.get("website"):
            abort(400)
        client = hmac.new(str(app.config["SECRET_KEY"]).encode(), (request.remote_addr or "unknown").encode(), hashlib.sha256).hexdigest()
        now = int(time.time())
        with connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM rate_limits WHERE started_at < ?", (now - 3600,))
            connection.execute("INSERT INTO rate_limits VALUES (?, ?, 1) ON CONFLICT(client_hash) DO UPDATE SET attempts=attempts+1", (client, now))
            attempts = connection.execute("SELECT attempts FROM rate_limits WHERE client_hash=?", (client,)).fetchone()[0]
        if attempts > 10:
            response, status = home_response({"form": "Muitas tentativas. Aguarde uma hora antes de tentar novamente."}, request.form, 429)
            return response, status, {"Retry-After": "3600"}
        limits = {"name": 100, "workshop": 160, "phone": 24, "email": 160, "city": 100, "team": 40, "plan": 40, "challenge": 1000}
        values = {key: request.form.get(key, "").strip() for key in limits}
        errors = {}
        for key, maximum in limits.items():
            if len(values[key]) > maximum:
                errors[key] = f"Use até {maximum} caracteres."
        for key in ("name", "workshop", "phone", "city", "team", "plan"):
            if not values[key]:
                errors[key] = "Preencha este campo."
        phone = re.sub(r"\D", "", values["phone"])
        if len(phone) in (12, 13) and phone.startswith("55"):
            phone = phone[2:]
        if len(phone) not in (10, 11):
            errors["phone"] = "Informe um telefone com DDD."
        if values["email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", values["email"]):
            errors["email"] = "Confira o endereço de e-mail."
        if values["plan"] not in PLANS:
            errors["plan"] = "Selecione um plano."
        if values["team"] not in TEAMS:
            errors["team"] = "Selecione o tamanho da equipe."
        if request.form.get("privacy") != "accepted":
            errors["privacy"] = "Confirme a autorização para contato."
        submission_id = request.form.get("submission_id", "")
        if not submission_id or not hmac.compare_digest(session.get("submission_id", "").encode(), submission_id.encode()):
            errors["form"] = "Atualize a página antes de enviar novamente."
        if errors:
            return home_response(errors, values, 422)
        try:
            with connect() as connection:
                connection.execute("""INSERT OR IGNORE INTO leads
                    (name, workshop, phone, email, city, team, plan, challenge, source, medium, campaign, privacy_version, submission_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (values["name"], values["workshop"], phone, values["email"], values["city"], values["team"], values["plan"],
                     values["challenge"], session.get("utm_source", ""), session.get("utm_medium", ""), session.get("utm_campaign", ""), "2026-09-07", submission_id))
        except sqlite3.Error:
            app.logger.error("Não foi possível registrar a solicitação comercial.")
            return home_response({"form": "Não foi possível salvar agora. Tente novamente em alguns instantes."}, values, 503)
        session["lead_received"] = True
        return redirect(url_for("thanks"), code=303)

    @app.errorhandler(sqlite3.Error)
    def unavailable_storage(error):
        app.logger.error("Armazenamento comercial temporariamente indisponível.")
        return home_response({"form": "Não foi possível salvar agora. Tente novamente em alguns instantes."}, request.form, 503)

    @app.get("/obrigado")
    def thanks():
        if not session.get("lead_received"):
            return redirect(url_for("index", _anchor="contato"))
        return render_template("thanks.html")

    @app.get("/privacidade")
    def privacy():
        return render_template("privacy.html")

    @app.get("/robots.txt")
    def robots():
        return "User-agent: *\nAllow: /\nDisallow: /obrigado\nSitemap: https://lshub.com.br/sitemap.xml\n", 200, {"Content-Type": "text/plain"}

    @app.get("/sitemap.xml")
    def sitemap():
        return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://lshub.com.br/</loc></url><url><loc>https://lshub.com.br/privacidade</loc></url></urlset>', 200, {"Content-Type": "application/xml"}

    @app.cli.command("export-leads")
    @click.argument("output", type=click.Path(path_type=Path))
    def export_leads(output):
        """Export leads locally; no public endpoint exposes customer contacts."""
        if output.exists():
            raise click.ClickException("O arquivo já existe. Escolha outro destino.")
        with connect() as connection:
            rows = connection.execute("SELECT id, created_at, name, workshop, phone, email, city, team, plan, challenge, source, medium, campaign FROM leads ORDER BY id").fetchall()
        if not rows:
            click.echo("Nenhuma solicitação registrada.")
            return
        def safe_cell(value):
            text = str(value)
            return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text
        with output.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(rows[0].keys())
            writer.writerows([safe_cell(value) for value in row] for row in rows)
        click.echo(f"{len(rows)} solicitações exportadas.")

    return app
