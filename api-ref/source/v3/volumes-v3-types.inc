.. -*- rst -*-

Volume types (types)
====================

To create an environment with multiple-storage back ends, you must
specify a volume type. The API spawns Block Storage volume back
ends as children to ``cinder-volume``, and keys them from a unique
queue. The API names the back ends ``cinder-volume.HOST.BACKEND``.
For example, ``cinder-volume.ubuntu.lvmdriver``. When you create a
volume, the scheduler chooses an appropriate back end for the
volume type to handle the request.

For information about how to use volume types to create multiple-
storage back ends, see `Configure multiple-storage back ends
<https://docs.openstack.org/cinder/latest/admin
/blockstorage-multi-backend.html>`_.


Update a volume type
~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/types/{volume_type_id}

Updates a volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id
   - volume_type: volume_type
   - name: name_volume_type_optional
   - description: description_volume_type_optional
   - is_public: is_public_volume_type_optional

Request Example
---------------

.. literalinclude:: ./samples/volume_type/volume-type-update-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volume_type: volume_type
   - is_public: is_public_volume_type_required
   - extra_specs: extra_specs_volume_type_optional
   - description: description_volume_type_required
   - name: name_volume_type_required
   - id: volume_type_id

Response Example
----------------

.. literalinclude:: ./samples/volume_type/volume-type-update-response.json
   :language: javascript


Create or update extra specs for volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/types/{volume_type_id}/extra_specs

Adds new extra specifications to a volume type, or updates the extra
specifications that are assigned to a volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id
   - extra_specs: extra_specs_volume_type_required

Request Example
---------------

.. literalinclude::
   ./samples/volume_type/volume-type-extra-specs-create-update-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - extra_specs: extra_specs_volume_type_required


Response Example
----------------

.. literalinclude::
   ./samples/volume_type/volume-type-extra-specs-create-update-response.json
   :language: javascript


Show all extra specifications for volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/types/{volume_type_id}/extra_specs

Shows all extra specifications assigned to a volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - extra_specs: extra_specs_volume_type_required


Response Example
----------------

.. literalinclude::
   ./samples/volume_type/volume-type-all-extra-specs-show-response.json
   :language: javascript


Show extra specification for volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/types/{volume_type_id}/extra_specs/{key}

Shows the specific extra specification assigned to a volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id
   - key: key_extra_spec


Response Example
----------------

.. literalinclude::
   ./samples/volume_type/volume-type-specific-extra-specs-show-response.json
   :language: javascript


Update extra specification for volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{project_id}/types/{volume_type_id}/extra_specs/{key}

Update the specific extra specification assigned to a volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id
   - key: key_extra_spec

Request Example
---------------

.. literalinclude::
   ./samples/volume_type/volume-type-specific-extra-specs-update-request.json
   :language: javascript


Response Example
----------------

.. literalinclude::
   ./samples/volume_type/volume-type-specific-extra-specs-update-response.json
   :language: javascript


Delete extra specification for volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   DELETE /v3/{project_id}/types/{volume_type_id}/extra_specs/{key}

Deletes the specific extra specification assigned to a volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id
   - key: key_extra_spec


Show volume type detail
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/types/{volume_type_id}

Shows details for a volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volume_type: volume_type
   - is_public: is_public_volume_type_required
   - extra_specs: extra_specs_volume_type_optional
   - description: description_volume_type_required
   - name: name_volume_type_required
   - id: volume_type_id_body
   - os-volume-type-access:is_public: is_public_volume_type_required
   - qos_specs_id: qos_specs_id


Response Example
----------------

.. literalinclude:: ./samples/volume_type/volume-type-show-response.json
   :language: javascript


Show default volume type
~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/types/default

Shows details for the default volume type if configured.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volume_type: volume_type
   - is_public: is_public_volume_type_required
   - extra_specs: extra_specs_volume_type_optional
   - description: description_volume_type_required
   - name: name_volume_type_required
   - qos_specs_id: qos_specs_id


