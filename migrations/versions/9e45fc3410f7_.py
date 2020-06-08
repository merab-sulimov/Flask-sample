"""empty message

Revision ID: 9e45fc3410f7
Revises: ae958fae3c6e
Create Date: 2017-08-08 15:11:13.307538

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9e45fc3410f7'
down_revision = 'ae958fae3c6e'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('enquiries', sa.Column('created_on', sa.DateTime(), nullable=True))
    op.add_column('enquiries', sa.Column('response_on', sa.DateTime(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('enquiries', 'response_on')
    op.drop_column('enquiries', 'created_on')
    # ### end Alembic commands ###
