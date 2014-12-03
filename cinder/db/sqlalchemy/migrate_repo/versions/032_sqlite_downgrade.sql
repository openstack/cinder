-- As sqlite does not support the DROP CHECK, we need to create
-- the table, and move all the data to it.

CREATE TABLE volume_types_v31 (
  created_at DATETIME,
  updated_at DATETIME,
  deleted_at DATETIME,
  deleted BOOLEAN,
  id VARCHAR(36) NOT NULL,
  name VARCHAR(255),
  qos_specs_id VARCHAR(36),
  PRIMARY KEY (id),
  CHECK (deleted IN (0, 1)),
  FOREIGN KEY(qos_specs_id) REFERENCES quality_of_service_specs (id)
);

INSERT INTO volume_types_v31
    SELECT created_at,
        updated_at,
        deleted_at,
        deleted,
        id,
        name,
        qos_specs_id
    FROM volume_types;

DROP TABLE volume_types;
ALTER TABLE volume_types_v31 RENAME TO volume_types;
DROP TABLE volume_type_projects;
