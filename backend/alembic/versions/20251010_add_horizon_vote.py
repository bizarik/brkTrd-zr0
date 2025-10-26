"""add horizon_vote to sentiment_aggregates

Revision ID: 20251010_add_horizon_vote
Revises: 20250927_add_sentiment_returns
Create Date: 2025-10-10 16:40:47

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251010_add_horizon_vote'
down_revision = '20250927_add_sentiment_returns'
branch_labels = None
depends_on = None


def upgrade():
    # Add horizon_vote column to sentiment_aggregates
    op.add_column('sentiment_aggregates', 
        sa.Column('horizon_vote', sa.String(20), nullable=True)
    )
    
    # Backfill existing records by calculating horizon_vote from model_votes
    # This SQL will extract horizons from the JSONB model_votes and find the most common one
    op.execute("""
        UPDATE sentiment_aggregates
        SET horizon_vote = (
            SELECT mode() WITHIN GROUP (ORDER BY horizon)
            FROM (
                SELECT jsonb_array_elements(model_votes)->>'horizon' as horizon
            ) subq
        )
        WHERE model_votes IS NOT NULL
    """)


def downgrade():
    op.drop_column('sentiment_aggregates', 'horizon_vote')

