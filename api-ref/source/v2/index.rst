:tocdepth: 2

==============================
Block Storage API V2 (REMOVED)
==============================

.. note::
    Version 2 of the Block Storage API was `deprecated in the Pike release
    <https://docs.openstack.org/releasenotes/cinder/pike.html#deprecation-notes>`_
    and was removed during the Xena development cycle.  `This document is
    maintained for historical purposes only.`

    `Version 3
    <https://docs.openstack.org/api-ref/block-storage/v3/>`_
    of the Block Storage API was `introduced in the Mitaka release
    <https://review.opendev.org/c/openstack/cinder/+/224910>`_.  Version
    3.0, which is the default microversion at the ``/v3`` endpoint, was
    designed to be identical to version 2.  Thus, scripts using the Block
    Storage API v2 should be adaptable to version 3 with minimal changes.


.. rest_expand_all::

.. include:: api-versions.inc
.. include:: ext-backups.inc
.. include:: ext-backups-actions-v2.inc
.. include:: capabilities-v2.inc
.. include:: os-cgsnapshots-v2.inc
.. include:: consistencygroups-v2.inc
.. include:: hosts.inc
.. include:: limits.inc
.. include:: os-vol-pool-v2.inc
.. include:: os-vol-transfer-v2.inc
.. include:: qos-specs-v2-qos-specs.inc
.. include:: quota-classes.inc
.. include:: quota-sets.inc
.. include:: volume-manage.inc
.. include:: volume-type-access.inc
.. include:: volumes-v2-extensions.inc
.. include:: volumes-v2-snapshots.inc
.. include:: volumes-v2-snapshots-actions.inc
.. include:: volumes-v2-types.inc
.. include:: volumes-v2-versions.inc
.. include:: volumes-v2-volumes-actions.inc
.. include:: volumes-v2-volumes.inc
