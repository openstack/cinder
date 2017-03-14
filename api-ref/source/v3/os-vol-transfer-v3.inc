.. -*- rst -*-

Volume transfer
===============

Transfers a volume from one user to another user.


Accept a volume transfer
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/os-volume-transfer/{transfer_id}/accept

Accepts a volume transfer.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - auth_key: auth_key
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


Create a volume transfer
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/os-volume-transfer

Creates a volume transfer.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

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


List volume transfers for a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/os-volume-transfer

Lists volume transfers.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path


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

.. rest_method::  GET /v3/{project_id}/os-volume-transfer/{transfer_id}

Shows details for a volume transfer.


Normal response codes: 200
Error response codes:


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


Delete a volume transfer
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/os-volume-transfer/{transfer_id}

Deletes a volume transfer.

Normal response codes: 202


Request
-------

.. rest_parameters:: parameters.yaml

   - transfer_id: transfer_id
   - project_id: project_id_path


List volume transfers and details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/os-volume-transfer/detail

Lists volume transfers, with details.


Normal response codes: 200
Error response codes:

Request
-------

.. rest_parameters:: parameters.yaml

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

.. literalinclude:: ./samples/volume-transfers-list-detailed-response.json
   :language: javascript
