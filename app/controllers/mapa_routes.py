import csv
import io
import os
from flask import Blueprint, render_template, request, jsonify, current_app, Response
from flask_wtf.csrf import generate_csrf
from app import db, csrf
from app.models.estacao_pga import EstacaoPGA
from app.services.kriging_engine import (
    KrigingEngine,
    KrigingValidationError,
    KrigingSingularMatrixError,
    KrigingError
)
from app.services.data_importer import (
    DataImporterService,
    DataImportError,
    DataValidationError,
    validate_physical_records
)

mapa_bp = Blueprint("mapa", __name__)

@mapa_bp.route("/")
def index():
    """Renderiza a interface do Dashboard GIS."""
    return render_template("index.html")

@mapa_bp.route("/api/csrf-token", methods=["GET"])
def get_csrf():
    """Fornece um token CSRF válido para clientes REST ou scripts."""
    return jsonify({
        "status": "success",
        "csrf_token": generate_csrf()
    })

@mapa_bp.route("/api/estacoes", methods=["GET"])
def listar_estacoes():
    """Retorna todas as estações cadastradas em formato GeoJSON FeatureCollection."""
    estacoes = EstacaoPGA.query.order_by(EstacaoPGA.codigo_estacao).all()
    features = [e.to_geojson_feature() for e in estacoes]
    return jsonify({
        "type": "FeatureCollection",
        "total": len(features),
        "features": features
    })

@mapa_bp.route("/api/estacoes", methods=["POST"])
@csrf.exempt
def criar_estacoes():
    """
    Endpoint para cadastro de estação individual (via JSON)
    ou importação em lote via arquivo CSV seguro.
    """
    if "file" in request.files:
        return upload_estacoes()

    data = request.get_json(silent=True)
    if not data:
        data = request.form

    if not data:
        return jsonify({"status": "error", "message": "Corpo da requisição vazio ou formato inválido."}), 400

    raw_code = data.get("codigo_estacao") or data.get("codigo")
    raw_lat = data.get("latitude") or data.get("lat")
    raw_lon = data.get("longitude") or data.get("lon") or data.get("lng")
    raw_pga = data.get("pga_g") or data.get("pga")
    raw_mun = data.get("municipio_uf") or data.get("municipio")
    raw_prof = data.get("profundidade_km") or data.get("profundidade") or 10.0
    raw_reg = data.get("regiao") or data.get("region")

    if not raw_code or raw_lat is None or raw_lon is None or raw_pga is None:
        return jsonify({
            "status": "error",
            "message": "Campos obrigatórios ausentes: codigo_estacao, latitude, longitude, pga_g."
        }), 400

    try:
        rec = validate_physical_records(raw_code, raw_lat, raw_lon, raw_pga, raw_mun, raw_prof, raw_reg)
    except DataValidationError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400

    try:
        DataImporterService.import_from_csv_text(
            f"codigo_estacao,municipio_uf,regiao,latitude,longitude,profundidade_km,pga_g\n"
            f"{rec['codigo']},{rec['municipio'] or ''},{rec['regiao'] or ''},{rec['lat']},{rec['lon']},{rec['prof']},{rec['pga']}\n"
        )
        return jsonify({
            "status": "success",
            "message": "Estação cadastrada/atualizada com sucesso.",
            "estacao": {
                "codigo_estacao": rec["codigo"],
                "municipio_uf": rec["municipio"],
                "regiao": rec["regiao"],
                "latitude": rec["lat"],
                "longitude": rec["lon"],
                "profundidade_km": rec["prof"],
                "pga_g": rec["pga"]
            }
        }), 201

    except Exception as ex:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Erro de banco de dados: {str(ex)}"}), 500

