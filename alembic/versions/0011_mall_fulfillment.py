"""Order snapshots and separately persisted notification facts."""
from alembic import op
revision = "0011_mall_fulfillment"
down_revision = "0010_activity_publications"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''ALTER TABLE bot.points_mall_orders
        ADD COLUMN IF NOT EXISTS product_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN IF NOT EXISTS fulfiller_user_id bigint NULL,
        ADD COLUMN IF NOT EXISTS assignment_version integer NOT NULL DEFAULT 1,
        ADD COLUMN IF NOT EXISTS fulfillment_note text NULL,
        ADD COLUMN IF NOT EXISTS fulfilled_at timestamptz NULL''')
    # Historical facts must not be invented. Name/description are a migration-time snapshot.
    op.execute('''UPDATE bot.points_mall_orders o SET product_snapshot =
        jsonb_build_object('name', p.name, 'description', p.description,
                          'price_points', o.price_points, 'snapshot_source', 'migration')
        FROM bot.points_mall_products p WHERE p.product_id = o.product_id AND o.product_snapshot = '{}'::jsonb''')
    op.execute('''DO $$ DECLARE fk record; BEGIN
        FOR fk IN SELECT conname FROM pg_constraint WHERE conrelid='bot.points_mall_orders'::regclass
            AND confrelid='bot.points_mall_products'::regclass AND contype='f'
        LOOP EXECUTE format('ALTER TABLE bot.points_mall_orders DROP CONSTRAINT %I', fk.conname); END LOOP;
        ALTER TABLE bot.points_mall_orders ADD CONSTRAINT points_mall_orders_product_id_fkey
            FOREIGN KEY(product_id) REFERENCES bot.points_mall_products(product_id) ON DELETE RESTRICT;
    END $$''')
    op.execute('''CREATE TABLE IF NOT EXISTS bot.mall_notifications (
        id serial PRIMARY KEY,
        order_id integer NOT NULL REFERENCES bot.points_mall_orders(order_id) ON DELETE CASCADE,
        recipient_id bigint NOT NULL, role varchar(16) NOT NULL, assignment_version integer NOT NULL,
        status varchar(32) NOT NULL, attempts integer NOT NULL,
        next_retry_at timestamptz NULL, message_id bigint NULL, last_error text NULL,
        updated_at timestamptz NOT NULL,
        CONSTRAINT uq_mall_notification_target UNIQUE(order_id, role, assignment_version)
    )''')


def downgrade():
    raise RuntimeError("Keep orders, assignments, and notification facts during rollback.")
