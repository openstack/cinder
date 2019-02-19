.. -*- rst -*-

Volume type access (volumes)
============================

Private volume type access to project.

By default, volumes types are public. To create a private volume
type, set the ``is_public`` boolean field to ``false`` at volume
type creation time. To control access to a private volume type,
user needs to add a project to or remove a project from the volume
type. Private volume types without projects are only accessible by
users with the administrative role and context.


Add private volume type access
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/types/{volume_type}/action

Adds private volume type access to a project.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project: project
   - project_id: project_id_path
   - volume_type: volume_type_access

Request Example
---------------

.. literalinclude:: ./samples/volume-type-access-add-request.json
   :language: javascript


Remove private volume type access
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v2/{project_id}/types/{volume_type}/action

Removes private volume type access from a project.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 202


Request
-------

.. rest_parameters:: parameters.yaml

   - project: project
   - project_id: project_id_path
   - volume_type: volume_type_access

Request Example
---------------

.. literalinclude:: ./samples/volume-type-access-delete-request.json
   :language: javascript


List private volume type access details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   GET /v2/{project_id}/types/{volume_type}/os-volume-type-access

Lists project IDs that have access to private volume type.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - volume_type: volume_type_access


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - project_id: project_id



Response Example
----------------

.. literalinclude:: ./samples/volume-type-access-list-response.json
   :language: javascript
