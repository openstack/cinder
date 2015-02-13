CREATE TABLE encryption_v32 (
    created_at DATETIME,
    updated_at DATETIME,
    deleted_at DATETIME,
    deleted BOOLEAN,
    cipher VARCHAR(255),
    control_location VARCHAR(255),
    key_size INTEGER,
    provider VARCHAR(255),
    volume_type_id VARCHAR(36),
    PRIMARY KEY (volume_type_id),
    FOREIGN KEY(volume_type_id) REFERENCES volume_types(id)
);

INSERT INTO encryption_v32
    SELECT created_at,
        updated_at,
        deleted_at,
        deleted,
        cipher,
        control_location,
        key_size,
        provider,
        volume_type_id
    FROM encryption;

DROP TABLE encryption;
ALTER TABLE encryption_v32 RENAME TO encryption;
