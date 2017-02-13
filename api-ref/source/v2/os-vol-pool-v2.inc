.. -*- rst -*-

Back-end storage pools
======================

Administrator only. Lists all back-end storage pools that are known
to the scheduler service.


List back-end storage pools
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{tenant_id}/scheduler-stats/get_pools

Lists all back-end storage pools.


Normal response codes: 200
Error response codes:

Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
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
