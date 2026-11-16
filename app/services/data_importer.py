import csv
import io
import json
import re
from sqlalchemy import text
from app import db
from app.models.estacao_pga import EstacaoPGA

class DataImportError(Exception):
    """Exceção base para erros de importação de dados."""
    pass

class DataValidationError(DataImportError):
    """Exceção para dados que violem restrições físicas ou de formato."""
    pass

def sanitize_station_code(code_str):
    """Sanitiza o código da estação permitindo apenas caracteres alfanuméricos, hífen e underscore."""
    if not code_str:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9_\-]", "", str(code_str).strip())
    return cleaned.upper()[:50]

def sanitize_text(text_str, max_len=100):
    """Remove caracteres maliciosos e tags, permitindo acentuação e pontuação segura."""
    if not text_str:
        return None
    cleaned = re.sub(r"<[^>]*>", "", str(text_str).strip())
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", cleaned)
    return cleaned[:max_len]

def validate_physical_records(code, lat, lon, pga, municipio=None, profundidade=10.0, regiao=None):
    """
    Valida limites físicos rigorosos:
    - Latitude: [-90.0, 90.0]
    - Longitude: [-180.0, 180.0]
    - PGA: > 0.0 g e <= 5.0 g
    - Profundidade: >= 0.0 km e <= 700.0 km
    """
    code_clean = sanitize_station_code(code)
    if not code_clean:
        raise DataValidationError("Código da estação inválido ou vazio.")

    try:
        lat_f = float(lat)
        lon_f = float(lon)
        pga_f = float(pga)
        prof_f = float(profundidade) if profundidade is not None and str(profundidade).strip() != "" else 10.0
    except (ValueError, TypeError):
        raise DataValidationError(f"Coordenadas, PGA ou profundidade com valores não-numéricos para {code}.")

    if not (-90.0 <= lat_f <= 90.0):
        raise DataValidationError(f"Latitude fora dos limites físicos (-90 a 90): {lat_f}")
    if not (-180.0 <= lon_f <= 180.0):
        raise DataValidationError(f"Longitude fora dos limites físicos (-180 a 180): {lon_f}")
    if pga_f <= 0.0 or pga_f > 5.0:
        raise DataValidationError(f"PGA fora dos limites válidos (0.0 < PGA <= 5.0 g): {pga_f}")
    if prof_f < 0.0 or prof_f > 700.0:
        raise DataValidationError(f"Profundidade hipocentral improvável (0 a 700 km): {prof_f}")

    municipio_clean = sanitize_text(municipio, max_len=100) if municipio else None
    regiao_clean = sanitize_text(regiao, max_len=50) if regiao else None

    return {
        "codigo": code_clean,
        "municipio": municipio_clean,
        "regiao": regiao_clean,
        "lat": round(lat_f, 6),
        "lon": round(lon_f, 6),
        "pga": round(pga_f, 5),
        "prof": round(prof_f, 2)
    }

def find_column_index(col_map, candidates):
    """Localiza o índice da primeira coluna encontrada na lista de candidatos."""
    for cand in candidates:
        if cand in col_map:
            return col_map[cand]
    return None

