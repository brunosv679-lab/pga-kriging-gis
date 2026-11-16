import io
import json
import os
import math
import numpy as np
import pytest
from app import create_app, db
from app.models.estacao_pga import EstacaoPGA
from app.services.kriging_engine import (
    KrigingEngine,
    KrigingValidationError,
    KrigingSingularMatrixError
)
from app.services.data_importer import DataImporterService

@pytest.fixture
def app():
    """Cria uma instância da aplicação configurada para testes."""
    test_config = {
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False
    }
    app = create_app(test_config=test_config)

    with app.app_context():
        db.create_all()
        # Limpar tabela antes dos testes
        EstacaoPGA.query.delete()
        db.session.commit()
        yield app
        # Teardown
        db.session.rollback()
        EstacaoPGA.query.delete()
        db.session.commit()

@pytest.fixture
def client(app):
    """Cliente de testes HTTP do Flask."""
    return app.test_client()

@pytest.fixture
def sample_stations(app):
    """Insere 12 estações sísmicas representativas."""
    stations = [
        EstacaoPGA(codigo_estacao="EST_T01", latitude=-6.0450, longitude=-50.1550, pga_g=0.145, municipio_uf="Parauapebas/PA", profundidade_km=10.0),
        EstacaoPGA(codigo_estacao="EST_T02", latitude=-6.1120, longitude=-50.2800, pga_g=0.210, municipio_uf="Canaã dos Carajás/PA", profundidade_km=12.0),
        EstacaoPGA(codigo_estacao="EST_T03", latitude=-5.9230, longitude=-49.9820, pga_g=0.082, municipio_uf="Curionópolis/PA", profundidade_km=8.5),
        EstacaoPGA(codigo_estacao="EST_T04", latitude=-6.2340, longitude=-50.0890, pga_g=0.178, municipio_uf="Eldorado/PA", profundidade_km=11.0),
        EstacaoPGA(codigo_estacao="EST_T05", latitude=-6.0120, longitude=-50.4100, pga_g=0.065, municipio_uf="Marabá/PA", profundidade_km=14.0),
        EstacaoPGA(codigo_estacao="EST_T06", latitude=-5.8300, longitude=-50.1200, pga_g=0.045, municipio_uf="Itupiranga/PA", profundidade_km=13.0),
        EstacaoPGA(codigo_estacao="EST_T07", latitude=-6.3500, longitude=-50.3200, pga_g=0.115, municipio_uf="São Félix/PA", profundidade_km=15.0),
        EstacaoPGA(codigo_estacao="EST_T08", latitude=-6.1800, longitude=-49.8500, pga_g=0.038, municipio_uf="Tucumã/PA", profundidade_km=10.0),
        EstacaoPGA(codigo_estacao="EST_T09", latitude=-5.9500, longitude=-50.5500, pga_g=0.052, municipio_uf="Ourilândia/PA", profundidade_km=9.5),
        EstacaoPGA(codigo_estacao="EST_T10", latitude=-6.4200, longitude=-49.9500, pga_g=0.095, municipio_uf="Redenção/PA", profundidade_km=12.5),
        EstacaoPGA(codigo_estacao="EST_T11", latitude=-6.2800, longitude=-50.5100, pga_g=0.160, municipio_uf="Altamira/PA", profundidade_km=16.0),
        EstacaoPGA(codigo_estacao="EST_T12", latitude=-6.0700, longitude=-49.7200, pga_g=0.030, municipio_uf="Tucuruí/PA", profundidade_km=18.0),
    ]
    with app.app_context():
        for s in stations:
            db.session.add(s)
        db.session.commit()
    return stations

# =========================================================================
# 1. TESTES DO MODELO E PERSISTÊNCIA ESPACIAL NO POSTGIS
# =========================================================================

