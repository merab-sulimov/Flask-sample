"""empty message

Revision ID: ffdfd2c285e2
Revises: a956667663e0
Create Date: 2017-12-07 15:30:47.024517

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ffdfd2c285e2'
down_revision = 'a956667663e0'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('orders', sa.Column('revision_count_left', sa.Integer(), nullable=True))
    op.add_column('products', sa.Column('revision_count', sa.Integer(), nullable=False))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('products', 'revision_count')
    op.drop_column('orders', 'revision_count_left')
    # ### end Alembic commands ###
