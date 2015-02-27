CREATE TABLE volume_types_v33 (
    created_at DATETIME,
    updated_at DATETIME,
    deleted_at DATETIME,
    deleted BOOLEAN,
    id VARCHAR(36) NOT NULL,
    name VARCHAR(255),
    is_public BOOLEAN,
    qos_specs_id VARCHAR(36),
    PRIMARY KEY (id)
);

INSERT INTO volume_types_v33
    SELECT created_at,
        updated_at,
        deleted_at,
        deleted,
        id,
        name,
        is_public,
        qos_specs_id
    FROM volume_types;

DROP TABLE volume_types;
ALTER TABLE volume_types_v33 RENAME TO volume_types;
