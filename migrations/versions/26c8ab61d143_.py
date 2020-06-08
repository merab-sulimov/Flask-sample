"""empty message

Revision ID: 26c8ab61d143
Revises: b46a8b8aed62
Create Date: 2017-07-17 12:31:43.907705

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '26c8ab61d143'
down_revision = 'b46a8b8aed62'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('products', sa.Column('not_approved', sa.Boolean(), nullable=False))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('products', 'not_approved')
    # ### end Alembic commands ###
