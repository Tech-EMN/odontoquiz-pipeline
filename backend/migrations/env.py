"""
Alembic environment configuration for OdontoQuiz Pipeline.
Lê DATABASE_URL do ambiente (Supabase connection pooler).
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy import create_engine

from alembic import context

# ─── Path setup ────────────────────────────────────────────────────────────
# Garante que backend/src/ esteja no PYTHONPATH para imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

# ─── Alembic Config ─────────────────────────────────────────────────────────
config = context.config

# Interpret config file for logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ─── Database URL ───────────────────────────────────────────────────────────
# Prioridade: DATABASE_URL > SUPABASE_DB_URL > construção via Supabase env vars
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("SUPABASE_DB_URL")
    or None
)

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL não definida. Configure a env var com a URL do pooler do Supabase.\n"
        "Ex: postgresql://postgres.xxx:password@aws-0-region-x.pooler.supabase.com:6543/postgres"
    )

# Inject into alembic's config so %(DATABASE_URL)s resolves
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# ─── Metadata ───────────────────────────────────────────────────────────────
# target_metadata = None (usamos migrations manuais via SQL, não autogenerate)
# Caso queira autogenerate no futuro: crie models com SQLAlchemy declarative_base
target_metadata = None


def run_migrations_offline() -> None:
    """Executa migrations offline (gera SQL sem conectar ao banco)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Executa migrations online (conecta ao banco e aplica)."""
    connectable = create_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
