{
    "versions": [
        {
            "status": "DEPRECATED",
            "updated": "%(isotime)s",
            "links": [
                {
                    "href": "https://docs.openstack.org/",
                    "type": "text/html",
                    "rel": "describedby"
                },
                {
                    "href": "%(host)s/v2/",
                    "rel": "self"
                }
            ],
            "min_version": "",
            "version": "",
            "media-types": [
                {
                    "base": "application/json",
                    "type": "application/vnd.openstack.volume+json;version=2"
                }
            ],
            "id": "v2.0"
        },
        {
            "status": "CURRENT",
            "updated": "%(isotime)s",
            "links": [
                {
                    "href": "https://docs.openstack.org/",
                    "type": "text/html",
                    "rel": "describedby"
                },
                {
                    "href": "%(host)s/v3/",
                    "rel": "self"
                }
            ],
            "min_version": "3.0",
            "version": "%(max_api_version)s",
            "media-types": [
                {
                    "base": "application/json",
                    "type": "application/vnd.openstack.volume+json;version=3"
                }
            ],
            "id": "v3.0"
        }
    ]
}
