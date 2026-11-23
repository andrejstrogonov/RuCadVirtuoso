CREATE TABLE libraries (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    is_readonly INTEGER DEFAULT 0          -- 1 для PDK, 0 для проектных
);

CREATE TABLE cells (
    id INTEGER PRIMARY KEY,
    lib_id INTEGER REFERENCES libraries(id),
    name TEXT NOT NULL,
    prefix TEXT,                            -- M, R, C, L...
    created_at TEXT,
    UNIQUE(lib_id, name)
);

CREATE TABLE symbol_specs (
    cell_id INTEGER REFERENCES cells(id),
    view TEXT DEFAULT 'symbol',
    json TEXT NOT NULL,                     -- сама спека: примитивы, пины, origin
    content_hash TEXT NOT NULL,             -- sha256(json)
    updated_at TEXT,
    PRIMARY KEY (cell_id, view)
);

CREATE TABLE symbol_assets (
    cell_id INTEGER REFERENCES cells(id),
    view TEXT,
    zoom_level REAL,                        -- кластер зума, если растры
    asset_path TEXT,                        -- symbols/lib/cell.svg на диске
    spec_hash TEXT,                         -- хеш спеки, по которой сгенерирован
    PRIMARY KEY (cell_id, view, zoom_level)
);

CREATE TABLE cdf_params (
    cell_id INTEGER REFERENCES cells(id),
    name TEXT,
    type TEXT,                              -- string, double, int, combo
    default_value TEXT,
    choices TEXT,                           -- JSON для combo
    callback TEXT,
    PRIMARY KEY (cell_id, name)
);
