from datetime import datetime
from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import Column, Integer, String, Float, DateTime, Index, func
from app import db

class EstacaoPGA(db.Model):
    """
    Modelo representativo de uma Estação Sismográfica com registro de PGA (Peak Ground Acceleration).
    Mapeia pontos espaciais com SRID 4326 e índice espacial GIST no PostGIS.
    """
    __tablename__ = "estacoes_pga"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    codigo_estacao = db.Column(db.String(50), unique=True, nullable=False, index=True)
    municipio_uf = db.Column(db.String(100), nullable=True)
    regiao = db.Column(db.String(50), nullable=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    profundidade_km = db.Column(db.Float, nullable=True, default=10.0)
    pga_g = db.Column(db.Float, nullable=False)
    ano_evento = db.Column(db.Integer, nullable=True)
    magnitude_mw = db.Column(db.Float, nullable=True)

    # Campo espacial Point em WGS84 (SRID 4326) com índice espacial GIST
    geom = db.Column(Geometry(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Índice explícito adicional para garantir a indexação GIST
    __table_args__ = (
        Index("idx_estacoes_pga_geom_gist", "geom", postgresql_using="gist"),
    )

    def __init__(self, codigo_estacao, latitude, longitude, pga_g, municipio_uf=None, profundidade_km=10.0, regiao=None, ano_evento=None, magnitude_mw=None):
        self.codigo_estacao = codigo_estacao.strip().upper()
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self.pga_g = float(pga_g)
        self.municipio_uf = municipio_uf.strip() if municipio_uf else None
        self.profundidade_km = float(profundidade_km) if profundidade_km is not None else 10.0
        self.regiao = regiao.strip() if regiao else None
        self.ano_evento = int(ano_evento) if ano_evento is not None else None
        self.magnitude_mw = float(magnitude_mw) if magnitude_mw is not None else None
        # PostGIS POINT(longitude latitude) para X Y
        self.geom = WKTElement(f"POINT({self.longitude} {self.latitude})", srid=4326)

    def to_dict(self):
        """Retorna representação serializável em JSON."""
        return {
            "id": self.id,
            "codigo_estacao": self.codigo_estacao,
            "municipio_uf": self.municipio_uf,
            "regiao": self.regiao,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "profundidade_km": self.profundidade_km,
            "pga_g": self.pga_g,
            "ano_evento": self.ano_evento,
            "magnitude_mw": self.magnitude_mw,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

    def to_geojson_feature(self):
        """Retorna uma Feature GeoJSON padrão para visualização no Leaflet."""
        return {
            "type": "Feature",
            "id": self.id,
            "geometry": {
                "type": "Point",
                "coordinates": [self.longitude, self.latitude]
            },
            "properties": {
                "id": self.id,
                "codigo_estacao": self.codigo_estacao,
                "municipio_uf": self.municipio_uf or "Não informado",
                "regiao": self.regiao or "Brasil",
                "latitude": self.latitude,
                "longitude": self.longitude,
                "profundidade_km": self.profundidade_km if self.profundidade_km is not None else 10.0,
                "pga_g": self.pga_g,
                "ano_evento": self.ano_evento,
                "magnitude_mw": self.magnitude_mw,
                "created_at": self.created_at.isoformat() if self.created_at else None
            }
        }
