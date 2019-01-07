========================
DRBD driver (Deprecated)
========================

The DRBD driver allows Cinder to use DRBDmanage instances.

.. note::
   The LINBIT DRBDManage volume driver is moving to maintenance mode in Stein
   Release and will be removed in T Release.

Configuration
~~~~~~~~~~~~~

Set the following option in the ``cinder.conf`` file for the DRBD transport:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.drbdmanagedrv.DrbdManageDrbdDriver

Or use the following for iSCSI transport:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.drbdmanagedrv.DrbdManageIscsiDriver


The following table contains the configuration options supported by the
DRBD drivers:

.. config-table::
   :config-target: DRBD

   cinder.volume.drivers.drbdmanagedrv
