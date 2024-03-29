"""empty message

Revision ID: 4cd38c69eae4
Revises: 9e45fc3410f7
Create Date: 2017-08-09 22:16:28.494913

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4cd38c69eae4'
down_revision = '9e45fc3410f7'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('orders', sa.Column('delivery_notification_sent', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('orders', 'delivery_notification_sent')
    # ### end Alembic commands ###