Response Example
----------------

.. literalinclude:: ./samples/volume_type/volume-type-default-response.json
   :language: javascript


Delete a volume type
~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/types/{volume_type_id}

Deletes a volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id


List all volume types
~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/types

Lists volume types.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - is_public: is_public_volume_type_query
   - sort: sort
   - limit: limit
   - offset: offset
   - marker: marker


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volume_types: volume_types
   - extra_specs: extra_specs_volume_type_optional
   - name: name_volume_type_required
   - is_public: is_public_volume_type_required
   - description: description_volume_type_required
   - id: volume_type_id_body
   - os-volume-type-access:is_public: is_public_volume_type_required
   - qos_specs_id: qos_specs_id

Response Example
----------------

.. literalinclude:: ./samples/volume_type/volume-types-list-response.json
   :language: javascript


Create a volume type
~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/types

Creates a volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type: volume_type
   - name: name_volume_type_required
   - os-volume-type-access:is_public: is_public_volume_type_optional
   - description: description_volume_type_optional
   - extra_specs: extra_specs_volume_type_optional

Request Example
---------------

.. literalinclude:: ./samples/volume_type/volume-type-create-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volume_type: volume_type
   - is_public: is_public_volume_type_required
   - extra_specs: extra_specs_volume_type_optional
   - description: description_volume_type_required
   - name: name_volume_type_required
   - id: volume_type_id_body
   - os-volume-type-access:is_public: is_public_volume_type_required

Response Example
----------------

.. literalinclude:: ./samples/volume_type/volume-type-create-response.json
   :language: javascript


Show an encryption type
~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/types/{volume_type_id}/encryption

To show an encryption type for an existing volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - volume_type_id: volume_type_id_body
   - encryption_id: encryption_id_body
   - key_size: key_size
   - provider: provider
   - control_location: control_location
   - cipher: cipher
   - deleted: deleted
   - created_at: created_at
   - updated_at: updated_at
   - deleted_at: deleted_at

Response Example
----------------

.. literalinclude:: ./samples/volume_type/encryption-type-show-response.json
   :language: javascript


Show encryption specs item
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/types/{volume_type_id}/encryption/{key}

To show encryption specs item for an existing volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id
   - key: key_encrypt_spec

Response Example
----------------

.. literalinclude::
   ./samples/volume_type/encryption-type-specific-specs-show-response.json
   :language: javascript


Delete an encryption type
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   DELETE /v3/{project_id}/types/{volume_type_id}/encryption/{encryption_id}

To delete an encryption type for an existing volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id
   - encryption_id: encryption_id


Create an encryption type
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v3/{project_id}/types/{volume_type_id}/encryption

To create an encryption type for an existing volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id
   - encryption: encryption
   - key_size: key_size
   - provider: provider_req
   - control_location: control_location
   - cipher: cipher

Request Example
---------------

.. literalinclude:: ./samples/volume_type/encryption-type-create-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - encryption: encryption
   - volume_type_id: volume_type_id_body
   - encryption_id: encryption_id_body
   - key_size: key_size
   - provider: provider
   - control_location: control_location
   - cipher: cipher

Response Example
----------------

.. literalinclude:: ./samples/volume_type/encryption-type-create-response.json
   :language: javascript


Update an encryption type
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   PUT /v3/{project_id}/types/{volume_type_id}/encryption/{encryption_id}

To update an encryption type for an existing volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type_id: volume_type_id
   - encryption_id: encryption_id
   - encryption: encryption
   - key_size: key_size
   - provider: provider_req_optional
   - control_location: control_location
   - cipher: cipher

Request Example
---------------

.. literalinclude:: ./samples/volume_type/encryption-type-update-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - encryption: encryption
   - key_size: key_size
   - provider: provider_optional
   - control_location: control_location
   - cipher: cipher

Response Example
----------------

.. literalinclude:: ./samples/volume_type/encryption-type-update-response.json
   :language: javascript
