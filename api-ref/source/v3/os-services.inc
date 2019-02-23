.. -*- rst -*-

Services (os-services)
======================

Administrator only. Lists all Cinder services, enables or disables
a Cinder service, freeze or thaw the specified cinder-volume host,
failover a replicating cinder-volume host.


List All Cinder Services
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method:: GET /v3/{project_id}/os-services

Lists all Cinder services. Provides details why any services
were disabled.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - host: host_query
   - binary: binary_query

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

  - services: services
  - binary: binary_required
  - disabled_reason: disabled_reason_body_req
  - host: host_name_body_req
  - state: service_state_up_down
  - status: service_status
  - frozen: frozen
  - updated_at: updated
  - zone: availability_zone_required
  - cluster: cluster_cvol
  - replication_status: replication_status_cvol
  - active_backend_id: active_backend_id
  - backend_state: backend_state

Response Example
----------------

.. literalinclude:: ./samples/services-list-response.json
   :language: javascript


Disable a Cinder Service
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method:: PUT /v3/{project_id}/os-services/disable

Disables a Cinder service. Specify the service by its host name
and binary name.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403
   - 404

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - host: host_name_body_req
   - binary: binary_required

Request Example
---------------

.. literalinclude:: ./samples/services-disable-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

  - disabled: disabled_required
  - status: service_status
  - host: host_name_body_req
  - service: service_key
  - binary: binary_required

Response Example
----------------

.. literalinclude:: ./samples/services-disable-response.json
   :language: javascript


Log Disabled Cinder Service Information
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method:: PUT /v3/{project_id}/os-services/disable-log-reason

Logs information to the Cinder service table about why a Cinder service was
disabled.

Specify the service by its host name and binary name.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403
   - 404

Request
-------

.. rest_parameters:: parameters.yaml

  - project_id: project_id_path
  - binary: binary_required
  - host: host_name_body_req
  - disabled_reason: disabled_reason_body

Request Example
---------------

.. literalinclude:: ./samples/services-disable-log-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - disabled: disabled_required
  - status: service_status
  - host: host_name_body_req
  - service: service_key
  - binary: binary_required
  - disabled_reason: disabled_reason_body_req

Response Example
----------------

.. literalinclude:: ./samples/services-disable-log-response.json
   :language: javascript


Enable a Cinder Service
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method:: PUT /v3/{project_id}/os-services/enable

Enables a Cinder service. Specify the service by its host name
and binary name.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403
   - 404

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - binary: binary_required
   - host: host_name_body_req

Request Example
---------------

.. literalinclude:: ./samples/services-enable-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

  - disabled: disabled_required
  - status: service_status
  - host: host_name_body_req
  - service: service_key
  - binary: binary_required
  - disabled_reason: disabled_reason_body_req

Response Example
----------------

.. literalinclude:: ./samples/services-enable-response.json
   :language: javascript


Get Current Log Levels for Cinder Services
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method:: PUT /v3/{project_id}/os-services/get-log

Get current log levels for services, supported since v3.32. Filter the
services by binary, server name and prefix for the log path.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - binary: binary
   - server: host_name_body
   - prefix: prefix

Request Example
---------------

.. literalinclude:: ./samples/services-get-log-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

  - log_levels: log_levels
  - binary: binary_required
  - host: host_name_body_req
  - levels: levels

Response Example
----------------

.. literalinclude:: ./samples/services-get-log-response.json
   :language: javascript


Set Log Levels of Cinder Services Dynamically
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method:: PUT /v3/{project_id}/os-services/set-log

Set log levels of services dynamically, supported since v3.32. Filter the
services by binary, server name and prefix for the log path.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - binary: binary
   - server: host_name_body
   - prefix: prefix
   - levels: levels_set

Request Example
---------------

.. literalinclude:: ./samples/services-set-log-request.json
   :language: javascript


Freeze a Cinder Backend Host
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method:: PUT /v3/{project_id}/os-services/freeze

Freeze and disable the specified cinder-volume host, and set
``Disabled Reason`` of Cinder service table to ``frozen``.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - host: host_name_body_req

Request Example
---------------

.. literalinclude:: ./samples/services-freeze-request.json
   :language: javascript


Thaw a Cinder Backend Host
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method:: PUT /v3/{project_id}/os-services/thaw

Thaw and enable the specified cinder-volume host, and clean
``Disabled Reason`` of Cinder service table.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - host: host_name_body_req

Request Example
---------------

.. literalinclude:: ./samples/services-thaw-request.json
   :language: javascript


Failover a Cinder Backend Host
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method:: PUT /v3/{project_id}/os-services/failover_host

Failover a replicating cinder-volume host. Since Cinder Volume API Version
3.26, you can use ``failover`` in request URL instead of ``failover_host``,
and the cluster name in request body is supported.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403
   - 404

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - host: host_name_body_req
   - backend_id: backend_id
   - cluster: cluster_cvol

Request Example
---------------

.. literalinclude:: ./samples/services-failover-host-request.json
   :language: javascript
