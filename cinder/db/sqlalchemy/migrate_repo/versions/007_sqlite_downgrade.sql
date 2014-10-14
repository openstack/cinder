-- As sqlite does not support the DROP FOREIGN KEY, we need to create
-- the table, and move all the data to it.

CREATE TABLE snapshots_v6 (
    created_at DATETIME,
    updated_at DATETIME,
    deleted_at DATETIME,
    deleted BOOLEAN,
    id VARCHAR(36) NOT NULL,
    volume_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(255),
    project_id VARCHAR(255),
    status VARCHAR(255),
    progress VARCHAR(255),
    volume_size INTEGER,
    scheduled_at DATETIME,
    display_name VARCHAR(255),
    display_description VARCHAR(255),
    provider_location VARCHAR(255),
    PRIMARY KEY (id),
    CHECK (deleted IN (0, 1))
);

INSERT INTO snapshots_v6 SELECT * FROM snapshots;

DROP TABLE snapshots;

ALTER TABLE snapshots_v6 RENAME TO snapshots;
