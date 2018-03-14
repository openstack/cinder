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
  - binary: binary
  - disabled_reason: disabled_reason_body
  - host: host_name_body
  - state: service_state_1
  - status: service_status
  - frozen: frozen
  - updated_at: updated
  - zone: availability_zone_3
  - cluster: cluster
  - replication_status: replication_status_1
  - active_backend_id: active_backend_id

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
   - host: host_name_body
   - binary: binary

Request Example
---------------

.. literalinclude:: ./samples/services-disable-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

  - disabled: disabled_1
  - status: service_status
  - host: host_name_body
  - service: service_key
  - binary: binary

Response Example
----------------

.. literalinclude:: ./samples/services-disable-response.json
   :language: javascript


Log Disabled Cinder Service Information
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method:: PUT /v3/{project_id}/os-services/disable-log-reason

Logs information to the Cinder service table about why a Cinder service was disabled.

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
  - binary: binary
  - host: host_name_body
  - disabled_reason: disabled_reason_body_1

Request Example
---------------

.. literalinclude:: ./samples/services-disable-log-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - disabled: disabled_1
  - status: service_status
  - host: host_name_body
  - service: service_key
  - binary: binary
  - disabled_reason: disabled_reason_body

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
   - binary: binary
   - host: host_name_body

Request Example
---------------

.. literalinclude:: ./samples/services-enable-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

  - disabled: disabled_1
  - status: service_status
  - host: host_name_body
  - service: service_key
  - binary: binary
  - disabled_reason: disabled_reason_body

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
   - binary: binary_1
   - server: host_name_body_1
   - prefix: prefix

Request Example
---------------

.. literalinclude:: ./samples/services-get-log-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

  - log_levels: log_levels
  - binary: binary
  - host: host_name_body
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
   - binary: binary_1
   - server: host_name_body_1
   - prefix: prefix
   - levels: levels_1

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
   - host: host_name_body

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
   - host: host_name_body

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
   - host: host_name_body
   - backend_id: backend_id
   - cluster: cluster

Request Example
---------------

.. literalinclude:: ./samples/services-failover-host-request.json
   :language: javascript
