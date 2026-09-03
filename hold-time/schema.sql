DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS items;

CREATE TABLE items (
  id      integer PRIMARY KEY,
  stock   integer NOT NULL,
  version bigint  NOT NULL DEFAULT 0
);

CREATE TABLE orders (
  id         bigserial PRIMARY KEY,
  item_id    integer NOT NULL,
  worker     bigint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