def test_model_spatial_insertion(app):
    """Valida inserção de estação com geometria Point SRID 4326 e novos campos."""
    with app.app_context():
        estacao = EstacaoPGA(
            codigo_estacao="EST_SPATIAL_01",
            latitude=-6.123456,
            longitude=-50.654321,
            pga_g=0.185,
            municipio_uf="Marabá/PA",
            profundidade_km=15.5
        )
        db.session.add(estacao)
        db.session.commit()

        recuperada = EstacaoPGA.query.filter_by(codigo_estacao="EST_SPATIAL_01").first()
        assert recuperada is not None
        assert recuperada.id > 0
        assert recuperada.latitude == -6.123456
        assert recuperada.longitude == -50.654321
        assert recuperada.pga_g == 0.185
        assert recuperada.municipio_uf == "Marabá/PA"
        assert recuperada.profundidade_km == 15.5
        assert recuperada.geom is not None

        # Validação do método to_geojson_feature
        feat = recuperada.to_geojson_feature()
        assert feat["type"] == "Feature"
        assert feat["geometry"]["type"] == "Point"
        assert feat["geometry"]["coordinates"] == [-50.654321, -6.123456]
        assert feat["properties"]["codigo_estacao"] == "EST_SPATIAL_01"
        assert feat["properties"]["municipio_uf"] == "Marabá/PA"
        assert feat["properties"]["profundidade_km"] == 15.5

# =========================================================================
# 2. TESTES DE SEGURANÇA E VALIDAÇÃO DE ENTRADA
# =========================================================================

def test_input_validation_latitude_out_of_bounds(client):
    """Garante que latitudes fora de [-90, 90] sejam rejeitadas com HTTP 400."""
    payload = {
        "codigo_estacao": "EST_INVALID_LAT",
        "latitude": 95.0,
        "longitude": -50.0,
        "pga_g": 0.10
    }
    res = client.post("/api/estacoes", json=payload)
    assert res.status_code == 400
    assert "Latitude fora dos limites físicos" in res.get_json()["message"]

def test_input_validation_longitude_out_of_bounds(client):
    """Garante que longitudes fora de [-180, 180] sejam rejeitadas com HTTP 400."""
    payload = {
        "codigo_estacao": "EST_INVALID_LON",
        "latitude": -6.0,
        "longitude": -195.0,
        "pga_g": 0.10
    }
    res = client.post("/api/estacoes", json=payload)
    assert res.status_code == 400
    assert "Longitude fora dos limites físicos" in res.get_json()["message"]

def test_input_validation_pga_negative_or_zero(client):
    """Garante que valores de PGA <= 0 sejam rejeitados com HTTP 400."""
    payload = {
        "codigo_estacao": "EST_INVALID_PGA",
        "latitude": -6.0,
        "longitude": -50.0,
        "pga_g": -0.05
    }
    res = client.post("/api/estacoes", json=payload)
    assert res.status_code == 400
    assert "limites válidos" in res.get_json()["message"]

def test_security_headers_present(client):
    """Garante que cabeçalhos de segurança essenciais estejam configurados."""
    res = client.get("/")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "1; mode=block" in res.headers.get("X-XSS-Protection", "")

# =========================================================================
# 3. TESTES DO MOTOR DE KRIGAGEM E MODELOS
# =========================================================================

@pytest.mark.parametrize("modelo", ["spherical", "exponential", "gaussian", "linear"])
def test_kriging_all_models_success(app, sample_stations, modelo):
    """Valida a execução da Krigagem Ordinária para todos os 4 modelos suportados."""
    with app.app_context():
        geojson = KrigingEngine.execute_interpolation(modelo=modelo, resolucao=25)
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) > 0

        meta = geojson["metadata"]
        assert meta["modelo_semivariograma"] == modelo
        assert meta["total_estacoes"] == 12

        first_cell = geojson["features"][0]
        assert first_cell["geometry"]["type"] == "Polygon"
        assert "pga_g" in first_cell["properties"]
        assert not math.isnan(first_cell["properties"]["pga_g"])

