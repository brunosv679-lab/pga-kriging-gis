# Sistema de Interpolação de Aceleração Máxima do Solo (PGA) por Krigagem Ordinária

Aplicação web geoespacial (GIS) de nível de produção para interpolação espacial de dados sismográficos de Pico de Aceleração do Solo (**Peak Ground Acceleration - PGA**) utilizando **Krigagem Ordinária** (Ordinary Kriging), **PostgreSQL + PostGIS**, e visualização interativa com **Leaflet.js** e **Tailwind CSS**.

---

## 🚀 Deploy Automatizado em Nova VM (Ubuntu Server com IP Público)

> **Em uma VM Ubuntu Server limpa (22.04 / 24.04 / 26.04), toda a infraestrutura — PostgreSQL/PostGIS, Python/Flask, Gunicorn, Nginx e Firewall UFW — sobe em minutos com um único comando.**

### Pré-requisito
- VM Ubuntu Server com acesso root/sudo e conexão à internet.

### Passo a Passo

```bash
# 1. Clone o repositório
git clone https://github.com/brunosv679-lab/pga-kriging-gis.git
cd pga-kriging-gis

# 2. Execute o provisionamento automático
sudo ./setup.sh
```

O script `setup.sh` é **idempotente** e executa automaticamente:

| Etapa | O que faz |
|-------|-----------|
| ✅ **Dependências do Sistema** | Instala `python3-venv`, `libpq-dev`, `build-essential`, `postgresql`, `postgis`, `nginx`, `ufw` |
| ✅ **PostgreSQL + PostGIS** | Cria role `pga_app`, banco `pga_db`, ativa extensão PostGIS, concede privilégios |
| ✅ **venv Python** | Cria ambiente virtual e instala todas as dependências de `requirements.txt` |
| ✅ **`.env` Seguro** | Gera `SECRET_KEY` criptográfica nova e `DATABASE_URL` com senha aleatória (`chmod 600`) |
| ✅ **Tabelas + Dados** | Executa `db.create_all()` e carga inicial das 35 estações nacionais (NBR 15421) |
| ✅ **Gunicorn + Systemd** | Cria e ativa `pga-kriging.service` (3 workers, `bind 127.0.0.1:8000`) |
| ✅ **Nginx** | Configura proxy reverso na porta 80 com headers de segurança e cache de estáticos |
| ✅ **Firewall UFW** | Libera apenas SSH e Nginx Full; bloqueia PostgreSQL (5432) externamente |

### Após o Deploy

```bash
# Verificar status da aplicação
sudo systemctl status pga-kriging

# Acompanhar logs em tempo real
sudo journalctl -u pga-kriging -f

# Verificar regras de firewall
sudo ufw status verbose

# Recarregar Nginx após mudanças
sudo nginx -t && sudo systemctl reload nginx
```

A aplicação estará disponível em `http://<IP_PUBLICO_DA_VM>/`.

---

## 1. Arquitetura do Sistema (Padrão MVC)

O projeto segue a arquitetura Model-View-Controller (MVC) com separação modular de responsabilidades:

```
pga-kriging-gis/
├── app/
│   ├── __init__.py               # Application Factory, Flask-WTF, Security Headers, DB Init
│   ├── models/
│   │   ├── __init__.py
│   │   └── estacao_pga.py        # Entidade PostGIS (Geometry POINT, SRID 4326, GIST, Região)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── kriging_engine.py     # Motor Geoestatístico PyKrige, Reprojeção UTM, GeoJSON
│   │   └── data_importer.py      # Ingestão Segura (.csv/.geojson) com Upsert PostGIS
│   ├── controllers/
│   │   ├── __init__.py
│   │   └── mapa_routes.py        # Endpoints REST (CRUD, Upload, Seed Norte/Brasil, Export)
│   ├── templates/
│   │   └── index.html            # Dashboard Fullscreen, Painel Retrátil, Leaflet Map
│   └── static/
│       ├── css/style.css         # Tema Dark/Glassmorphism Técnico
│       └── js/map_kriging.js     # Controle do Mapa, Camadas, Legenda Dinâmica
├── data/
│   ├── estacoes_pga_norte_brasil.csv      # 20 Estações — Região Norte
│   ├── estacoes_norte.geojson             # FeatureCollection WGS84 — Norte
│   └── estacoes_pga_brasil_completo.csv   # 35 Estações — Brasil Completo (NBR 15421)
├── tests/
│   └── test_kriging.py           # Testes Automatizados com Pytest
├── logs/                         # Logs Gunicorn (gerado pelo setup.sh)
├── setup.sh                      # 🚀 Script de Provisionamento Automatizado
├── run.py                        # Ponto de Entrada Flask (desenvolvimento)
├── seed_data.py                  # Script de Carga Manual (Região Norte)
├── requirements.txt              # Dependências Python (inclui gunicorn)
├── .env                          # Variáveis de Ambiente (NÃO versioneie)
├── .env.example                  # Template de Configuração
├── .gitignore                    # Protege .env, venv/, __pycache__/
└── README.md
```

---

## 2. Stack Tecnológica

