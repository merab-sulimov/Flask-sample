"""empty message

Revision ID: 8d2f08567020
Revises: 71ff5ee55f21
Create Date: 2017-10-27 14:01:50.977672

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8d2f08567020'
down_revision = '71ff5ee55f21'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('user_verifications',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], onupdate='cascade', ondelete='cascade'),
    sa.PrimaryKeyConstraint('user_id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('user_verifications')
    # ### end Alembic commands ###
