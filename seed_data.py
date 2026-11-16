import os
import sys
from app import create_app, db
from app.services.data_importer import DataImporterService

def seed():
    app = create_app()
    with app.app_context():
        db.create_all()

        csv_path = os.path.join(os.path.dirname(__file__), "data", "estacoes_pga_norte_brasil.csv")
        print(f"=== Populando Dataset Sísmico da Região Norte: {csv_path} ===")
        
        if not os.path.exists(csv_path):
            print(f"[!] Arquivo não encontrado: {csv_path}")
            sys.exit(1)

        result = DataImporterService.import_local_file(csv_path)
        print("---------------------------------------------------------")
        print(f"Sucesso! {result['processados']} estações processadas.")
        if result['rejeitados'] > 0:
            print(f"Aviso: {result['rejeitados']} rejeitadas. Erros: {result['erros']}")

if __name__ == "__main__":
    seed()
