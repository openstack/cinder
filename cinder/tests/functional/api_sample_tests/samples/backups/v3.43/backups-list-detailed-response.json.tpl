{
    "backups": [
        {
            "availability_zone": null,
            "container": null,
            "created_at": "%(strtime)s",
            "data_timestamp": "%(strtime)s",
            "description": "Test backup",
            "fail_reason": null,
            "snapshot_id": null,
            "id": "%(uuid)s",
            "links": [
                {
                    "href": "%(host)s/v3/%(id)s/backups/%(uuid)s",
                    "rel": "self"
                },
                {
                    "href": "%(host)s/%(id)s/backups/%(uuid)s",
                    "rel": "bookmark"
                }
            ],
            "metadata": {},
            "name": "backup001",
            "object_count": %(int)s,
            "os-backup-project-attr:project_id": "%(uuid)s",
            "size": 10,
            "status": "creating",
            "updated_at": "%(strtime)s",
            "volume_id": "%(uuid)s",
            "is_incremental": false,
            "has_dependent_backups": false
        }
    ]
}
