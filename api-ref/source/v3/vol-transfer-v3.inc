.. -*- rst -*-

Volume transfer
===============

Transfers a volume from one user to another user.
This is the new transfer APIs with microversion 3.53.


Accept a volume transfer
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volume_transfers/{transfer_id}/accept

Accepts a volume transfer.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400

.. rest_status_code:: error ../status.yaml

   - 413

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - transfer_id: transfer_id
   - auth_key: auth_key

Request Example
---------------

.. literalinclude:: ./samples/volume-transfer-accept-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - transfer: transfer
   - volume_id: volume_id
   - id: id
   - links: links
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/volume-transfer-accept-response.json
   :language: javascript


Create a volume transfer
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volume_transfers

Creates a volume transfer.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - transfer: transfer
   - name: name
   - volume_id: volume_id
   - no_snapshots: no_snapshots

Request Example
---------------

.. literalinclude:: ./samples/volume-transfer-create-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - auth_key: auth_key
   - links: links
   - created_at: created_at
   - volume_id: volume_id
   - id: id
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/volume-transfer-create-response.json
   :language: javascript


List volume transfers for a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volume_transfers

Lists volume transfers.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - all_tenants: all-tenants


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volume_id: volume_id
   - id: id
   - links: links
   - name: name


Response Example
----------------

.. literalinclude:: ./samples/volume-transfers-list-response.json
   :language: javascript


Show volume transfer detail
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volume_transfers/{transfer_id}

Shows details for a volume transfer.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - transfer_id: transfer_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - created_at: created_at
   - volume_id: volume_id
   - id: id
   - links: links
   - name: name


Response Example
----------------

.. literalinclude:: ./samples/volume-transfer-show-response.json
   :language: javascript


Delete a volume transfer
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/volume_transfers/{transfer_id}

Deletes a volume transfer.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - transfer_id: transfer_id


List volume transfers and details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volume_transfers/detail

Lists volume transfers, with details.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - all_tenants: all-tenants

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - transfers: transfers
   - created_at: created_at
   - volume_id: volume_id
   - id: id
   - links: links
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/volume-transfers-list-detailed-response.json
   :language: javascript
