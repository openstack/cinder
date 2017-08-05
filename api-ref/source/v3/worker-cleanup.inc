.. -*- rst -*-

Workers (workers)
=================


Cleanup services
~~~~~~~~~~~~~~~~

.. rest_method::  POST v3/{project_id}/workers/cleanup

Request cleanup of services with optional filtering. This API is only
available with microversion 3.24 or later.



Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - cluster: cluster_mutex
   - host: host_service
   - binary: binary
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
   - binary: binary
   - id: service_id
   - cluster_name: cluster_mutex


Response Example
----------------

.. literalinclude:: ./samples/worker-cleanup-response.json
   :language: javascript
