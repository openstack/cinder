-- As sqlite does not support the DROP CHECK, we need to create
-- the table, and move all the data to it.

CREATE TABLE volume_type_projects_new (
    created_at DATETIME,
    updated_at DATETIME,
    deleted_at DATETIME,
    deleted INTEGER,
    id INTEGER NOT NULL,
    volume_type_id VARCHAR(36),
    project_id VARCHAR(255),
    PRIMARY KEY (id),
    FOREIGN KEY (volume_type_id) REFERENCES volume_types(id),
    CONSTRAINT uniq_volume_type_projects0volume_type_id0project_id0deleted UNIQUE (volume_type_id, project_id, deleted)
);

INSERT INTO volume_type_projects_new
    SELECT created_at,
           updated_at,
           deleted_at,
           deleted,
           id,
           volume_type_id,
           project_id
    FROM volume_type_projects;

DROP TABLE volume_type_projects;

ALTER TABLE volume_type_projects_new RENAME TO volume_type_projects;
