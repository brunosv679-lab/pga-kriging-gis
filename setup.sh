#!/usr/bin/env bash
# =============================================================================
#  setup.sh — Provisionamento Automático do PGA Kriging GIS
#  Repositório: https://github.com/brunosv679-lab/pga-kriging-gis
#
#  Uso: sudo ./setup.sh
#
#  Idempotente: pode ser re-executado em qualquer momento sem quebrar o ambiente.
#  Compatível: Ubuntu 22.04 LTS / 24.04 LTS / 26.04 LTS (Focal, Jammy, Noble)
# =============================================================================
set -euo pipefail

# --- Cores e helpers ---------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
die()     { echo -e "${RED}[ERRO]${NC} $*" >&2; exit 1; }

# =============================================================================
# 0. VERIFICAÇÕES INICIAIS
# =============================================================================
info "============================================================"
info " PGA Kriging GIS — Provisionamento Automatizado"
info " $(date '+%Y-%m-%d %H:%M:%S')"
info "============================================================"

[[ $EUID -ne 0 ]] && die "Este script deve ser executado como root (sudo ./setup.sh)."

# Detectar diretório raiz do projeto (mesmo dir do script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"
info "Diretório do projeto: ${PROJECT_DIR}"

# Detectar usuário proprietário do projeto (quem criou o diretório)
PROJECT_OWNER="$(stat -c '%U' "${PROJECT_DIR}")"
PROJECT_GROUP="$(stat -c '%G' "${PROJECT_DIR}")"
info "Proprietário do projeto: ${PROJECT_OWNER}:${PROJECT_GROUP}"

# =============================================================================
# 1. ATUALIZAÇÃO DO SISTEMA
# =============================================================================
info "Atualizando índice de pacotes APT..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
success "APT atualizado."

# =============================================================================
# 2. INSTALAÇÃO DE DEPENDÊNCIAS DO SISTEMA
# =============================================================================
info "Instalando dependências do sistema (PostGIS, Python, Nginx, UFW)..."

# Lista de pacotes necessários
PKGS=(
    python3-venv
    python3-dev
    python3-pip
    libpq-dev
    build-essential
    gcc
    postgresql
    postgresql-contrib
    postgis
    nginx
    ufw
    curl
    git
)

# Instalar apenas os que não estiverem presentes (idempotência)
for pkg in "${PKGS[@]}"; do
    if ! dpkg -l "$pkg" 2>/dev/null | grep -q '^ii'; then
        apt-get install -y -qq "$pkg"
    fi
done
success "Dependências do sistema instaladas."

# =============================================================================
# 3. CONFIGURAÇÃO DO POSTGRESQL + POSTGIS
# =============================================================================
info "Configurando PostgreSQL e habilitando PostGIS..."

systemctl enable --now postgresql
sleep 2  # aguarda socket ficar disponível

# Detectar versão do PostgreSQL instalada
PG_VERSION=$(pg_lsclusters -h | head -1 | awk '{print $1}')
info "PostgreSQL versão detectada: ${PG_VERSION}"

# Senha do banco: usa variável de ambiente ou gera uma nova aleatória segura
if [[ -z "${PGA_DB_PASSWORD:-}" ]]; then
    PGA_DB_PASSWORD="$(python3 -c 'import secrets, string; \
        chars=string.ascii_letters+string.digits; \
        print("".join(secrets.choice(chars) for _ in range(32)))')"
    warn "PGA_DB_PASSWORD não definida. Senha gerada automaticamente."
fi
info "Senha do banco de dados configurada."

# Verificar/criar role pga_app (idempotente)
ROLE_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='pga_app'" 2>/dev/null || echo "")
if [[ -z "$ROLE_EXISTS" ]]; then
    sudo -u postgres psql -c "CREATE ROLE pga_app WITH LOGIN PASSWORD '${PGA_DB_PASSWORD}';"
    success "Role pga_app criada."
else
    sudo -u postgres psql -c "ALTER ROLE pga_app WITH PASSWORD '${PGA_DB_PASSWORD}';"
    success "Role pga_app já existe — senha atualizada."
fi

# Verificar/criar banco pga_db (idempotente)
DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='pga_db'" 2>/dev/null || echo "")
if [[ -z "$DB_EXISTS" ]]; then
    sudo -u postgres createdb -O pga_app pga_db
    success "Banco pga_db criado."
else
    success "Banco pga_db já existe."
fi

# Ativar extensão PostGIS e conceder privilégios (idempotente)
sudo -u postgres psql -d pga_db -c "CREATE EXTENSION IF NOT EXISTS postgis;"
sudo -u postgres psql -d pga_db -c "CREATE EXTENSION IF NOT EXISTS postgis_topology;" 2>/dev/null || true
sudo -u postgres psql -d pga_db -c "GRANT ALL PRIVILEGES ON DATABASE pga_db TO pga_app;"
sudo -u postgres psql -d pga_db -c "GRANT ALL ON SCHEMA public TO pga_app;"
sudo -u postgres psql -d pga_db -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO pga_app;"
sudo -u postgres psql -d pga_db -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO pga_app;"
success "PostGIS ativado e privilégios concedidos."

