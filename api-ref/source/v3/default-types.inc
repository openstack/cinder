.. -*- rst -*-

Default Volume Types (default-types)
====================================

Manage a default volume type for individual projects.

By default, a volume-create request that does not specify a volume-type
will assign the configured system default volume type to the volume.
You can override this behavior on a per-project basis by setting a different
default volume type for any project.

Available in microversion 3.62 or higher.

NOTE: The default policy for list API is system admin so you would require
a system scoped token to access it.
To get a system scoped token, you need to run the following command:

openstack --os-system-scope all --os-project-name='' token issue

Create or update a default volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/default-types/{project-id}

Create or update the default volume type for a project

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 404

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type: volume_type_name_or_id

Request Example
---------------

.. literalinclude:: ./samples/set-default-type-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - project_id: project_id
   - volume_type_id: volume_type_id

Response Example
----------------

.. literalinclude:: ./samples/set-default-type-response.json
   :language: javascript

Show a default volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/default-types/{project-id}

Show the default volume type for a project

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 404

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - project_id: project_id
   - volume_type_id: volume_type_id

Response Example
----------------

.. literalinclude:: ./samples/get-default-type-response.json
   :language: javascript

List default volume types
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/default-types/

Get a list of all default volume types

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 404

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - project_id: project_id
   - volume_type_id: volume_type_id

Response Example
----------------

.. literalinclude:: ./samples/get-default-types-response.json
   :language: javascript

Delete a default volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/default-types/{project-id}

Unset the default volume type for a project.

This operation does not do anything to the volume type itself.
It simply removes the volume type from being the default volume type for
the specified project.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 204

.. rest_status_code:: error ../status.yaml

   - 404

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path