.. -*- rst -*-

Hosts extension (os-hosts)
==========================

Administrators only, depending on policy settings.

Lists, shows hosts.


List all hosts
~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{admin_project_id}/os-hosts

Lists all hosts summary info that is not disabled.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403

Request
-------

.. rest_parameters:: parameters.yaml

   - admin_project_id: admin_project_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - service-status: host_service_status
   - service: host_service
   - zone: availability_zone_3
   - service-state: service_state
   - host_name: host_name_1
   - last-update: updated_at

Response Example
----------------

.. literalinclude:: ./samples/hosts-list-response.json
   :language: javascript

Show Host Details
~~~~~~~~~~~~~~~~~

.. rest_method:: GET /v2/{admin_project_id}/os-hosts/{host_name}

Shows volume and snapshot details for a cinder-volume host.

*Note:* This API is meant specifically for cinder-volume hosts only.
It is not valid against other Cinder service hosts or hosts where the
cinder-volume service has been disabled.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

.. rest_status_code:: error ../status.yaml

   - 400
   - 401
   - 403
   - 404

Request
-------

.. rest_parameters:: parameters.yaml

  - admin_project_id: admin_project_id
  - host_name: hostname

Response
--------

.. rest_parameters:: parameters.yaml

  - volume_count: total_count_str
  - total_volume_gb: totalGigabytesUsedStr
  - total_snapshot_gb: totalSnapshotsUsedStr
  - project: project_id_2
  - host: host_name_1
  - snapshot_count: totalSnapshotsUsed

**Example Show Host Details**

.. literalinclude:: ./samples/hosts-get-response.json
   :language: javascript
