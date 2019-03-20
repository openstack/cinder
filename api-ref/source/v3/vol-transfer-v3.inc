.. -*- rst -*-

Volume transfer (3.55 or later)
===============================

Transfers a volume from one user to another user.
This is the new transfer APIs with microversion 3.55.


Accept a volume transfer
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volume-transfers/{transfer_id}/accept

Accepts a volume transfer.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

.. rest_status_code:: error ../status.yaml

   - 400
   - 413

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - transfer_id: transfer_id
   - auth_key: auth_key

Request Example
---------------

.. literalinclude:: ./samples/volume_transfer/volume-transfer-accept-request.json
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

.. literalinclude:: ./samples/volume_transfer/volume-transfer-accept-response.json
   :language: javascript


Create a volume transfer
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/volume-transfers

Creates a volume transfer.

**Preconditions**

* The volume ``status`` must be ``available``
* Transferring encrypted volumes is not supported
* If the volume has snapshots, those snapshots must be ``available`` unless
  ``no_snapshots=True``

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

.. literalinclude:: ./samples/volume_transfer/volume-transfer-create-request.json
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
   - destination_project_id: destination_project_id
   - source_project_id: source_project_id
   - accepted: accepted

Response Example
----------------

.. literalinclude:: ./samples/volume_transfer/volume-transfer-create-response.json
   :language: javascript


List volume transfers for a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volume-transfers

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
   - limit: limit_transfer
   - offset: offset_transfer
   - marker: marker_transfer
   - sort_key: sort_key_transfer
   - sort_dir: sort_dir_transfer


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volume_id: volume_id
   - id: id
   - links: links
   - name: name


Response Example
----------------

.. literalinclude:: ./samples/volume_transfer/volume-transfers-list-response.json
   :language: javascript


Show volume transfer detail
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/volume-transfers/{transfer_id}

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
   - destination_project_id: destination_project_id
   - source_project_id: source_project_id
   - accepted: accepted


Response Example
----------------

.. literalinclude:: ./samples/volume_transfer/volume-transfer-show-response.json
   :language: javascript


Delete a volume transfer
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/volume-transfers/{transfer_id}

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

.. rest_method::  GET /v3/{project_id}/volume-transfers/detail

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
   - destination_project_id: destination_project_id
   - source_project_id: source_project_id
   - accepted: accepted

Response Example
----------------

.. literalinclude:: ./samples/volume_transfer/volume-transfers-list-detailed-response.json
   :language: javascript
