.. -*- rst -*-

Capabilities for storage back ends (capabilities)
=================================================

Shows capabilities for a storage back end.


Show all back-end capabilities
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/capabilities/{hostname}

Shows capabilities for a storage back end on the host.
The ``hostname`` takes the form of ``hostname@volume_backend_name``.

Normal response codes: 200
Error response codes:

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - hostname: hostname

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - pool_name: pool_name
   - description: description
   - volume_backend_name: volume_backend_name
   - namespace: namespace
   - visibility: visibility
   - driver_version: driver_version
   - vendor_name: vendor_name
   - properties: properties
   - storage_protocol: storage_protocol
   - replication_targets: replication_targets
   - display_name: display_name

Response Example
----------------

.. literalinclude:: ./samples/backend-capabilities-response.json
   :language: javascript