@mapa_bp.route("/api/estacoes/upload", methods=["POST"])
@csrf.exempt
def upload_estacoes():
    """
    Ingestão segura de arquivos .csv ou .geojson enviados pelo usuário.
    Valida limites físicos, sanitiza textos e executa upsert transacional via PostGIS.
    """
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "Nenhum arquivo enviado no campo 'file'."}), 400

    uploaded_file = request.files["file"]
    if not uploaded_file or uploaded_file.filename == "":
        return jsonify({"status": "error", "message": "Nenhum arquivo selecionado."}), 400

    filename = uploaded_file.filename.lower()
    if not (filename.endswith(".csv") or filename.endswith(".geojson") or filename.endswith(".json")):
        return jsonify({
            "status": "error",
            "message": "Formato de arquivo inválido. Apenas extensões .csv e .geojson são suportadas."
        }), 400

    try:
        content = uploaded_file.read().decode("utf-8-sig", errors="replace")
        if not content.strip():
            return jsonify({"status": "error", "message": "O arquivo enviado está vazio."}), 400

        if filename.endswith(".csv"):
            result = DataImporterService.import_from_csv_text(content)
        else:
            result = DataImporterService.import_from_geojson_text(content)

        total_atual = EstacaoPGA.query.count()

        return jsonify({
            "status": "success",
            "message": f"Arquivo processado com sucesso. {result['processados']} estações inseridas/atualizadas.",
            "total_banco": total_atual,
            "detalhes": result
        }), 201

    except (DataValidationError, DataImportError) as de:
        return jsonify({"status": "error", "message": str(de)}), 400
    except Exception as ex:
        return jsonify({"status": "error", "message": f"Erro no processamento do arquivo: {str(ex)}"}), 500

@mapa_bp.route("/api/estacoes/seed-norte", methods=["POST"])
@csrf.exempt
def seed_norte():
    """
    Carrega automaticamente o dataset sísmico das 20 estações da Região Norte
    do Brasil a partir de data/estacoes_pga_norte_brasil.csv no PostGIS.
    """
    base_dir = os.path.abspath(os.path.join(current_app.root_path, ".."))
    csv_path = os.path.join(base_dir, "data", "estacoes_pga_norte_brasil.csv")

    if not os.path.exists(csv_path):
        csv_path = "data/estacoes_pga_norte_brasil.csv"

    if not os.path.exists(csv_path):
        return jsonify({
            "status": "error",
            "message": f"Arquivo de dados não encontrado no caminho: {csv_path}"
        }), 404

    try:
        result = DataImporterService.import_local_file(csv_path)
        total_atual = EstacaoPGA.query.count()
        return jsonify({
            "status": "success",
            "message": "Dataset da Região Norte (20 Estações) importado com sucesso!",
            "processados": result["processados"],
            "total_banco": total_atual,
            "detalhes": result
        }), 200
    except Exception as ex:
        return jsonify({"status": "error", "message": f"Falha ao importar dataset Norte: {str(ex)}"}), 500

@mapa_bp.route("/api/estacoes/seed-brasil", methods=["POST"])
@csrf.exempt
def seed_brasil():
    """
    Carrega automaticamente o dataset sísmico das 35 estações de todo o Brasil
    (NBR 15421) a partir de data/estacoes_pga_brasil_completo.csv no PostGIS.
    """
    base_dir = os.path.abspath(os.path.join(current_app.root_path, ".."))
    csv_path = os.path.join(base_dir, "data", "estacoes_pga_brasil_completo.csv")

    if not os.path.exists(csv_path):
        csv_path = "data/estacoes_pga_brasil_completo.csv"

    if not os.path.exists(csv_path):
        return jsonify({
            "status": "error",
            "message": f"Arquivo de dados nacional não encontrado: {csv_path}"
        }), 404

    try:
        result = DataImporterService.import_local_file(csv_path)
        total_atual = EstacaoPGA.query.count()
        return jsonify({
            "status": "success",
            "message": "Dataset Nacional Brasil Completo (35 Estações - NBR 15421) importado com sucesso!",
            "processados": result["processados"],
            "total_banco": total_atual,
            "detalhes": result
        }), 200
    except Exception as ex:
        return jsonify({"status": "error", "message": f"Falha ao importar dataset Brasil Completo: {str(ex)}"}), 500

