"""empty message

Revision ID: baba93b16da5
Revises: 8d2f08567020
Create Date: 2017-10-27 14:22:32.361412

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'baba93b16da5'
down_revision = '8d2f08567020'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('user_verifications', sa.Column('created_on', sa.DateTime(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('user_verifications', 'created_on')
    # ### end Alembic commands ###
