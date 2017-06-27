:tocdepth: 2

==============================
Block Storage API V3 (CURRENT)
==============================

.. rest_expand_all::

.. First thing we want to see is the version discovery document.
.. include:: api-versions.inc
.. include:: volumes-v3-versions.inc

.. Next top-level thing could be listing extensions available on this endpoint.
.. include:: volumes-v3-extensions.inc

.. To create a volume, I might need a volume type, so list those next.
.. include:: volumes-v3-types.inc
.. include:: volume-type-access.inc

.. Now my primary focus is on volumes and what I can do with them.
.. include:: volumes-v3-volumes.inc
.. include:: volumes-v3-volumes-actions.inc

.. List the other random volume APIs in just alphabetical order.
.. include:: volume-manage.inc
.. include:: volumes-v3-snapshots.inc
.. include:: snapshot-manage.inc
.. include:: os-vol-transfer-v3.inc

.. Now the other random things in alphabetical order.
.. include:: attachments.inc
.. include:: os-vol-pool-v3.inc
.. include:: ext-backups.inc
.. include:: ext-backups-actions-v3.inc
.. include:: capabilities-v3.inc
.. include:: consistencygroups-v3.inc
.. include:: os-cgsnapshots-v3.inc
.. include:: groups.inc
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