# =============================================================================
# 4. AMBIENTE VIRTUAL PYTHON (venv) E DEPENDÊNCIAS
# =============================================================================
VENV_DIR="${PROJECT_DIR}/venv"
info "Configurando ambiente virtual Python em ${VENV_DIR}..."

if [[ ! -d "${VENV_DIR}" ]]; then
    sudo -u "${PROJECT_OWNER}" python3 -m venv "${VENV_DIR}"
    success "venv criado."
else
    success "venv já existe."
fi

# Atualizar pip e instalar dependências
sudo -u "${PROJECT_OWNER}" "${VENV_DIR}/bin/pip" install --quiet --upgrade pip setuptools wheel
sudo -u "${PROJECT_OWNER}" "${VENV_DIR}/bin/pip" install --quiet -r "${PROJECT_DIR}/requirements.txt"

# Garantir gunicorn instalado
sudo -u "${PROJECT_OWNER}" "${VENV_DIR}/bin/pip" install --quiet gunicorn
success "Dependências Python instaladas (incluindo gunicorn)."

# =============================================================================
# 5. GERAÇÃO AUTOMÁTICA DO ARQUIVO .env SEGURO
# =============================================================================
ENV_FILE="${PROJECT_DIR}/.env"

# Encode de caracteres especiais na URL do banco
PGA_DB_PASSWORD_URL_ENCODED="$(python3 -c "import urllib.parse; print(urllib.parse.quote('${PGA_DB_PASSWORD}', safe=''))")"

if [[ ! -f "${ENV_FILE}" ]]; then
    info "Gerando .env seguro com chave criptográfica nova..."
    NEW_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    cat > "${ENV_FILE}" <<EOF
# Configuração de Segurança — PGA Kriging GIS
# Gerado automaticamente por setup.sh em $(date '+%Y-%m-%d %H:%M:%S')
# NÃO VERSIONEIE ESTE ARQUIVO. Veja .gitignore.

SECRET_KEY=${NEW_SECRET_KEY}
DATABASE_URL=postgresql+psycopg://pga_app:${PGA_DB_PASSWORD_URL_ENCODED}@localhost:5432/pga_db

FLASK_HOST=127.0.0.1
FLASK_PORT=5000
FLASK_DEBUG=false
WTF_CSRF_ENABLED=true
EOF
    chown "${PROJECT_OWNER}:${PROJECT_GROUP}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    success ".env gerado com SECRET_KEY aleatória e permissão 600."
else
    # Atualizar apenas a senha do banco no .env existente
    warn ".env já existe — atualizando DATABASE_URL com a nova senha..."
    sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg://pga_app:${PGA_DB_PASSWORD_URL_ENCODED}@localhost:5432/pga_db|" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    success ".env atualizado."
fi

# =============================================================================
# 6. INICIALIZAÇÃO DAS TABELAS E CARGA INICIAL
# =============================================================================
info "Inicializando tabelas do PostGIS e carregando dados iniciais..."

INIT_SCRIPT="${PROJECT_DIR}/_setup_init.py"
cat > "${INIT_SCRIPT}" <<'PYEOF'
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import create_app, db
from app.services.data_importer import DataImporterService

app = create_app()
with app.app_context():
    db.create_all()
    print("[OK] Tabelas criadas/verificadas no PostGIS.")

    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "estacoes_pga_brasil_completo.csv")
    if os.path.exists(csv_path):
        result = DataImporterService.import_local_file(csv_path)
        print(f"[OK] Dataset Brasil carregado: {result['processados']} estações.")
        if result.get('rejeitados', 0) > 0:
            print(f"[WARN] {result['rejeitados']} estações rejeitadas: {result.get('erros', [])[:3]}")
    else:
        print(f"[WARN] Dataset não encontrado em: {csv_path}")
        print("[WARN] Execute manualmente: POST /api/estacoes/seed-brasil")
PYEOF

chown "${PROJECT_OWNER}:${PROJECT_GROUP}" "${INIT_SCRIPT}"

cd "${PROJECT_DIR}"
sudo -u "${PROJECT_OWNER}" "${VENV_DIR}/bin/python" "${INIT_SCRIPT}"
rm -f "${INIT_SCRIPT}"
success "Tabelas e dados iniciais configurados."

# =============================================================================
# 7. SERVIÇO SYSTEMD (GUNICORN)
# =============================================================================
SERVICE_FILE="/etc/systemd/system/pga-kriging.service"
info "Configurando serviço systemd pga-kriging (Gunicorn)..."

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=PGA Kriging GIS — Interpolação Sísmica Flask/Gunicorn
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=exec
User=${PROJECT_OWNER}
Group=${PROJECT_GROUP}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/gunicorn \\
    --workers 3 \\
    --worker-class sync \\
    --bind 127.0.0.1:8000 \\
    --timeout 120 \\
    --access-logfile ${PROJECT_DIR}/logs/gunicorn_access.log \\
    --error-logfile ${PROJECT_DIR}/logs/gunicorn_error.log \\
    --log-level warning \\
    "run:app"
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=on-failure
RestartSec=5s
KillMode=mixed
TimeoutStopSec=10

