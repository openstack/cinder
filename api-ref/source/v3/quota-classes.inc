.. -*- rst -*-

Quota class set extension (os-quota-class-sets)
===============================================

Administrators only, depending on policy settings.

Shows and updates quota classes for a project.

Show quota classes for a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   GET /v3/{admin_project_id}/os-quota-class-sets/{quota_class_name}

Shows quota class set for a project. If no specific value for the quota class
resource exists, then the default value will be reported.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 403
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - quota_class_name: quota_class_name
   - admin_project_id: admin_project_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - quota_class_set: quota_class_set
   - backup_gigabytes: maxTotalBackupGigabytes
   - backups: maxTotalBackups
   - gigabytes: maxTotalVolumeGigabytes
   - gigabytes_{volume_type}: gigabytes_for_type
   - groups: maxTotalGroups
   - per_volume_gigabytes: per_volume_gigabytes
   - snapshots: maxTotalSnapshots
   - snapshots_{volume_type}: snapshots_number_for_type
   - volumes: maxTotalVolumes
   - volumes_{volume_type}: volumes_number_for_type
   - id: quota_class_id


Response Example
----------------

.. literalinclude:: ./samples/quota-classes-show-response.json
   :language: javascript

Update quota classes for a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   PUT /v3/{admin_project_id}/os-quota-class-sets/{quota_class_name}

Updates quota class set for a project. If the ``quota_class_name`` key does not
exist, then the API will create one.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 403
   - 404


Request
-------

.. rest_parameters:: parameters.yaml

   - admin_project_id: admin_project_id
   - quota_class_name: quota_class_name
   - gigabytes: maxTotalVolumeGigabytesOptional
   - gigabytes_{volume_type}: gigabytes_for_type
   - snapshots: maxTotalSnapshotsOptional
   - snapshots_{volume_type}: snapshots_number_for_type
   - volumes: maxTotalVolumesOptional
   - volumes_{volume_type}: volumes_number_for_type

Request Example
---------------

.. literalinclude:: ./samples/quota-classes-update-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - quota_class_set: quota_class_set
   - backup_gigabytes: maxTotalBackupGigabytes
   - backups: maxTotalBackups
   - gigabytes: maxTotalVolumeGigabytes
   - gigabytes_{volume_type}: gigabytes_for_type
   - groups: maxTotalGroups
   - per_volume_gigabytes: per_volume_gigabytes
   - snapshots: maxTotalSnapshots
   - snapshots_{volume_type}: snapshots_number_for_type
   - volumes: maxTotalVolumes
   - volumes_{volume_type}: volumes_number_for_type

Response Example
----------------

.. literalinclude:: ./samples/quota-classes-update-response.json
   :language: javascript
