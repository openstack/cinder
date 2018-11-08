.. -*- rst -*-

Capabilities for storage back ends (capabilities)
=================================================

Shows capabilities for a storage back end.


Show all back-end capabilities
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/capabilities/{hostname}

Shows capabilities for a storage back end on the host.
The ``hostname`` takes the form of ``hostname@volume_backend_name``.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - hostname: hostname

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - pool_name: pool_name
   - description: description_cap
   - volume_backend_name: volume_backend_name
   - namespace: namespace_storage
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
