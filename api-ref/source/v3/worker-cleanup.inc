.. -*- rst -*-

Workers (workers)
=================


Cleanup services
~~~~~~~~~~~~~~~~

.. rest_method::  POST v3/{project_id}/workers/cleanup

Request cleanup of services with optional filtering. This API is only
available with microversion 3.24 or later.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - cluster_name: cluster_mutex
   - service_id: service_id
   - host: host_service
   - binary: binary_required
   - is-up: is_up
   - disabled: disabled
   - resource-id: resource_id
   - resource-type: resource_type


Request Example
---------------

.. literalinclude:: ./samples/worker-cleanup-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - host: host_service
   - binary: binary_required
   - id: service_id
   - cluster_name: cluster_mutex


Response Example
----------------

.. literalinclude:: ./samples/worker-cleanup-response.json
   :language: javascript
