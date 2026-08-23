"""Initial evidence, master-data, intelligence and governance schema.

This revision is deliberately self-contained. Historical migrations must not
import live ORM metadata because later model changes would alter fresh installs.
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Frozen baseline generated from the reviewed pilot schema.
    op.create_table('audit_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=True),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('actor_type', sa.String(length=50), nullable=False),
    sa.Column('actor_reference', sa.String(length=180), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('metadata_json', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_events_company_id'), 'audit_events', ['company_id'], unique=False)
    op.create_table('companies',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('inbound_message_receipts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=True),
    sa.Column('provider_message_id', sa.String(length=180), nullable=False),
    sa.Column('disposition', sa.String(length=40), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider_message_id')
    )
    op.create_index(op.f('ix_inbound_message_receipts_company_id'), 'inbound_message_receipts', ['company_id'], unique=False)
    op.create_table('ai_operations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('task_type', sa.String(length=80), nullable=False),
    sa.Column('quality_tier', sa.String(length=30), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('prompt_version', sa.String(length=40), nullable=False),
    sa.Column('schema_version', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('estimated_cost_usd', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('error_code', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_operations_company_id'), 'ai_operations', ['company_id'], unique=False)
    op.create_table('employees',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('employee_code', sa.String(length=80), nullable=False),
    sa.Column('employment_type', sa.Enum('FULL_TIME', 'CONTRACTUAL', name='employmenttype', native_enum=False), nullable=False),
    sa.Column('designation', sa.String(length=160), nullable=True),
    sa.Column('territory_code', sa.String(length=100), nullable=True),
    sa.Column('state', sa.String(length=100), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('whatsapp_number', sa.String(length=20), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'employee_code', name='uq_employee_code_company'),
    sa.UniqueConstraint('company_id', 'whatsapp_number', name='uq_employee_whatsapp_company')
    )
    op.create_index(op.f('ix_employees_company_id'), 'employees', ['company_id'], unique=False)
    op.create_table('political_nodes',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('level', sa.String(length=30), nullable=False),
    sa.Column('parent_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['political_nodes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'code', name='uq_political_code_company')
    )
    op.create_index(op.f('ix_political_nodes_company_id'), 'political_nodes', ['company_id'], unique=False)
    op.create_table('products',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('ownership', sa.Enum('OWN', 'COMPETITOR', name='productownership', native_enum=False), nullable=False),
    sa.Column('manufacturer', sa.String(length=200), nullable=True),
    sa.Column('brand', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=False),
    sa.Column('active_ingredient', sa.String(length=240), nullable=True),
    sa.Column('formulation', sa.String(length=160), nullable=True),
    sa.Column('concentration', sa.String(length=100), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'ownership', 'brand', name='uq_product_brand_owner')
    )
    op.create_index(op.f('ix_products_company_id'), 'products', ['company_id'], unique=False)
    op.create_table('retention_policies',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('data_type', sa.String(length=60), nullable=False),
    sa.Column('retention_days', sa.Integer(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'data_type', name='uq_retention_type_company')
    )
    op.create_index(op.f('ix_retention_policies_company_id'), 'retention_policies', ['company_id'], unique=False)
    op.create_table('sales_org_nodes',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('level', sa.String(length=30), nullable=False),
    sa.Column('parent_id', sa.String(length=36), nullable=True),
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['sales_org_nodes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'code', 'effective_from', name='uq_soh_version')
    )
    op.create_index(op.f('ix_sales_org_nodes_company_id'), 'sales_org_nodes', ['company_id'], unique=False)
    op.create_table('signals',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('state', sa.String(length=100), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=False),
    sa.Column('subject_key', sa.String(length=300), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('strength', sa.Enum('WEAK', 'STRONG', name='signalstrength', native_enum=False), nullable=False),
    sa.Column('distinct_employee_count', sa.Integer(), nullable=False),
    sa.Column('distinct_conversation_count', sa.Integer(), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'state', 'category', 'subject_key', name='uq_signal_scope')
    )
    op.create_index(op.f('ix_signals_company_id'), 'signals', ['company_id'], unique=False)
    op.create_table('whatsapp_channels',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('phone_number_id', sa.String(length=80), nullable=False),
    sa.Column('display_phone_number', sa.String(length=32), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('phone_number_id')
    )
    op.create_index(op.f('ix_whatsapp_channels_company_id'), 'whatsapp_channels', ['company_id'], unique=False)
    op.create_table('competition_prices',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('product_id', sa.String(length=36), nullable=False),
    sa.Column('state', sa.String(length=100), nullable=False),
    sa.Column('pack_size', sa.String(length=80), nullable=False),
    sa.Column('price_type', sa.Enum('FARMER', 'CHANNEL_NET_LANDING', name='pricetype', native_enum=False), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source', sa.String(length=30), nullable=False),
    sa.Column('signal_id', sa.String(length=36), nullable=True),
    sa.Column('evidence_ids', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.ForeignKeyConstraint(['signal_id'], ['signals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_competition_prices_company_id'), 'competition_prices', ['company_id'], unique=False)
    op.create_index('ix_price_current_lookup', 'competition_prices', ['company_id', 'product_id', 'state', 'pack_size', 'price_type'], unique=False)
    op.create_table('field_conversations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('employee_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.Enum('OPEN', 'CLOSED', name='conversationstatus', native_enum=False), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('close_reason', sa.String(length=40), nullable=True),
    sa.Column('employee_context', sa.JSON(), nullable=False),
    sa.Column('analysis_status', sa.String(length=30), nullable=False),
    sa.Column('analysis_error_code', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_field_conversations_company_id'), 'field_conversations', ['company_id'], unique=False)
    op.create_index('ix_open_conversation_lookup', 'field_conversations', ['company_id', 'employee_id', 'status'], unique=False)
    op.create_table('outbound_messages',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('channel_id', sa.String(length=36), nullable=False),
    sa.Column('recipient_wa_id', sa.String(length=20), nullable=False),
    sa.Column('message_kind', sa.String(length=40), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error_code', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['channel_id'], ['whatsapp_channels.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_outbound_messages_company_id'), 'outbound_messages', ['company_id'], unique=False)
    op.create_table('product_aliases',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('product_id', sa.String(length=36), nullable=False),
    sa.Column('alias', sa.String(length=240), nullable=False),
    sa.Column('normalized_alias', sa.String(length=240), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'normalized_alias', name='uq_product_alias_company')
    )
    op.create_index(op.f('ix_product_aliases_company_id'), 'product_aliases', ['company_id'], unique=False)
    op.create_table('sales_political_mappings',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('sales_org_node_id', sa.String(length=36), nullable=False),
    sa.Column('subdistrict_id', sa.String(length=36), nullable=False),
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['sales_org_node_id'], ['sales_org_nodes.id'], ),
    sa.ForeignKeyConstraint(['subdistrict_id'], ['political_nodes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sales_political_mappings_company_id'), 'sales_political_mappings', ['company_id'], unique=False)
    op.create_table('field_messages',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('employee_id', sa.String(length=36), nullable=False),
    sa.Column('provider_message_id', sa.String(length=180), nullable=False),
    sa.Column('message_type', sa.Enum('TEXT', 'AUDIO', 'IMAGE', 'DOCUMENT', 'LOCATION', 'UNSUPPORTED', name='messagetype', native_enum=False), nullable=False),
    sa.Column('text_content', sa.Text(), nullable=True),
    sa.Column('derived_text', sa.Text(), nullable=True),
    sa.Column('provider_media_id', sa.String(length=180), nullable=True),
    sa.Column('provider_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('raw_payload', sa.JSON(), nullable=False),
    sa.Column('processing_status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['conversation_id'], ['field_conversations.id'], ),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider_message_id')
    )
    op.create_index(op.f('ix_field_messages_company_id'), 'field_messages', ['company_id'], unique=False)
    op.create_index(op.f('ix_field_messages_conversation_id'), 'field_messages', ['conversation_id'], unique=False)
    op.create_table('observations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('employee_id', sa.String(length=36), nullable=False),
    sa.Column('state', sa.String(length=100), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=False),
    sa.Column('subject_key', sa.String(length=300), nullable=False),
    sa.Column('claim', sa.Text(), nullable=False),
    sa.Column('structured_data', sa.JSON(), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('source_message_ids', sa.JSON(), nullable=False),
    sa.Column('review_status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['conversation_id'], ['field_conversations.id'], ),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_observations_company_id'), 'observations', ['company_id'], unique=False)
    op.create_table('media_assets',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('message_id', sa.String(length=36), nullable=False),
    sa.Column('provider_media_id', sa.String(length=180), nullable=False),
    sa.Column('object_key', sa.String(length=600), nullable=True),
    sa.Column('mime_type', sa.String(length=120), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('scan_status', sa.String(length=30), nullable=False),
    sa.Column('analysis_status', sa.String(length=30), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error_code', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['message_id'], ['field_messages.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_media_assets_company_id'), 'media_assets', ['company_id'], unique=False)
    op.create_table('signal_evidence',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('company_id', sa.String(length=36), nullable=False),
    sa.Column('signal_id', sa.String(length=36), nullable=False),
    sa.Column('observation_id', sa.String(length=36), nullable=False),
    sa.Column('employee_id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['conversation_id'], ['field_conversations.id'], ),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ),
    sa.ForeignKeyConstraint(['observation_id'], ['observations.id'], ),
    sa.ForeignKeyConstraint(['signal_id'], ['signals.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('signal_id', 'observation_id', name='uq_signal_observation')
    )
    op.create_index(op.f('ix_signal_evidence_company_id'), 'signal_evidence', ['company_id'], unique=False)


def downgrade() -> None:
    # Drop in reverse dependency order.
    op.drop_index(op.f('ix_signal_evidence_company_id'), table_name='signal_evidence')
    op.drop_table('signal_evidence')
    op.drop_index(op.f('ix_media_assets_company_id'), table_name='media_assets')
    op.drop_table('media_assets')
    op.drop_index(op.f('ix_observations_company_id'), table_name='observations')
    op.drop_table('observations')
    op.drop_index(op.f('ix_field_messages_conversation_id'), table_name='field_messages')
    op.drop_index(op.f('ix_field_messages_company_id'), table_name='field_messages')
    op.drop_table('field_messages')
    op.drop_index(op.f('ix_sales_political_mappings_company_id'), table_name='sales_political_mappings')
    op.drop_table('sales_political_mappings')
    op.drop_index(op.f('ix_product_aliases_company_id'), table_name='product_aliases')
    op.drop_table('product_aliases')
    op.drop_index(op.f('ix_outbound_messages_company_id'), table_name='outbound_messages')
    op.drop_table('outbound_messages')
    op.drop_index('ix_open_conversation_lookup', table_name='field_conversations')
    op.drop_index(op.f('ix_field_conversations_company_id'), table_name='field_conversations')
    op.drop_table('field_conversations')
    op.drop_index('ix_price_current_lookup', table_name='competition_prices')
    op.drop_index(op.f('ix_competition_prices_company_id'), table_name='competition_prices')
    op.drop_table('competition_prices')
    op.drop_index(op.f('ix_whatsapp_channels_company_id'), table_name='whatsapp_channels')
    op.drop_table('whatsapp_channels')
    op.drop_index(op.f('ix_signals_company_id'), table_name='signals')
    op.drop_table('signals')
    op.drop_index(op.f('ix_sales_org_nodes_company_id'), table_name='sales_org_nodes')
    op.drop_table('sales_org_nodes')
    op.drop_index(op.f('ix_retention_policies_company_id'), table_name='retention_policies')
    op.drop_table('retention_policies')
    op.drop_index(op.f('ix_products_company_id'), table_name='products')
    op.drop_table('products')
    op.drop_index(op.f('ix_political_nodes_company_id'), table_name='political_nodes')
    op.drop_table('political_nodes')
    op.drop_index(op.f('ix_employees_company_id'), table_name='employees')
    op.drop_table('employees')
    op.drop_index(op.f('ix_ai_operations_company_id'), table_name='ai_operations')
    op.drop_table('ai_operations')
    op.drop_index(op.f('ix_inbound_message_receipts_company_id'), table_name='inbound_message_receipts')
    op.drop_table('inbound_message_receipts')
    op.drop_table('companies')
    op.drop_index(op.f('ix_audit_events_company_id'), table_name='audit_events')
    op.drop_table('audit_events')
