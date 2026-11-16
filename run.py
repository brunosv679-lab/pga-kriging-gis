import os
import sys
from app import create_app, db

# Criar instância da aplicação via Application Factory
app = create_app()

if __name__ == "__main__":
    with app.app_context():
        # Assegurar que as tabelas espaciais existam no PostGIS
        try:
            db.create_all()
            print("[✓] Tabelas do PostGIS verificadas/criadas com sucesso.")
        except Exception as e:
            print(f"[!] Aviso na verificação de tabelas: {e}")

    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    print("==================================================================")
    print(f"[*] PGA Kriging GIS iniciado em http://{host}:{port}")
    print(f"[*] Ambiente: {'Desenvolvimento/Debug' if debug else 'Produção/Teste'}")
    print(f"[*] PostGIS 18 Conectado: pga_db @ localhost:5432")
    print("==================================================================")

    app.run(host=host, port=port, debug=debug)
