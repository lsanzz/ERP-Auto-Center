"""Expand company profile and Focus NFe certificate metadata for MySQL."""
from alembic import op
import sqlalchemy as sa


revision = '20260907_05'
down_revision = '20260906_04'
branch_labels = None
depends_on = None


PROFILE_COLUMNS = (
    ('person_type', sa.String(20), False, 'JURIDICA'),
    ('state_registration', sa.String(40), True, None),
    ('state_registration_exempt', sa.Boolean(), False, '0'),
    ('municipal_registration', sa.String(40), True, None),
    ('tax_regime', sa.String(20), True, None),
    ('cnae', sa.String(20), True, None),
    ('rntrc', sa.String(30), True, None),
    ('responsible_name', sa.String(160), True, None),
    ('company_size', sa.String(30), True, None),
    ('address_number', sa.String(20), True, None),
    ('neighborhood', sa.String(100), True, None),
    ('address_complement', sa.String(100), True, None),
    ('mobile', sa.String(30), True, None),
    ('website', sa.String(160), True, None),
    ('weekdays_open', sa.Boolean(), False, '1'),
    ('weekdays_from', sa.String(5), False, '08:00'),
    ('weekdays_to', sa.String(5), False, '18:00'),
    ('saturday_open', sa.Boolean(), False, '0'),
    ('saturday_from', sa.String(5), False, '08:00'),
    ('saturday_to', sa.String(5), False, '12:00'),
    ('sunday_open', sa.Boolean(), False, '0'),
    ('sunday_from', sa.String(5), False, '08:00'),
    ('sunday_to', sa.String(5), False, '12:00'),
    ('accountant_name', sa.String(160), True, None),
    ('accountant_cpf', sa.String(20), True, None),
    ('accountant_cnpj', sa.String(20), True, None),
    ('accountant_crc', sa.String(40), True, None),
    ('accountant_email', sa.String(120), True, None),
    ('accountant_phone', sa.String(30), True, None),
    ('accountant_zip_code', sa.String(12), True, None),
    ('accountant_address', sa.String(255), True, None),
    ('accountant_address_number', sa.String(20), True, None),
    ('accountant_neighborhood', sa.String(100), True, None),
    ('accountant_complement', sa.String(100), True, None),
    ('accountant_city', sa.String(100), True, None),
    ('accountant_state', sa.String(2), True, None),
    ('certificate_subject', sa.String(255), True, None),
    ('certificate_serial_number', sa.String(100), True, None),
    ('certificate_expires_at', sa.DateTime(), True, None),
    ('certificate_synced_at', sa.DateTime(), True, None),
)


def upgrade():
    with op.batch_alter_table('system_settings') as batch:
        for name, column_type, nullable, default in PROFILE_COLUMNS:
            batch.add_column(sa.Column(name, column_type, nullable=nullable, server_default=default))
    with op.batch_alter_table('fiscal_api_configs') as batch:
        batch.add_column(sa.Column('focus_company_id', sa.String(80)))
        batch.add_column(sa.Column('focus_management_token', sa.String(255)))
    op.create_table(
        'company_partners',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('system_settings_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(160), nullable=False),
        sa.Column('cpf', sa.String(20)),
        sa.Column('email', sa.String(120)),
        sa.Column('phone', sa.String(30)),
        sa.Column('birth_date', sa.Date()),
        sa.Column('rg', sa.String(30)),
        sa.Column('ownership_percentage', sa.Numeric(5, 2)),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['system_settings_id'], ['system_settings.id'], name='fk_company_partner_settings', ondelete='CASCADE'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4',
    )
    op.create_index('ix_company_partners_system_settings_id', 'company_partners', ['system_settings_id'])


def downgrade():
    op.drop_table('company_partners')
    with op.batch_alter_table('fiscal_api_configs') as batch:
        batch.drop_column('focus_management_token')
        batch.drop_column('focus_company_id')
    with op.batch_alter_table('system_settings') as batch:
        for name, *_ in reversed(PROFILE_COLUMNS):
            batch.drop_column(name)
