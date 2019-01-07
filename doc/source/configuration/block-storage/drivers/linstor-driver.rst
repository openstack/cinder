==============
LINSTOR driver
==============

The LINSTOR driver allows Cinder to use DRBD/LINSTOR instances.

Configuration
~~~~~~~~~~~~~

Set the following option in the ``cinder.conf`` file for the DRBD transport:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.linstordrv.LinstorDrbdDriver

Or use the following for iSCSI transport:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.linstordrv.LinstorIscsiDriver


The following table contains the configuration options supported by the
LINSTOR driver:

.. config-table::
   :config-target: LINSTOR

   cinder.volume.drivers.linstordrv
