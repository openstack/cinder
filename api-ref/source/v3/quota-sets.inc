.. -*- rst -*-

Quota sets extension (os-quota-sets)
====================================

Administrators only, depending on policy settings.

Shows, updates, and deletes quotas for a project.


Show quotas for a project
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{admin_project_id}/os-quota-sets/{project_id}

Shows quotas for a project.


Normal response codes: 200
Error response codes:


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


Show quota usage for a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{admin_project_id}/os-quota-sets/{project_id}?{usage}=True

Shows quota usage for a project.


Normal response codes: 200
Error response codes:


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
   - volumes: volumes_number_usage
   - volumes_{volume_type}: volumes_number_for_type_usage
   - snapshots: snapshots_number_usage
   - snapshots_{volume_type}: snapshots_number_for_type_usage
   - backups: backups_number_usage
   - groups: groups_number_usage
   - per_volume_gigabytes: per_volume_gigabytes_usage
   - gigabytes: gigabytes_usage
   - gigabytes_{volume_type}: gigabytes_for_type_usage
   - backup_gigabytes: backup_gigabytes_usage

Response Example
----------------

.. literalinclude:: ./samples/quotas-show-usage-response.json
   :language: javascript



Update quotas for a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v3/{admin_project_id}/os-quota-sets/{project_id}

Updates quotas for a project.


Normal response codes: 200
Error response codes:


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
   - skip_validation: skip_validation

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

Delete quotas for a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{admin_project_id}/os-quota-sets/{project_id}

Deletes quotas for a project so the quotas revert to default values.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: quotas_project_id
   - admin_project_id: admin_project_id




Get default quotas for a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{admin_project_id}/os-quota-sets/{project_id}/defaults

Gets default quotas for a project.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
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