| Camada | Tecnologias |
|--------|-------------|
| **Backend** | Python 3.12+, Flask 3.1, SQLAlchemy 2.x, GeoAlchemy2 0.21, Psycopg 3, Flask-WTF (CSRF) |
| **Produção** | Gunicorn 23 (3 workers sync), Nginx (proxy reverso), Systemd (serviço auto-restart) |
| **Geoestatística** | PyKrige 1.7 (`OrdinaryKriging`), NumPy 2.x, SciPy 1.18, PyProj 3.8 |
| **Banco Espacial** | PostgreSQL + PostGIS (`Geometry('POINT', srid=4326)`, índice `GIST`) |
| **Frontend** | HTML5, Tailwind CSS (CDN, dark theme), Leaflet.js 1.9, FontAwesome 6 |
| **Segurança** | CSRF via Flask-WTF, Security Headers HTTP, UFW Firewall, `.env` chmod 600 |

---

## 3. Dataset Nacional (NBR 15421) — 35 Estações

A aplicação inclui nativamente **35 estações sismográficas** cobrindo todas as 5 regiões do Brasil:

| Região | Estações | Destaque Sísmico |
|--------|----------|-----------------|
| **Norte** | 8 | Cruzeiro do Sul/AC (PGA 0.165g), Carajás/PA (0.085g) |
| **Nordeste** | 8 | João Câmara/RN (0.155g), Sobral/CE (0.110g) |
| **Centro-Oeste** | 6 | Porto dos Gaúchos/MT (0.140g), Mara Rosa/GO (0.095g) |
| **Sudeste** | 7 | Montes Claros/MG (0.125g), Bebedouro/SP (0.090g) |
| **Sul** | 6 | Londrina/PR (0.055g), Lages/SC (0.028g) |

> Dataset geoestatisticamente distribuído sem pontos colineares, garantindo estabilidade numérica da Krigagem Ordinária.

---

## 4. Endpoints REST da API

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `GET` | `/` | Interface web do Dashboard GIS |
| `GET` | `/api/csrf-token` | Token CSRF para clientes REST |
| `GET` | `/api/estacoes` | GeoJSON FeatureCollection de todas as estações |
| `POST` | `/api/estacoes` | Cadastra estação individual (JSON) |
| `POST` | `/api/estacoes/upload` | Ingestão segura de `.csv` ou `.geojson` |
| `POST` | `/api/estacoes/seed-norte` | Carrega as 20 estações da Região Norte |
| `POST` | `/api/estacoes/seed-brasil` | Carrega as 35 estações do Brasil Completo (NBR 15421) |
| `GET` | `/api/estacoes/exportar-csv` | Download de todas as estações em CSV |
| `POST` | `/api/interpolar` | Executa Krigagem Ordinária → GeoJSON grid |
| `DELETE` | `/api/estacoes/<id>` | Remove estação pelo ID |
| `GET` | `/api/sample-csv` | Download de CSV modelo |

### Exemplo: Executar Krigagem (curl)
```bash
# Obter token CSRF
TOKEN=$(curl -s http://localhost/api/csrf-token | python3 -c "import sys,json; print(json.load(sys.stdin)['csrf_token'])")

# Executar krigagem com modelo esférico 80x80
curl -X POST http://localhost/api/interpolar \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $TOKEN" \
  -d '{"modelo": "spherical", "resolucao": 80}'
```

---

## 5. Desenvolvimento Local (sem setup.sh)

### Pré-requisitos
- PostgreSQL com PostGIS instalado
- Python 3.12+

### Configuração manual

```bash
# 1. Clone e entre no diretório
git clone https://github.com/brunosv679-lab/pga-kriging-gis.git
cd pga-kriging-gis

# 2. Crie o banco e ative o PostGIS
sudo -u postgres createuser -P pga_app
sudo -u postgres createdb -O pga_app pga_db
sudo -u postgres psql -d pga_db -c "CREATE EXTENSION postgis;"

# 3. Configure o ambiente
cp .env.example .env
# Edite .env com sua DATABASE_URL e gere uma SECRET_KEY

# 4. Instale dependências Python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Inicialize e rode
python run.py
```

Acesse: `http://localhost:5000`

---

## 6. Testes Automatizados

```bash
source venv/bin/activate
pytest -v tests/test_kriging.py
```

A suíte cobre:
- Inserção espacial e validação de geometria PostGIS
- Serialização GeoJSON (`to_geojson_feature`)
- Interpolação por Krigagem Ordinária (4 modelos de semivariograma)
- Upload seguro de `.csv` e `.geojson`
- Seed do dataset Região Norte + validação NaN-free
- Exportação CSV e tratamento de exceções

---

## 7. Segurança

- **CSRF Protection** via Flask-WTF em todos os formulários e endpoints sensíveis
- **Security Headers HTTP**: `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`, `Content-Security-Policy`
- **Sem credenciais em código**: todas as chaves via `os.getenv()` do `.env` (bloqueado no `.gitignore`)
- **Validação e Sanitização** de todos os inputs: coordenadas, PGA, códigos de estação
- **Consultas parametrizadas** via SQLAlchemy (prevenção de SQL Injection)
- **Firewall UFW**: apenas SSH e Nginx Full expostos; PostgreSQL (5432) interno
- **Gunicorn** em modo não-debug; Nginx remove headers de versão do servidor

---

## 8. Licença

MIT License — Bruno SV679 Lab
