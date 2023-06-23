{
    "backups": [
         {
            "id": "%(uuid)s",
            "links": [{
                "href": "%(host)s/v3/%(id)s/backups/%(uuid)s",
                "rel": "self"
            }, {
                "href": "%(host)s/%(id)s/backups/%(uuid)s",
                "rel": "bookmark"
            }],
            "name": "backup001"
        }
    ],
    "count": %(int)s
}