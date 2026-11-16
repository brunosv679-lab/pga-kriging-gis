import math
import numpy as np
import pyproj
from pykrige.ok import OrdinaryKriging
from sqlalchemy import text
from app import db
from app.models.estacao_pga import EstacaoPGA

class KrigingError(Exception):
    """Exceção base para erros no motor de krigagem."""
    pass

class KrigingValidationError(KrigingError):
    """Exceção levantada quando validações preliminares falham (< 4 pontos, modelo inválido)."""
    pass

class KrigingSingularMatrixError(KrigingError):
    """Exceção levantada quando matriz é singular ou pontos são colineares."""
    pass

def classify_pga(pga_value):
    """
    Classifica o valor de PGA (em g) de acordo com a escala de intensidade e risco sísmico.
    Retorna (categoria, cor_hex, nivel).
    """
    if pga_value < 0.02:
        return "Muito Baixo (Instrumental)", "#10b981", 1  # Verde
    elif pga_value < 0.05:
        return "Baixo (Percepção Leve)", "#06b6d4", 2      # Ciano
    elif pga_value < 0.10:
        return "Moderado (Sentido por muitos)", "#eab308", 3  # Amarelo
    elif pga_value < 0.20:
        return "Alto (Danos Leves)", "#f97316", 4           # Laranja
    elif pga_value < 0.40:
        return "Muito Alto (Danos Estruturais)", "#ef4444", 5 # Vermelho
    else:
        return "Extremo (Risco Severo)", "#8b5cf6", 6       # Púrpura

