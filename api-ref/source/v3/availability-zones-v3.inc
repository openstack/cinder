.. -*- rst -*-

Availability zones (os-availability-zone)
=========================================

List availability zone information.


List Availability Zone Information
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method:: GET /v3/{project_id}/os-availability-zone

List availability zone information.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path

Response Parameter
------------------

.. rest_parameters:: parameters.yaml

  - project_id: project_id
  - availabilityZoneInfo: availability_zone_info
  - zoneName: availability_zone_required
  - zoneState: availability_zone_state
  - available: available

Response Example
----------------

.. literalinclude:: ./samples/availability-zone-list-response.json
   :language: javascript
