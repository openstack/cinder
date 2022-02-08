:tocdepth: 2

==============================
Block Storage API V3 (CURRENT)
==============================

.. note::
   The URL for most API methods includes a {project_id} placeholder that
   represents the caller's project ID. As of V3.67, the project_id is optional
   in the URL, and the following are equivalent:

      * GET /v3/{project_id}/volumes
      * GET /v3/volumes

   In both instances, the actual project_id used by the API method is the one
   in the caller's keystone context. For that reason, including a project_id
   in the URL is redundant.

   The V3.67 microversion is only used as an indicator that the API accepts a
   URL without a project_id, and this applies to all requests regardless of
   the microversion in the request. For example, an API node serving V3.67 or
   greater will accept a URL without a project_id even if the request asks for
   V3.0. Likewise, it will accept a URL containing a project_id even if the
   request asks for V3.67.

.. rest_expand_all::

.. First thing we want to see is the version discovery document.
.. include:: api-versions.inc
.. include:: volumes-v3-versions.inc

.. Next top-level thing could be listing extensions available on this endpoint.
.. include:: volumes-v3-extensions.inc

.. To create a volume, I might need a volume type, so list those next.
.. include:: volumes-v3-types.inc
.. include:: volume-type-access.inc
.. include:: default-types.inc

.. Now my primary focus is on volumes and what I can do with them.
.. include:: volumes-v3-volumes.inc
.. include:: volumes-v3-volumes-actions.inc

.. List the other random volume APIs in just alphabetical order.
.. include:: volume-manage.inc
.. include:: volumes-v3-snapshots.inc
.. include:: volumes-v3-snapshots-actions.inc
.. include:: snapshot-manage.inc
.. include:: os-vol-transfer-v3.inc
.. include:: vol-transfer-v3.inc

.. Now the other random things in alphabetical order.
.. include:: attachments.inc
.. include:: os-vol-pool-v3.inc
.. include:: ext-backups.inc
.. include:: ext-backups-actions-v3.inc
.. include:: capabilities-v3.inc
.. include:: consistencygroups-v3.inc
.. include:: os-cgsnapshots-v3.inc
.. include:: os-services.inc
.. include:: groups.inc
.. include:: group-replication.inc
.. include:: group-snapshots.inc
.. include:: group-types.inc
.. include:: group-type-specs.inc
.. include:: hosts.inc
.. include:: limits.inc
.. include:: messages.inc
.. include:: resource-filters.inc
.. include:: qos-specs-v3-qos-specs.inc
.. quota-sets should arguably live closer to limits, but that would mess up
   our nice alphabetical ordering
.. include:: quota-classes.inc
.. include:: quota-sets.inc
.. include:: worker-cleanup.inc

.. valid values for boolean parameters.
.. include:: valid-boolean-values.inc
