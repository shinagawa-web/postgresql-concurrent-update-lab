DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS items;

CREATE TABLE items (
  id    integer PRIMARY KEY,
  stock integer NOT NULL
);

CREATE TABLE orders (
  id         bigserial PRIMARY KEY,
  item_id    integer NOT NULL,
  worker     bigint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
