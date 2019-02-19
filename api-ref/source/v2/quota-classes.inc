.. -*- rst -*-

Quota class set extension (os-quota-class-sets)
===============================================

Administrators only, depending on policy settings.

Shows and updates quota classes for a project.

Show quota classes
~~~~~~~~~~~~~~~~~~

.. rest_method::
   GET /v2/{admin_project_id}/os-quota-class-sets/{quota_class_name}

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

   - backup_gigabytes: maxTotalBackupGigabytes
   - backups: maxTotalBackups
   - gigabytes: maxTotalVolumeGigabytes
   - groups: maxTotalGroups
   - per_volume_gigabytes: perVolumeGigabytes
   - snapshots: maxTotalSnapshots
   - volumes: maxTotalVolumes
   - id: quota_class_id


Response Example
----------------

.. literalinclude:: ./samples/quota-classes-show-response.json
   :language: javascript

Update quota classes
~~~~~~~~~~~~~~~~~~~~

.. rest_method::
   PUT /v2/{admin_project_id}/os-quota-class-sets/{quota_class_name}

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
   - snapshots: maxTotalSnapshotsOptional
   - volumes: maxTotalVolumesOptional
   - volume-type: volume_type

Request Example
---------------

.. literalinclude:: ./samples/quota-classes-update-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - backup_gigabytes: maxTotalBackupGigabytes
   - backups: maxTotalBackups
   - gigabytes: maxTotalVolumeGigabytes
   - groups: maxTotalGroups
   - per_volume_gigabytes: perVolumeGigabytes
   - snapshots: maxTotalSnapshots
   - volumes: maxTotalVolumes

Response Example
----------------

.. literalinclude:: ./samples/quota-classes-update-response.json
   :language: javascript
