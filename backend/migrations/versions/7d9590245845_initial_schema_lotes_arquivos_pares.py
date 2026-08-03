"""initial schema: lotes, arquivos, pares_arquivos

Revision ID: 7d9590245845
Revises: None
Create Date: 2026-08-03 21:20:00.000000

Handoff schema (Seção 12):
  - lotes: agrupamento de uploads (provas + gabaritos)
  - arquivos: metadados de cada arquivo processado
  - pares_arquivos: pareamento prova ↔ gabarito
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision: str = '7d9590245845'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─── Extensão UUID ────────────────────────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ─── Tabela: lotes ────────────────────────────────────────────────────
    op.create_table(
        'lotes',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('origem', sa.Text(), nullable=False, server_default=sa.text("'webhook'")),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'pendente'")),
        sa.Column('criado_por', sa.Text(), nullable=True),
        sa.Column('total_arquivos', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('total_validos', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('total_duplicados', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('total_falhas', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('observacoes', sa.Text(), nullable=True),
        sa.Column('metadata', JSONB(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # Índices lotes
    op.create_index('idx_lotes_status', 'lotes', ['status'])
    op.create_index('idx_lotes_criado_por', 'lotes', ['criado_por'])
    op.create_index('idx_lotes_created_at', 'lotes', ['created_at'])

    # ─── Tabela: arquivos ─────────────────────────────────────────────────
    op.create_table(
        'arquivos',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('lote_id', UUID(as_uuid=True), sa.ForeignKey('lotes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('nome_original', sa.Text(), nullable=False),
        sa.Column('nome_normalizado', sa.Text(), nullable=True),
        sa.Column('mime_type', sa.Text(), nullable=True),
        sa.Column('extensao', sa.Text(), nullable=True),
        sa.Column('tamanho_bytes', sa.Integer(), nullable=True),
        sa.Column('storage_path', sa.Text(), nullable=True),
        sa.Column('hash_arquivo', sa.Text(), nullable=True),
        sa.Column('tipo_arquivo_inicial', sa.Text(), nullable=True),
        sa.Column('confianca_tipo', sa.Float(), nullable=True),
        sa.Column('precisa_ocr', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('formato_suportado', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'pendente'")),
        sa.Column('chave_pareamento', sa.Text(), nullable=True),
        sa.Column('duplicado_de', UUID(as_uuid=True), sa.ForeignKey('arquivos.id', ondelete='SET NULL'), nullable=True),
        sa.Column('observacoes', sa.Text(), nullable=True),
        sa.Column('metadata', JSONB(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # Índices arquivos
    op.create_index('idx_arquivos_lote_id', 'arquivos', ['lote_id'])
    op.create_index('idx_arquivos_hash', 'arquivos', ['hash_arquivo'])
    op.create_index('idx_arquivos_status', 'arquivos', ['status'])
    op.create_index('idx_arquivos_tipo', 'arquivos', ['tipo_arquivo_inicial'])
    op.create_index('idx_arquivos_chave_pareamento', 'arquivos', ['chave_pareamento'])

    # ─── Tabela: pares_arquivos ───────────────────────────────────────────
    op.create_table(
        'pares_arquivos',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('lote_id', UUID(as_uuid=True), sa.ForeignKey('lotes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('arquivo_prova_id', UUID(as_uuid=True), sa.ForeignKey('arquivos.id', ondelete='CASCADE'), nullable=False),
        sa.Column('arquivo_gabarito_id', UUID(as_uuid=True), sa.ForeignKey('arquivos.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chave_pareamento', sa.Text(), nullable=True),
        sa.Column('confianca_pareamento', sa.Float(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'pendente'")),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # Índices pares_arquivos
    op.create_index('idx_pares_lote_id', 'pares_arquivos', ['lote_id'])
    op.create_index('idx_pares_prova_id', 'pares_arquivos', ['arquivo_prova_id'])
    op.create_index('idx_pares_gabarito_id', 'pares_arquivos', ['arquivo_gabarito_id'])
    op.create_index('idx_pares_status', 'pares_arquivos', ['status'])

    # ─── Trigger: updated_at automático ────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    for table in ['lotes', 'arquivos', 'pares_arquivos']:
        op.execute(f"""
            DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    # Remove triggers (in reverse order)
    for table in ['pares_arquivos', 'arquivos', 'lotes']:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")

    op.execute('DROP FUNCTION IF EXISTS update_updated_at_column()')

    # Drop tables (in reverse FK order)
    op.drop_table('pares_arquivos')
    op.drop_table('arquivos')
    op.drop_table('lotes')
