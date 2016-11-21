.. -*- rst -*-

====================================
Snapshot actions (snapshots, action)
====================================

Administrator only. Resets status for a snapshot.


Reset a snapshot's status
=========================

.. rest_method::  POST /v3/{tenant_id}/snapshots/{snapshot_id}/action

Resets the status. Specify the ``os-reset_status`` action in the request body.

Normal response codes: 202,


Request
-------

.. rest_parameters:: parameters.yaml

   - status: status_2
   - os-reset_status: os-reset_status
   - tenant_id: tenant_id
   - snapshot_id: snapshot_id

Request Example
---------------

.. literalinclude:: ./samples/snapshot-status-reset-request.json
   :language: javascript
