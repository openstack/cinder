.. -*- rst -*-

Limits (limits)
===============

Shows absolute limits for a project.

An absolute limit value of ``-1`` indicates that the absolute limit
for the item is infinite.


Show absolute limits
~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{project_id}/limits

Shows absolute limits for a project.

An absolute limit value of ``-1`` indicates that the absolute limit
for the item is infinite.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 403

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - totalSnapshotsUsed: totalSnapshotsUsed
   - maxTotalBackups: maxTotalBackups
   - maxTotalVolumeGigabytes: maxTotalVolumeGigabytes
   - limits: limits
   - maxTotalSnapshots: maxTotalSnapshots
   - maxTotalBackupGigabytes: maxTotalBackupGigabytes
   - totalBackupGigabytesUsed: totalBackupGigabytesUsed
   - maxTotalVolumes: maxTotalVolumes
   - totalVolumesUsed: totalVolumesUsed
   - rate: rate
   - totalBackupsUsed: totalBackupsUsed
   - totalGigabytesUsed: totalGigabytesUsed
   - absolute: absolute

Response Example
----------------

.. literalinclude:: ./samples/limits-show-response.json
   :language: javascript
