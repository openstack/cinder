.. -*- rst -*-

Quota sets extension (os-quota-sets)
====================================

Administrators only, depending on policy settings.

Shows, updates, and deletes quotas for a project.

Show quotas
~~~~~~~~~~~

.. rest_method::  GET /v2/{admin_project_id}/os-quota-sets/{project_id}

Shows quotas for a project.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: quotas_project_id
   - admin_project_id: admin_project_id
   - usage: usage


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - quota_set: quota_set
   - id: project_id
   - volumes: volumes_number
   - volumes_{volume_type}: volumes_number_for_type
   - snapshots: snapshots_number
   - snapshots_{volume_type}: snapshots_number_for_type
   - backups: backups_number
   - groups: groups_number
   - per_volume_gigabytes: per_volume_gigabytes
   - gigabytes: gigabytes
   - gigabytes_{volume_type}: gigabytes_for_type
   - backup_gigabytes: backup_gigabytes

Response Example
----------------

.. literalinclude:: ./samples/quotas-show-response.json
   :language: javascript

Update quotas
~~~~~~~~~~~~~

.. rest_method::  PUT /v2/{admin_project_id}/os-quota-sets/{project_id}

Updates quotas for a project.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - admin_project_id: admin_project_id
   - project_id: quotas_project_id
   - quota_set: quota_set
   - volumes: volumes_number
   - volumes_{volume_type}: volumes_number_for_type
   - snapshots: snapshots_number
   - snapshots_{volume_type}: snapshots_number_for_type
   - backups: backups_number
   - groups: groups_number
   - per_volume_gigabytes: per_volume_gigabytes
   - gigabytes: gigabytes
   - gigabytes_{volume_type}: gigabytes_for_type
   - backup_gigabytes: backup_gigabytes

Request Example
---------------

.. literalinclude:: ./samples/quotas-update-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - quota_set: quota_set
   - volumes: volumes_number
   - volumes_{volume_type}: volumes_number_for_type
   - snapshots: snapshots_number
   - snapshots_{volume_type}: snapshots_number_for_type
   - backups: backups_number
   - groups: groups_number
   - per_volume_gigabytes: per_volume_gigabytes
   - gigabytes: gigabytes
   - gigabytes_{volume_type}: gigabytes_for_type
   - backup_gigabytes: backup_gigabytes

Response Example
----------------

.. literalinclude:: ./samples/quotas-update-response.json
   :language: javascript

Delete quotas
~~~~~~~~~~~~~

.. rest_method::  DELETE /v2/{admin_project_id}/os-quota-sets/{project_id}

Deletes quotas for a project so the quotas revert to default values.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: quotas_project_id
   - admin_project_id: admin_project_id

Response Example
----------------

.. literalinclude:: ./samples/quotas-delete-response.json
   :language: javascript

Get default quotas
~~~~~~~~~~~~~~~~~~

.. rest_method::
   GET /v2/{admin_project_id}/os-quota-sets/{project_id}/defaults

Gets default quotas for a project.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: quotas_project_id
   - admin_project_id: admin_project_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - quota_set: quota_set
   - id: project_id
   - volumes: volumes_number
   - volumes_{volume_type}: volumes_number_for_type
   - snapshots: snapshots_number
   - snapshots_{volume_type}: snapshots_number_for_type
   - backups: backups_number
   - groups: groups_number
   - per_volume_gigabytes: per_volume_gigabytes
   - gigabytes: gigabytes
   - gigabytes_{volume_type}: gigabytes_for_type
   - backup_gigabytes: backup_gigabytes

Response Example
----------------

.. literalinclude:: ./samples/quotas-show-defaults-response.json
   :language: javascript
