-- ============================================================
-- Base de Datos de Medicamentos
-- Comparacion de descuentos por drogueria
-- ============================================================
-- Corre esto una sola vez, completo, en el SQL Editor de Neon
-- (o contra una base nueva/vacia).

-- Necesaria para busqueda por texto parecido (similarity(), operador %)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------- Catalogos ----------

CREATE TABLE laboratorios (
    id      SERIAL PRIMARY KEY,
    nombre  VARCHAR(150) NOT NULL UNIQUE
);

CREATE TABLE drogas (
    id      SERIAL PRIMARY KEY,
    nombre  VARCHAR(150) NOT NULL UNIQUE
);

CREATE TABLE droguerias (
    id        SERIAL PRIMARY KEY,
    nombre    VARCHAR(150) NOT NULL UNIQUE,
    contacto  VARCHAR(150)
);

-- ---------- Productos ----------

CREATE TABLE productos (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(200) NOT NULL,
    codigo          VARCHAR(50) UNIQUE,   -- codigo de barra / codigo interno
    troquel         VARCHAR(50) UNIQUE,   -- codigo oficial ANMAT, se completa con el tiempo
    laboratorio_id  INT REFERENCES laboratorios(id),
    droga_id        INT REFERENCES drogas(id)
);

-- indices para busqueda por nombre (parcial e ILIKE), y por las FK
CREATE INDEX idx_productos_nombre_trgm ON productos USING GIN (nombre gin_trgm_ops);
CREATE INDEX idx_productos_laboratorio_id ON productos (laboratorio_id);
CREATE INDEX idx_productos_droga_id ON productos (droga_id);

-- ---------- Descuentos ----------

CREATE TABLE descuentos (
    id                SERIAL PRIMARY KEY,
    drogueria_id      INT NOT NULL REFERENCES droguerias(id),
    nivel_aplicacion  VARCHAR(20) NOT NULL
                      CHECK (nivel_aplicacion IN ('producto', 'droga', 'laboratorio', 'general')),
    referencia_id     INT,  -- id de producto/droga/laboratorio segun nivel_aplicacion; NULL si es 'general'
    porcentaje        NUMERIC(5, 2) NOT NULL,
    fecha_carga       DATE NOT NULL DEFAULT CURRENT_DATE,
    fecha_fin         DATE,
    cantidad_minima   INT CHECK (cantidad_minima > 0)  -- unidades minimas para acceder al porcentaje; NULL = sin minimo
);

CREATE INDEX idx_descuentos_drogueria_id ON descuentos (drogueria_id);
CREATE INDEX idx_descuentos_referencia ON descuentos (nivel_aplicacion, referencia_id);
CREATE INDEX idx_descuentos_fecha_fin ON descuentos (fecha_fin);
