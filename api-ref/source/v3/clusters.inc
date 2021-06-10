.. -*- rst -*-

Clusters (clusters)
===================

Administrator only.  Lists all Cinder clusters, show cluster detail,
enable or disable a cluster.

Each cinder service runs on a *host* computer (possibly multiple services
on the same host; it depends how you decide to deploy cinder).  In order
to support High Availibility scenarios, services can be grouped into
*clusters* where the same type of service (for example, cinder-volume)
can run on different hosts so that if one host goes down the service is
still available on a different host. Since there's no point having these
services sitting around doing nothing while waiting for some other host
to go down (which is also known as Active/Passive mode), grouping services
into clusters also allows cinder to support Active/Active mode in which
all services in a cluster are doing work all the time.

.. note::

   Currently the only service that can be grouped into clusters is
   ``cinder-volume``.

Clusters are determined by the deployment configuration; that's why there
is no 'create-cluster' API call listed below.  Once your services are up
and running, however, you can use the following API requests to get
information about your clusters and to update their status.


Disable cluster
~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/clusters/disable

Disables a cluster. Specify the cluster by its name and optionally the
binary name in the request body.

Available starting in the 3.7 microversion.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 404

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - name: cluster_name_required
   - binary: cluster_binary
   - disabled_reason: disabled_reason_body

Request Example
---------------

.. literalinclude:: ./samples/clusters/v3.7/cluster-disable-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - cluster: cluster
   - name: cluster_name_resp
   - binary: cluster_binary_resp
   - state: cluster_state
   - status: cluster_status
   - replication_status: cluster_replication_status
   - disabled_reason: disabled_reason_body

Response Example
----------------

.. literalinclude:: ./samples/clusters/v3.7/cluster-disable-response.json
   :language: javascript


Enable cluster
~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/clusters/enable

Enables a cluster. Specify the cluster by its name and optionally the
binary name in the request body.

Available starting in the 3.7 microversion.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 404

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - name: cluster_name_required
   - binary: cluster_binary

Request Example
---------------

.. literalinclude:: ./samples/clusters/v3.7/cluster-enable-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - cluster: cluster
   - name: cluster_name_resp
   - binary: cluster_binary_resp
   - state: cluster_state
   - status: cluster_status
   - replication_status: cluster_replication_status
   - disabled_reason: disabled_reason_body

Response Example
----------------

.. literalinclude:: ./samples/clusters/v3.7/cluster-enable-response.json
   :language: javascript


Show cluster details
~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/clusters/{cluster_name}

Shows details for a cluster by its name and optionally the
binary name.

Available starting in the 3.7 microversion.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 404

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - cluster_name: cluster_name_path
   - binary: cluster_binary_query

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - cluster: cluster
   - name: cluster_name_resp
   - binary: cluster_binary_resp
   - state: cluster_state
   - status: cluster_status
   - num_hosts: cluster_num_hosts
   - num_down_hosts: cluster_num_down_hosts
   - last_heartbeat: cluster_last_heartbeat
   - created_at: created_at
   - updated_at: updated_at
   - disabled_reason: disabled_reason_body
   - replication_status: cluster_replication_status
   - frozen: cluster_frozen
   - active_backend_id: cluster_active_backend_id

Response Example
----------------

.. literalinclude:: ./samples/clusters/v3.7/cluster-show-response.json
   :language: javascript


List clusters
~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/clusters

Lists all clusters.

Available starting in the 3.7 microversion.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - name: cluster_name_query
   - binary: cluster_binary_query
   - is_up: cluster_is_up_query
   - disabled: cluster_disabled_query
   - num_hosts: cluster_num_hosts_query
   - num_down_hosts: cluster_num_down_hosts_query
   - replication_status: cluster_replication_status_query

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - clusters: clusters
   - name: cluster_name_resp
   - binary: cluster_binary_resp
   - state: cluster_state
   - status: cluster_status
   - replication_status: cluster_replication_status

Response Example
----------------

.. literalinclude:: ./samples/clusters/v3.7/clusters-list-response.json
   :language: javascript


List clusters with details
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/clusters/detail

Lists all clusters with details.

Available starting in the 3.7 microversion.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - name: cluster_name_query
   - binary: cluster_binary_query
   - is_up: cluster_is_up_query
   - disabled: cluster_disabled_query
   - num_hosts: cluster_num_hosts_query
   - num_down_hosts: cluster_num_down_hosts_query
   - replication_status: cluster_replication_status_query
   - frozen: cluster_frozen
   - active_backend_id: cluster_active_backend_id

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - clusters: clusters
   - name: cluster_name_resp
   - binary: cluster_binary_resp
   - state: cluster_state
   - status: cluster_status
   - num_hosts: cluster_num_hosts
   - num_down_hosts: cluster_num_down_hosts
   - last_heartbeat: cluster_last_heartbeat
   - created_at: created_at
   - updated_at: updated_at
   - disabled_reason: disabled_reason_body
   - replication_status: cluster_replication_status
   - frozen: cluster_frozen
   - active_backend_id: cluster_active_backend_id

Response Example
----------------

.. literalinclude:: ./samples/clusters/v3.7/clusters-list-detailed-response.json
   :language: javascript