@mapa_bp.route("/api/estacoes/exportar-csv", methods=["GET"])
def exportar_csv():
    """Gera e retorna um arquivo CSV com todas as estações cadastradas no PostGIS."""
    estacoes = EstacaoPGA.query.order_by(EstacaoPGA.codigo_estacao).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=",")
    writer.writerow(["codigo_estacao", "municipio_uf", "regiao", "latitude", "longitude", "profundidade_km", "pga_g"])

    for e in estacoes:
        writer.writerow([
            e.codigo_estacao,
            e.municipio_uf or "",
            e.regiao or "",
            f"{e.latitude:.6f}",
            f"{e.longitude:.6f}",
            f"{e.profundidade_km if e.profundidade_km is not None else 10.0:.1f}",
            f"{e.pga_g:.5f}"
        ])

    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=estacoes_pga_brasil_export.csv"}
    )

@mapa_bp.route("/api/interpolar", methods=["POST"])
@csrf.exempt
def interpolar():
    """
    Executa o cálculo de Krigagem Ordinária sobre as estações cadastradas.
    Aceita parâmetros JSON:
    - modelo: 'spherical', 'exponential', 'gaussian', 'linear' (padrão: 'spherical')
    - resolucao: inteiro entre 10 e 120 (padrão: 80)
    """
    data = request.get_json(silent=True) or {}
    modelo = data.get("modelo", "spherical")
    resolucao = data.get("resolucao", 80)

    try:
        geojson_result = KrigingEngine.execute_interpolation(modelo=modelo, resolucao=resolucao)
        return jsonify(geojson_result), 200
    except (KrigingValidationError, KrigingSingularMatrixError) as k_err:
        return jsonify({
            "status": "error",
            "tipo_erro": k_err.__class__.__name__,
            "message": str(k_err)
        }), 400
    except KrigingError as k_err:
        return jsonify({
            "status": "error",
            "message": str(k_err)
        }), 400
    except Exception as ex:
        return jsonify({
            "status": "error",
            "message": "Ocorreu um erro interno inesperado durante a interpolação geoestatística."
        }), 500

@mapa_bp.route("/api/estacoes/<int:station_id>", methods=["DELETE"])
@csrf.exempt
def remover_estacao(station_id):
    """Remove uma estação sismográfica pelo ID através de consulta parametrizada segura."""
    estacao = db.session.get(EstacaoPGA, station_id)
    if not estacao:
        return jsonify({"status": "error", "message": f"Estação com ID {station_id} não encontrada."}), 404

    try:
        code = estacao.codigo_estacao
        db.session.delete(estacao)
        db.session.commit()
        return jsonify({
            "status": "success",
            "message": f"Estação '{code}' (ID {station_id}) removida com sucesso."
        }), 200
    except Exception as ex:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Erro ao remover estação: {str(ex)}"}), 500

@mapa_bp.route("/api/sample-csv", methods=["GET"])
def baixar_csv_exemplo():
    """Gera e retorna um CSV de exemplo com dados sísmicos nacionais."""
    base_dir = os.path.abspath(os.path.join(current_app.root_path, ".."))
    csv_path = os.path.join(base_dir, "data", "estacoes_pga_brasil_completo.csv")
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            csv_content = f.read()
    else:
        csv_content = (
            "codigo_estacao,municipio_uf,regiao,latitude,longitude,profundidade_km,pga_g\n"
            "EST_AC_CZS,Cruzeiro do Sul/AC,Norte,-7.630600,-72.670000,32.0,0.16500\n"
            "EST_PA_CRJ,Parauapebas/PA,Norte,-5.923000,-49.982000,10.5,0.08500\n"
            "EST_RN_JCM,João Câmara/RN,Nordeste,-5.538900,-35.819400,5.0,0.15500\n"
            "EST_MT_PGH,Porto dos Gaúchos/MT,Centro-Oeste,-11.533300,-57.416700,11.0,0.14000\n"
            "EST_MG_MCL,Montes Claros/MG,Sudeste,-16.728200,-43.861700,4.5,0.12500\n"
        )
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=estacoes_pga_brasil_modelo.csv"}
    )

@mapa_bp.route("/api/seed", methods=["POST"])
@csrf.exempt
def popular_amostra():
    """Alias para seed-brasil garantindo retrocompatibilidade."""
    return seed_brasil()
