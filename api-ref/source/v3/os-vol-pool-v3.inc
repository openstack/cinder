.. -*- rst -*-

Back-end storage pools
======================

Administrator only. Lists all back-end storage pools that are known
to the scheduler service.


List all back-end storage pools
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/scheduler-stats/get_pools

Lists all back-end storage pools, since v3.31 if non-admin users
specify invalid filters in the url, API will return bad request.


Normal response codes: 200
Error response codes: badRequest(400)

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - detail: detail

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - updated: updated
   - QoS_support: QoS_support
   - name: name
   - total_capacity: total_capacity
   - volume_backend_name: volume_backend_name
   - capabilities: capabilities
   - free_capacity: free_capacity
   - driver_version: driver_version
   - reserved_percentage: reserved_percentage
   - storage_protocol: storage_protocol

Response Example
----------------

.. literalinclude:: ./samples/pools-list-detailed-response.json
   :language: javascript