# Hardening de Segurança
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# Criar diretório de logs
mkdir -p "${PROJECT_DIR}/logs"
chown "${PROJECT_OWNER}:${PROJECT_GROUP}" "${PROJECT_DIR}/logs"

systemctl daemon-reload
systemctl enable pga-kriging
systemctl restart pga-kriging
sleep 3

if systemctl is-active --quiet pga-kriging; then
    success "Serviço pga-kriging ativo e rodando (Gunicorn na porta 8000)."
else
    warn "Serviço pga-kriging não está ativo. Verifique: journalctl -u pga-kriging -n 50"
fi

# =============================================================================
# 8. PROXY REVERSO NGINX
# =============================================================================
NGINX_CONF="/etc/nginx/sites-available/pga-kriging"
info "Configurando Nginx como proxy reverso (porta 80 → 127.0.0.1:8000)..."

cat > "${NGINX_CONF}" <<'EOF'
# =============================================================
# PGA Kriging GIS — Configuração Nginx (Proxy Reverso Seguro)
# =============================================================
server {
    listen 80;
    listen [::]:80;
    server_name _;

    # Tamanho máximo de upload (alinhado ao Flask MAX_CONTENT_LENGTH)
    client_max_body_size 5M;

    # Logs
    access_log /var/log/nginx/pga-kriging-access.log;
    error_log  /var/log/nginx/pga-kriging-error.log warn;

    # --- Security Headers ---
    add_header X-Content-Type-Options    "nosniff"                     always;
    add_header X-Frame-Options           "SAMEORIGIN"                  always;
    add_header X-XSS-Protection          "1; mode=block"               always;
    add_header Referrer-Policy           "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy        "geolocation=(), microphone=()" always;

    # --- Proxy para Gunicorn ---
    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;
        proxy_send_timeout 60s;

        # Buffer para respostas GeoJSON grandes
        proxy_buffering    on;
        proxy_buffer_size  16k;
        proxy_buffers      8 32k;
    }

    # --- Cache para assets estáticos ---
    location /static/ {
        proxy_pass http://127.0.0.1:8000/static/;
        expires    7d;
        add_header Cache-Control "public, immutable";
    }

    # --- Health check endpoint ---
    location /health {
        return 200 'pga-kriging-gis OK';
        add_header Content-Type text/plain;
    }

    # --- Bloquear acesso a arquivos sensíveis ---
    location ~ /\. {
        deny all;
        return 404;
    }
}
EOF

# Ativar site e desativar default (idempotente)
ln -sf "${NGINX_CONF}" /etc/nginx/sites-enabled/pga-kriging
[[ -f /etc/nginx/sites-enabled/default ]] && rm -f /etc/nginx/sites-enabled/default || true

# Testar configuração e recarregar
nginx -t 2>&1 && systemctl enable --now nginx && systemctl reload nginx
success "Nginx configurado e recarregado."

# =============================================================================
# 9. FIREWALL UFW
# =============================================================================
info "Configurando firewall UFW (SSH + HTTP/HTTPS, PostgreSQL bloqueado)..."

ufw --force reset 2>/dev/null || true
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
success "UFW ativo: SSH e Nginx (80/443) permitidos. PostgreSQL (5432) bloqueado externamente."

# =============================================================================
# 10. SUMÁRIO FINAL
# =============================================================================
INSTANCE_IP=$(hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  PGA Kriging GIS — PROVISIONAMENTO CONCLUÍDO!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo -e "  ${CYAN}URL da Aplicação:${NC}  http://${INSTANCE_IP}/"
echo -e "  ${CYAN}Usuário do Banco:${NC}  pga_app @ pga_db (localhost:5432)"
echo -e "  ${CYAN}Serviço systemd:${NC}   pga-kriging (Gunicorn x3 workers)"
echo -e "  ${CYAN}Logs Gunicorn:${NC}     ${PROJECT_DIR}/logs/"
echo -e "  ${CYAN}Logs Nginx:${NC}        /var/log/nginx/pga-kriging-*.log"
echo -e "  ${CYAN}Env Seguro:${NC}        ${ENV_FILE} (chmod 600)"
echo ""
echo -e "  ${YELLOW}Comandos úteis:${NC}"
echo -e "    sudo systemctl status pga-kriging"
echo -e "    sudo journalctl -u pga-kriging -f"
echo -e "    sudo nginx -t && sudo systemctl reload nginx"
echo -e "    sudo ufw status verbose"
echo -e "${GREEN}============================================================${NC}"