# =========================================================================
# 4. TESTES DE TRATAMENTO DE EXCEÇÕES GEOESTATÍSTICAS
# =========================================================================

def test_kriging_exception_less_than_4_stations(app, client):
    """Garante que a interpolação com menos de 4 estações seja bloqueada graciosamente com HTTP 400."""
    with app.app_context():
        for i in range(3):
            db.session.add(EstacaoPGA(f"EST_POUCO_{i}", -6.0 + i*0.1, -50.0 + i*0.1, 0.1))
        db.session.commit()

    res = client.post("/api/interpolar", json={"modelo": "spherical"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["status"] == "error"
    assert "no mínimo 4 estações" in data["message"]

def test_kriging_exception_collinear_stations(app, client):
    """Garante que estações colineares sejam bloqueadas com HTTP 400."""
    with app.app_context():
        for i in range(5):
            db.session.add(EstacaoPGA(f"EST_COLIN_{i}", -6.0, -50.0 + (i * 0.1), 0.1 + (i * 0.02)))
        db.session.commit()

    res = client.post("/api/interpolar", json={"modelo": "spherical"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["status"] == "error"
    assert "colinear" in data["message"].lower() or "singular" in data["message"].lower()

# =========================================================================
# 5. TESTES DOS ENDPOINTS REST DA API & UPLOAD
# =========================================================================

def test_api_crud_endpoints(client):
    """Testa ciclo completo: Cadastro, Consulta, Interpolação e Exclusão via REST."""
    stations = [
        {"codigo_estacao": "EST_API_1", "latitude": -6.0, "longitude": -50.0, "pga_g": 0.05, "municipio_uf": "M1"},
        {"codigo_estacao": "EST_API_2", "latitude": -6.2, "longitude": -50.0, "pga_g": 0.12, "municipio_uf": "M2"},
        {"codigo_estacao": "EST_API_3", "latitude": -6.0, "longitude": -50.3, "pga_g": 0.08, "municipio_uf": "M3"},
        {"codigo_estacao": "EST_API_4", "latitude": -6.2, "longitude": -50.3, "pga_g": 0.15, "municipio_uf": "M4"},
    ]
    for s in stations:
        res = client.post("/api/estacoes", json=s)
        assert res.status_code == 201

    res = client.get("/api/estacoes")
    assert res.status_code == 200
    body = res.get_json()
    assert body["total"] == 4

    res = client.post("/api/interpolar", json={"modelo": "spherical", "resolucao": 20})
    assert res.status_code == 200

    first_id = body["features"][0]["id"]
    res_del = client.delete(f"/api/estacoes/{first_id}")
    assert res_del.status_code == 200

def test_api_csv_upload(client):
    """Testa o endpoint de upload seguro de arquivo CSV."""
    csv_content = (
        "codigo_estacao,municipio_uf,latitude,longitude,profundidade_km,pga_g\n"
        "EST_CSV1,Belém/PA,-1.4500,-48.5000,15.0,0.020\n"
        "EST_CSV2,Marabá/PA,-5.3600,-49.1100,12.0,0.045\n"
        "EST_CSV3,Santarém/PA,-2.4400,-54.7000,18.0,0.030\n"
        "EST_CSV4,Manaus/AM,-3.1100,-60.0200,20.0,0.025\n"
    )
    data = {
        "file": (io.BytesIO(csv_content.encode("utf-8")), "estacoes_teste.csv")
    }
    res = client.post("/api/estacoes/upload", data=data, content_type="multipart/form-data")
    assert res.status_code == 201
    resp_data = res.get_json()
    assert resp_data["status"] == "success"
    assert resp_data["detalhes"]["processados"] == 4

def test_api_geojson_upload(client):
    """Testa o endpoint de upload seguro de arquivo GeoJSON."""
    geojson_dict = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-49.982, -5.923]},
                "properties": {"codigo_estacao": "EST_G1", "municipio_uf": "Parauapebas/PA", "pga_g": 0.082, "profundidade_km": 10.0}
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-50.320, -6.350]},
                "properties": {"codigo_estacao": "EST_G2", "municipio_uf": "Canaã/PA", "pga_g": 0.115, "profundidade_km": 12.0}
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-48.503, -1.455]},
                "properties": {"codigo_estacao": "EST_G3", "municipio_uf": "Belém/PA", "pga_g": 0.018, "profundidade_km": 20.0}
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-60.021, -3.119]},
                "properties": {"codigo_estacao": "EST_G4", "municipio_uf": "Manaus/AM", "pga_g": 0.021, "profundidade_km": 22.0}
            }
        ]
    }
    data = {
        "file": (io.BytesIO(json.dumps(geojson_dict).encode("utf-8")), "estacoes_teste.geojson")
    }
    res = client.post("/api/estacoes/upload", data=data, content_type="multipart/form-data")
    assert res.status_code == 201
    resp_data = res.get_json()
    assert resp_data["status"] == "success"
    assert resp_data["detalhes"]["processados"] == 4

