CREATE TABLE IF NOT EXISTS items (
  id    integer PRIMARY KEY,
  stock integer NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
  id         bigserial PRIMARY KEY,
  item_id    integer NOT NULL,
  worker     integer NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
