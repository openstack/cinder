.. -*- rst -*-

Back-end storage pools
======================

Administrator only. Lists all back-end storage pools that are known
to the scheduler service.


List back-end storage pools
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{project_id}/scheduler-stats/get_pools

Lists all back-end storage pools.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

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
   - name: name_16
   - total_capacity_gb: total_capacity
   - volume_backend_name: volume_backend_name
   - capabilities: capabilities
   - free_capacity_gb: free_capacity
   - driver_version: driver_version
   - reserved_percentage: reserved_percentage
   - storage_protocol: storage_protocol

Response Example
----------------

.. literalinclude:: ./samples/pools-list-detailed-response.json
   :language: javascript
