.. -*- rst -*-

Volume transfer
===============

Transfers a volume from one user to another user.


Accept volume transfer
~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/os-volume-transfer/{transfer_id}/accept

Accepts a volume transfer.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - auth_key: auth_key
   - transfer: transfer
   - transfer_id: transfer_id
   - project_id: project_id_path

Request Example
---------------

.. literalinclude:: ./samples/volume-transfer-accept-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volume_id: volume_id
   - id: id
   - links: links
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/volume-transfer-accept-response.json
   :language: javascript


Create volume transfer
~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/os-volume-transfer

Creates a volume transfer.

**Preconditions**

* The volume ``status`` must be ``available``
* Transferring encrypted volumes is not supported
* If the volume has snapshots, those snapshots must be ``available``

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - transfer: transfer
   - name: name
   - volume_id: volume_id
   - project_id: project_id_path

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


List volume transfers
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{project_id}/os-volume-transfer

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


Show volume transfer details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{project_id}/os-volume-transfer/{transfer_id}

Shows details for a volume transfer.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

Request
-------

.. rest_parameters:: parameters.yaml

   - transfer_id: transfer_id
   - project_id: project_id_path


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


Delete volume transfer
~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v2/{project_id}/os-volume-transfer/{transfer_id}

Deletes a volume transfer.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202

Request
-------

.. rest_parameters:: parameters.yaml

   - transfer_id: transfer_id
   - project_id: project_id_path


List volume transfers, with details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{project_id}/os-volume-transfer/detail

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

   - created_at: created_at
   - volume_id: volume_id
   - id: id
   - links: links
   - name: name

Response Example
----------------

.. literalinclude:: ./samples/volume-transfers-list-detailed-response.json
   :language: javascript
