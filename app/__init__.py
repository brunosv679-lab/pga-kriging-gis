import os
import secrets
from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect, generate_csrf
from dotenv import load_dotenv

# Carregar variáveis de ambiente do .env
load_dotenv()

db = SQLAlchemy()
csrf = CSRFProtect()

def create_app(test_config=None):
    """
    Application Factory para o Sistema de Interpolação de PGA.
    Configura segurança, banco de dados, CSRF e headers HTTP defensivos.
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Configuração Padrão
    secret_key = os.getenv("SECRET_KEY")
    if not secret_key:
        secret_key = secrets.token_hex(32)

    database_url = os.getenv("DATABASE_URL", "postgresql+psycopg://pga_app:PgaSecure2026%21%40%23@localhost:5432/pga_db")

    app.config.from_mapping(
        SECRET_KEY=secret_key,
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,  # Limite rígido de upload: 2MB
        WTF_CSRF_ENABLED=True,
        WTF_CSRF_TIME_LIMIT=3600,
        WTF_CSRF_CHECK_DEFAULT=True
    )

    if test_config:
        app.config.update(test_config)

    # Inicialização de extensões
    db.init_app(app)
    csrf.init_app(app)

    # Injetar token CSRF nos templates automaticamente
    @app.context_processor
    def inject_csrf_token():
        return dict(csrf_token=generate_csrf)

    # Hardening HTTP: Headers de Segurança em todas as respostas
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Content Security Policy flexível o suficiente para CDN Tailwind e Leaflet
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob: https://*.tile.openstreetmap.org https://server.arcgisonline.com; "
            "connect-src 'self';"
        )
        response.headers["Content-Security-Policy"] = csp
        return response

    # Tratamento de erro 413: Tamanho de arquivo excedido
    @app.errorhandler(413)
    def file_too_large(error):
        return jsonify({
            "status": "error",
            "message": "O arquivo enviado excede o limite máximo permitido de 2 MB."
        }), 413

    # Registro de Blueprints
    from app.controllers.mapa_routes import mapa_bp
    app.register_blueprint(mapa_bp)

    return app
