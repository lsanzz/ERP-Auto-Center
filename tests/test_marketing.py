"""Public lead capture is independent of the ERP and its customer database."""
import csv
from pathlib import Path
import sqlite3
import tempfile
import unittest
from html.parser import HTMLParser

from marketing import create_app


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])


class MarketingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "leads.db"
        self.app = create_app({"TESTING": True, "SECRET_KEY": "marketing-tests-only", "LEADS_DATABASE": str(self.database)})
        self.client = self.app.test_client()

    def payload(self):
        self.client.get("/?utm_source=teste&utm_medium=local&utm_campaign=demonstracao")
        with self.client.session_transaction() as session:
            tokens = {"csrf": session["csrf"], "submission_id": session["submission_id"]}
        return dict(tokens, name="Pessoa de teste", workshop="Oficina fictícia", phone="(19) 99999-9999", email="teste@example.com",
                    city="Campinas / SP", team="2 a 5 pessoas", plan="Profissional", challenge="Organizar o pátio", privacy="accepted")

    def rows(self):
        connection = sqlite3.connect(self.database)
        try:
            connection.row_factory = sqlite3.Row
            return connection.execute("SELECT * FROM leads").fetchall()
        finally:
            connection.close()

    def test_public_site_links_assets_and_erp_separation(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for price in ("89,90", "179,90", "299,90"):
            self.assertIn(price, html)
        self.assertIn("até 2 usuários", html)
        self.assertIn("até 5 usuários", html)
        self.assertIn("até 10 usuários", html)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        parser = Links()
        parser.feed(html)
        self.assertIn("https://app.lshub.com.br", parser.links)
        self.assertTrue(any("wa.me/5519992744148" in url for url in parser.links))
        for link in parser.links:
            if link.startswith("#") or link.startswith("/#"):
                self.assertIn(link.split("#")[1], parser.ids)
            elif link.startswith("/"):
                self.assertEqual(self.client.get(link).status_code, 200, link)
        for asset in ("site.css", "site.js", "favicon.svg"):
            with self.client.get("/assets/" + asset) as result:
                self.assertEqual(result.status_code, 200)
        for private in ("/sistema/admin", "/api/clients", "/instance/website/leads.db", "/leads", "/assets/../marketing.py"):
            self.assertEqual(self.client.get(private).status_code, 404)
        self.assertEqual(self.client.get("/robots.txt").status_code, 200)
        self.assertEqual(self.client.get("/sitemap.xml").status_code, 200)

    def test_capture_persisted_once_with_campaign_and_confirmation(self):
        payload = self.payload()
        result = self.client.post("/demonstracao", data=payload)
        self.assertEqual(result.status_code, 303)
        self.assertEqual(result.location, "/obrigado")
        self.assertEqual(self.client.post("/demonstracao", data=payload).status_code, 303)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["phone"], "19999999999")
        self.assertEqual(rows[0]["source"], "teste")
        self.assertEqual(rows[0]["privacy_version"], "2026-09-07")
        self.assertEqual(self.client.get("/obrigado").status_code, 200)
        next_payload = self.payload()
        self.assertNotEqual(payload["submission_id"], next_payload["submission_id"])

    def test_validation_and_escaping_preserve_fields_without_saving(self):
        payload = self.payload()
        payload.update(name='<script>alert("x")</script>', phone="123", email="bad", privacy="", plan="Unknown")
        result = self.client.post("/demonstracao", data=payload)
        self.assertEqual(result.status_code, 422)
        html = result.get_data(as_text=True)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('<script>alert("x")</script>', html)
        self.assertIn('id="error-phone"', html)
        self.assertIn('id="error-privacy"', html)
        self.assertEqual(len(self.rows()), 0)

    def test_csrf_unicode_and_honeypot_rejected(self):
        payload = self.payload()
        payload["csrf"] = "inválido"
        self.assertEqual(self.client.post("/demonstracao", data=payload).status_code, 400)
        payload = self.payload()
        payload["website"] = "spam"
        self.assertEqual(self.client.post("/demonstracao", data=payload).status_code, 400)
        payload = self.payload()
        payload["submission_id"] = "inválido"
        self.assertEqual(self.client.post("/demonstracao", data=payload).status_code, 422)
        self.assertEqual(len(self.rows()), 0)

    def test_rate_limit_persists_between_app_instances(self):
        payload = self.payload()
        payload["phone"] = "invalid"
        for _ in range(10):
            self.assertEqual(self.client.post("/demonstracao", data=payload).status_code, 422)
        other_app = create_app({"TESTING": True, "SECRET_KEY": "marketing-tests-only", "LEADS_DATABASE": str(self.database)})
        other_client = other_app.test_client()
        other_client.get("/")
        with other_client.session_transaction() as session:
            payload.update(csrf=session["csrf"], submission_id=session["submission_id"])
        result = other_client.post("/demonstracao", data=payload)
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result.headers["Retry-After"], "3600")

    def test_export_is_local_and_protects_spreadsheet_formulas(self):
        payload = self.payload()
        payload["name"] = "=1+1"
        self.client.post("/demonstracao", data=payload)
        output = Path(self.temp.name) / "leads.csv"
        result = self.app.test_cli_runner().invoke(args=["export-leads", str(output)])
        self.assertEqual(result.exit_code, 0, result.output)
        with output.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["name"], "'=1+1")
        result = self.app.test_cli_runner().invoke(args=["export-leads", str(output)])
        self.assertNotEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
