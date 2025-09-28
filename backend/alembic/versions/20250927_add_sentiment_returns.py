"""Add sentiment returns table

Revision ID: 20250927_add_sentiment_returns
Revises: af9c5a328261
Create Date: 2025-09-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = '20250927_add_sentiment_returns'
down_revision = 'af9c5a328261'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('sentiment_returns',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('headline_id', UUID(as_uuid=True), nullable=False),
        
        # Sentiment information
        sa.Column('sentiment_value', sa.Integer(), nullable=False),
        sa.Column('sentiment_confidence', sa.Float(), nullable=False),
        
        # Returns over different timeframes
        sa.Column('return_3h', sa.Float(), nullable=True),
        sa.Column('return_24h', sa.Float(), nullable=True),
        sa.Column('return_next_day', sa.Float(), nullable=True),
        sa.Column('return_2d', sa.Float(), nullable=True),
        sa.Column('return_3d', sa.Float(), nullable=True),
        sa.Column('return_prev_1d', sa.Float(), nullable=True),
        sa.Column('return_prev_2d', sa.Float(), nullable=True),
        
        # Price data points
        sa.Column('price_at_sentiment', sa.Float(), nullable=False),
        sa.Column('price_3h', sa.Float(), nullable=True),
        sa.Column('price_24h', sa.Float(), nullable=True),
        sa.Column('price_next_day', sa.Float(), nullable=True),
        sa.Column('price_2d', sa.Float(), nullable=True),
        sa.Column('price_3d', sa.Float(), nullable=True),
        sa.Column('price_prev_1d', sa.Float(), nullable=True),
        sa.Column('price_prev_2d', sa.Float(), nullable=True),
        
        # Timestamps for each price point
        sa.Column('timestamp_at_sentiment', sa.DateTime(timezone=True), nullable=False),
        sa.Column('timestamp_3h', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timestamp_24h', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timestamp_next_day', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timestamp_2d', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timestamp_3d', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timestamp_prev_1d', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timestamp_prev_2d', sa.DateTime(timezone=True), nullable=True),
        
        # Metadata
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['headline_id'], ['headlines.id'], ),
        sa.CheckConstraint('sentiment_value IN (-1, 0, 1)', name='check_sentiment_returns_value'),
        sa.CheckConstraint('sentiment_confidence >= 0 AND sentiment_confidence <= 1', name='check_sentiment_returns_confidence'),
    )
    
    # Create indexes
    op.create_index('idx_sentiment_returns_headline', 'sentiment_returns', ['headline_id'])
    op.create_index('idx_sentiment_returns_sentiment', 'sentiment_returns', ['sentiment_value', 'sentiment_confidence'])


def downgrade() -> None:
    op.drop_index('idx_sentiment_returns_sentiment', table_name='sentiment_returns')
    op.drop_index('idx_sentiment_returns_headline', table_name='sentiment_returns')
    op.drop_table('sentiment_returns')