class KrigingEngine:
    """
    Motor matemático de geoestatística para interpolação de PGA via Krigagem Ordinária.
    Reprojeta dinamicamente pontos para coordenadas métricas UTM via PostGIS / pyproj,
    avalia semivariogramas teóricos e projeta os resultados em malha poligonal GeoJSON WGS84.
    """
    SUPPORTED_MODELS = ["spherical", "exponential", "gaussian", "linear"]

    @staticmethod
    def get_utm_epsg(mean_lon, mean_lat):
        """Calcula o código EPSG da projeção UTM correspondente às coordenadas médias."""
        zone = int((mean_lon + 180.0) / 6.0) + 1
        base = 32600 if mean_lat >= 0 else 32700
        return base + zone, zone

    @classmethod
    def check_collinearity(cls, x_coords, y_coords, threshold=0.01):
        """
        Verifica se os pontos 2D são colineares ou quase colineares através da SVD das coordenadas centralizadas.
        Se a razão entre o menor e maior valor singular for menor que o limiar (padrão 1%),
        os pontos estão distribuídos em linha reta e inviabilizam a interpolação 2D.
        """
        if len(x_coords) < 3:
            return True
        pts = np.column_stack((x_coords - np.mean(x_coords), y_coords - np.mean(y_coords)))
        s = np.linalg.svd(pts, compute_uv=False)
        if s[0] == 0:
            return True
        ratio = s[1] / s[0]
        return ratio < threshold

    @classmethod
    def execute_interpolation(cls, modelo="spherical", resolucao=60):
        """
        Executa o pipeline completo de Krigagem Ordinária:
        1. Consulta estações no PostGIS
        2. Valida quantitativo de pontos (mínimo 4)
        3. Valida modelo e resolução
        4. Transforma coordenadas para UTM métrico via PostGIS ST_Transform
        5. Testa colinearidade espacial
        6. Interpola via OrdinaryKriging (PyKrige)
        7. Reprojeta a grade estimada de volta para WGS84 (EPSG:4326) em GeoJSON
        """
        modelo = str(modelo).lower().strip()
        if modelo not in cls.SUPPORTED_MODELS:
            raise KrigingValidationError(
                f"Modelo de semivariograma inválido: '{modelo}'. "
                f"Modelos suportados: {', '.join(cls.SUPPORTED_MODELS)}."
            )

        try:
            resolucao = int(resolucao)
        except (ValueError, TypeError):
            resolucao = 60
        if resolucao < 10 or resolucao > 120:
            raise KrigingValidationError("A resolução da malha deve estar compreendida entre 10 e 120 células por eixo.")

        # Buscar estações cadastradas
        estacoes = EstacaoPGA.query.order_by(EstacaoPGA.id).all()
        total_estacoes = len(estacoes)

        if total_estacoes < 4:
            raise KrigingValidationError(
                f"Número insuficiente de estações cadastradas ({total_estacoes}). "
                "São necessárias no mínimo 4 estações distribuídas no espaço para realizar a Krigagem Ordinária."
            )

        lons = np.array([e.longitude for e in estacoes], dtype=float)
        lats = np.array([e.latitude for e in estacoes], dtype=float)
        pgas = np.array([e.pga_g for e in estacoes], dtype=float)

        # Checagem preliminar de colinearidade em coordenadas angulares geográficas
        if cls.check_collinearity(lons, lats, threshold=0.005):
            raise KrigingSingularMatrixError(
                "As estações sismográficas informadas estão dispostas de forma colinear (em linha reta), "
                "o que torna a matriz de covariância espacial singular e impede a interpolação bidimensional."
            )

        mean_lon = float(np.mean(lons))
        mean_lat = float(np.mean(lats))
        utm_epsg, utm_zone = cls.get_utm_epsg(mean_lon, mean_lat)

        # Reprojeção métrica via PostGIS ST_Transform
        try:
            query = text("""
                SELECT id, codigo_estacao, pga_g,
                       ST_X(ST_Transform(geom, :srid)) AS utm_x,
                       ST_Y(ST_Transform(geom, :srid)) AS utm_y
                FROM estacoes_pga
                ORDER BY id
            """)
            result = db.session.execute(query, {"srid": utm_epsg}).mappings().all()
            utm_x = np.array([r["utm_x"] for r in result], dtype=float)
            utm_y = np.array([r["utm_y"] for r in result], dtype=float)
            pga_vals = np.array([r["pga_g"] for r in result], dtype=float)
        except Exception:
            to_utm = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)
            utm_x, utm_y = to_utm.transform(lons, lats)
            pga_vals = pgas

        # Validação de Colinearidade dos Pontos em UTM métrico
        if cls.check_collinearity(utm_x, utm_y, threshold=0.01):
            raise KrigingSingularMatrixError(
                "As estações sismográficas informadas estão dispostas de forma colinear (em linha reta), "
                "o que torna a matriz de covariância espacial singular e impede a interpolação bidimensional."
            )

        # Definição dos limites da malha com margem de 10%
        min_x, max_x = float(np.min(utm_x)), float(np.max(utm_x))
        min_y, max_y = float(np.min(utm_y)), float(np.max(utm_y))

        span_x = max(max_x - min_x, 1000.0)
        span_y = max(max_y - min_y, 1000.0)
        margin_x = span_x * 0.10
        margin_y = span_y * 0.10

        grid_min_x, grid_max_x = min_x - margin_x, max_x + margin_x
        grid_min_y, grid_max_y = min_y - margin_y, max_y + margin_y

        grid_x_1d = np.linspace(grid_min_x, grid_max_x, resolucao)
        grid_y_1d = np.linspace(grid_min_y, grid_max_y, resolucao)

        # Executar OrdinaryKriging
        try:
            ok = OrdinaryKriging(
                x=utm_x,
                y=utm_y,
                z=pga_vals,
                variogram_model=modelo,
                verbose=False,
                enable_plotting=False
            )
            z_grid, ss_grid = ok.execute("grid", grid_x_1d, grid_y_1d)
        except np.linalg.LinAlgError:
            raise KrigingSingularMatrixError(
                "A matriz de ponderação geoestatística é singular. "
                "Verifique a existência de estações com coordenadas idênticas ou quase coincidentes."
            )
        except Exception as exc:
            msg = str(exc)
            if "singular" in msg.lower() or "matrix" in msg.lower():
                raise KrigingSingularMatrixError(
                    f"Erro de matriz singular no ajuste do semivariograma: {msg}"
                )
            raise KrigingError(f"Falha na execução da Krigagem Ordinária: {msg}")

        z_grid = np.array(z_grid, dtype=float)
        ss_grid = np.array(ss_grid, dtype=float)

        to_wgs84 = pyproj.Transformer.from_crs(f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True)

        features = []

        # Montar polígonos GeoJSON para cada célula da malha regular
        for j in range(resolucao - 1):
            y0 = grid_y_1d[j]
            y1 = grid_y_1d[j + 1]
            for i in range(resolucao - 1):
                x0 = grid_x_1d[i]
                x1 = grid_x_1d[i + 1]

                raw_val = z_grid[j, i]
                raw_var = ss_grid[j, i]

                # Prevenção contra NaN em extrapoladores distantes
                cell_pga = 0.0 if (math.isnan(raw_val) or np.isnan(raw_val)) else float(max(0.0, raw_val))
                cell_var = 0.0 if (math.isnan(raw_var) or np.isnan(raw_var)) else float(max(0.0, raw_var))
                cell_std = math.sqrt(cell_var)

                utm_poly_x = [x0, x1, x1, x0, x0]
                utm_poly_y = [y0, y0, y1, y1, y0]
                wgs_lons, wgs_lats = to_wgs84.transform(utm_poly_x, utm_poly_y)

                poly_coords = [[
                    [round(float(wgs_lons[k]), 6), round(float(wgs_lats[k]), 6)]
                    for k in range(5)
                ]]

                risco, cor, nivel = classify_pga(cell_pga)

                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": poly_coords
                    },
                    "properties": {
                        "pga_g": round(cell_pga, 4),
                        "variancia": round(cell_var, 6),
                        "desvio_padrao": round(cell_std, 4),
                        "risco_sismico": risco,
                        "nivel_risco": nivel,
                        "cor": cor
                    }
                })

        valid_pga = np.nan_to_num(np.clip(z_grid, 0, None), nan=0.0)
        valid_var = np.nan_to_num(np.clip(ss_grid, 0, None), nan=0.0)

        stats = {
            "modelo_semivariograma": modelo,
            "total_estacoes": total_estacoes,
            "resolucao_grade": f"{resolucao}x{resolucao}",
            "total_celulas": len(features),
            "utm_epsg": utm_epsg,
            "utm_zona": f"{utm_zone}{'N' if mean_lat >= 0 else 'S'}",
            "pga_min": round(float(np.min(valid_pga)), 4),
            "pga_max": round(float(np.max(valid_pga)), 4),
            "pga_media": round(float(np.mean(valid_pga)), 4),
            "variancia_min": round(float(np.min(valid_var)), 6),
            "variancia_max": round(float(np.max(valid_var)), 6),
            "variancia_media": round(float(np.mean(valid_var)), 6),
            "bbox_wgs84": [
                round(float(np.min(lons)), 6),
                round(float(np.min(lats)), 6),
                round(float(np.max(lons)), 6),
                round(float(np.max(lats)), 6)
            ]
        }

        return {
            "type": "FeatureCollection",
            "metadata": stats,
            "features": features
        }