class DataImporterService:
    """
    Serviço seguro de ingestão de dados para datasets sísmicos (.csv e .geojson).
    Executa sanitização, checagem de limites físicos e upsert transacional via PostGIS.
    """

    UPSERT_SQL = text("""
        INSERT INTO estacoes_pga (
            codigo_estacao, municipio_uf, regiao, latitude, longitude, profundidade_km, pga_g, geom
        ) VALUES (
            :codigo, :municipio, :regiao, :lat, :lon, :prof, :pga,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
        )
        ON CONFLICT (codigo_estacao) DO UPDATE SET
            municipio_uf = EXCLUDED.municipio_uf,
            regiao = EXCLUDED.regiao,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            profundidade_km = EXCLUDED.profundidade_km,
            pga_g = EXCLUDED.pga_g,
            geom = EXCLUDED.geom;
    """)

    @classmethod
    def import_from_csv_text(cls, csv_text):
        """
        Processa texto CSV de estações sísmicas e aplica o upsert no PostGIS.
        Retorna dicionário com estatísticas da importação.
        """
        stream = io.StringIO(csv_text.strip())
        reader = csv.reader(stream, delimiter=",")
        header = next(reader, None)
        if not header:
            raise DataValidationError("O arquivo CSV está vazio.")

        col_map = {col.strip().lower(): idx for idx, col in enumerate(header)}

        code_idx = find_column_index(col_map, ["codigo_estacao", "codigo", "station", "id", "nome"])
        lat_idx = find_column_index(col_map, ["latitude", "lat", "y"])
        lon_idx = find_column_index(col_map, ["longitude", "lon", "lng", "x"])
        pga_idx = find_column_index(col_map, ["pga_g", "pga", "aceleracao", "valor"])
        mun_idx = find_column_index(col_map, ["municipio_uf", "municipio", "cidade", "city", "local"])
        prof_idx = find_column_index(col_map, ["profundidade_km", "profundidade", "depth", "prof"])
        reg_idx = find_column_index(col_map, ["regiao", "region", "macroregiao"])

        missing = []
        if code_idx is None: missing.append("codigo_estacao")
        if lat_idx is None: missing.append("latitude")
        if lon_idx is None: missing.append("longitude")
        if pga_idx is None: missing.append("pga_g")

        if missing:
            raise DataValidationError(f"Colunas obrigatórias ausentes no CSV: {', '.join(missing)}")

        valid_records = []
        rejected = []

        for row_num, row in enumerate(reader, start=2):
            if not row or not any(row):
                continue
            if len(row) <= max(code_idx, lat_idx, lon_idx, pga_idx):
                continue
            try:
                raw_code = row[code_idx]
                raw_lat = row[lat_idx]
                raw_lon = row[lon_idx]
                raw_pga = row[pga_idx]
                raw_mun = row[mun_idx] if mun_idx is not None and mun_idx < len(row) else None
                raw_prof = row[prof_idx] if prof_idx is not None and prof_idx < len(row) else 10.0
                raw_reg = row[reg_idx] if reg_idx is not None and reg_idx < len(row) else None

                record = validate_physical_records(
                    raw_code, raw_lat, raw_lon, raw_pga, raw_mun, raw_prof, raw_reg
                )
                valid_records.append(record)
            except Exception as e:
                rejected.append(f"Linha {row_num}: {str(e)}")

        if not valid_records:
            raise DataValidationError(f"Nenhum registro válido encontrado no CSV. Erros: {'; '.join(rejected[:3])}")

        try:
            for rec in valid_records:
                db.session.execute(cls.UPSERT_SQL, rec)
            db.session.commit()
        except Exception as ex:
            db.session.rollback()
            raise DataImportError(f"Erro na transação de banco de dados: {str(ex)}")

        return {
            "status": "success",
            "processados": len(valid_records),
            "rejeitados": len(rejected),
            "erros": rejected[:10]
        }

    @classmethod
    def import_from_geojson_text(cls, geojson_text):
        """
        Processa texto GeoJSON contendo FeatureCollection ou Features de estações sísmicas.
        """
        try:
            data = json.loads(geojson_text)
        except Exception as ex:
            raise DataValidationError(f"Arquivo GeoJSON mal formatado: {str(ex)}")

        features = []
        if isinstance(data, dict):
            if data.get("type") == "FeatureCollection":
                features = data.get("features", [])
            elif data.get("type") == "Feature":
                features = [data]
        elif isinstance(data, list):
            features = data

        if not features:
            raise DataValidationError("Nenhuma Feature geométrica encontrada no GeoJSON.")

        valid_records = []
        rejected = []

        for idx, feat in enumerate(features, start=1):
            try:
                geom = feat.get("geometry") or {}
                if geom.get("type") != "Point":
                    rejected.append(f"Feature {idx}: Geometria deve ser 'Point'.")
                    continue

                coords = geom.get("coordinates")
                if not coords or len(coords) < 2:
                    rejected.append(f"Feature {idx}: Coordenadas [lon, lat] ausentes ou incompletas.")
                    continue

                lon = coords[0]
                lat = coords[1]

                props = feat.get("properties") or {}
                code = props.get("codigo_estacao") or props.get("codigo") or feat.get("id") or f"EST_GEO_{idx}"
                pga = props.get("pga_g") or props.get("pga") or props.get("aceleracao")
                mun = props.get("municipio_uf") or props.get("municipio")
                prof = props.get("profundidade_km") or props.get("profundidade") or 10.0
                reg = props.get("regiao") or props.get("region")

                if pga is None:
                    rejected.append(f"Feature {idx} ({code}): Atributo 'pga_g' ausente.")
                    continue

                record = validate_physical_records(code, lat, lon, pga, mun, prof, reg)
                valid_records.append(record)

            except Exception as e:
                rejected.append(f"Feature {idx}: {str(e)}")

        if not valid_records:
            raise DataValidationError(f"Nenhuma Feature válida encontrada. Erros: {'; '.join(rejected[:3])}")

        try:
            for rec in valid_records:
                db.session.execute(cls.UPSERT_SQL, rec)
            db.session.commit()
        except Exception as ex:
            db.session.rollback()
            raise DataImportError(f"Erro na transação de banco de dados: {str(ex)}")

        return {
            "status": "success",
            "processados": len(valid_records),
            "rejeitados": len(rejected),
            "erros": rejected[:10]
        }

    @classmethod
    def import_local_file(cls, file_path):
        """Carrega e ingere um arquivo físico local (.csv ou .geojson)."""
        file_path_str = str(file_path).lower()
        with open(file_path, "r", encoding="utf-8-sig") as f:
            content = f.read()

        if file_path_str.endswith(".csv"):
            return cls.import_from_csv_text(content)
        elif file_path_str.endswith(".geojson") or file_path_str.endswith(".json"):
            return cls.import_from_geojson_text(content)
        else:
            raise DataValidationError("Formato de arquivo não suportado. Utilize .csv ou .geojson.")
