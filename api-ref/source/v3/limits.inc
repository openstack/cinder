.. -*- rst -*-

Limits (limits)
===============

Shows absolute limits for a project.

An absolute limit value of ``-1`` indicates that the absolute limit
for the item is infinite.


Show absolute limits for project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/limits

Shows absolute limits for a project.

An absolute limit value of ``-1`` indicates that the absolute limit
for the item is infinite.


Normal response codes: 200
Error response codes:203,

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
