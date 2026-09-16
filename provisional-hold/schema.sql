DROP TABLE IF EXISTS holds;
DROP TABLE IF EXISTS inventory;

CREATE TABLE inventory (
  product_id BIGINT PRIMARY KEY,
  stock      INT NOT NULL CHECK (stock >= 0)
);

CREATE TABLE holds (
  hold_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id BIGINT NOT NULL REFERENCES inventory,
  user_id    BIGINT NOT NULL,
  quantity   INT NOT NULL CHECK (quantity > 0),
  status     TEXT NOT NULL DEFAULT 'reserved'
               CHECK (status IN ('reserved', 'paying', 'confirmed', 'expired')),
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX ON holds (expires_at) WHERE status = 'reserved';