# =========================================================================
# 6. TESTE DE INTEGRAÇÃO DO DATASET REGIÃO NORTE (20 ESTAÇÕES) & KRIGAGEM SEM NAN
# =========================================================================

def test_seed_norte_dataset_and_kriging_no_nan(app, client):
    """
    Testa a importação do arquivo data/estacoes_pga_norte_brasil.csv,
    valida a presença das 20 estações no PostGIS e executa a krigagem ordinária
    verificando que a matriz gerada é 100% válida e livre de valores NaN.
    """
    # 1. Executar seed do Norte
    res_seed = client.post("/api/estacoes/seed-norte")
    assert res_seed.status_code == 200
    data_seed = res_seed.get_json()
    assert data_seed["status"] == "success"
    assert data_seed["processados"] == 20
    assert data_seed["total_banco"] >= 20

    # 2. Verificar que estações foram persistidas no PostGIS com atributos corretos
    with app.app_context():
        czs = EstacaoPGA.query.filter_by(codigo_estacao="EST_AC_CZS").first()
        assert czs is not None
        assert czs.municipio_uf == "Cruzeiro do Sul/AC"
        assert czs.latitude == -7.6306
        assert czs.longitude == -72.6700
        assert czs.pga_g == 0.165
        assert czs.profundidade_km == 32.0

        bel = EstacaoPGA.query.filter_by(codigo_estacao="EST_PA_BEL").first()
        assert bel is not None
        assert bel.municipio_uf == "Belém/PA"

    # 3. Executar Krigagem Ordinária na escala da Região Norte (resolução 60x60)
    res_krig = client.post("/api/interpolar", json={"modelo": "spherical", "resolucao": 60})
    assert res_krig.status_code == 200
    geojson = res_krig.get_json()
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) > 0

    meta = geojson["metadata"]
    assert meta["modelo_semivariograma"] == "spherical"
    assert meta["total_estacoes"] >= 20
    assert not math.isnan(meta["pga_media"])
    assert not math.isnan(meta["pga_min"])
    assert not math.isnan(meta["pga_max"])
    assert meta["pga_min"] >= 0.0

    # 4. Validar que nenhuma célula contém NaN ou valores nulos
    for feat in geojson["features"]:
        props = feat["properties"]
        pga = props["pga_g"]
        var = props["variancia"]
        std = props["desvio_padrao"]

        assert pga is not None
        assert not math.isnan(pga)
        assert pga >= 0.0

        assert var is not None
        assert not math.isnan(var)
        assert var >= 0.0

        assert std is not None
        assert not math.isnan(std)
        assert std >= 0.0

def test_api_export_csv(app, sample_stations, client):
    """Testa o endpoint de exportação de dados em CSV."""
    res = client.get("/api/estacoes/exportar-csv")
    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    content = res.data.decode("utf-8")
    assert "codigo_estacao,municipio_uf,latitude,longitude,profundidade_km,pga_g" in content
    assert "EST_T01" in content
