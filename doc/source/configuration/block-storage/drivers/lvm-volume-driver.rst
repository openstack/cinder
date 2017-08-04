===
LVM
===

The default volume back end uses local volumes managed by LVM.

This driver supports different transport protocols to attach volumes,
currently iSCSI and iSER.

Set the following in your ``cinder.conf`` configuration file, and use
the following options to configure for iSCSI transport:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver
   iscsi_protocol = iscsi

Use the following options to configure for the iSER transport:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver
   iscsi_protocol = iser

.. include:: ../../tables/cinder-lvm.inc

.. caution::

    When extending an existing volume which has a linked snapshot, the related
    logical volume is deactivated. This logical volume is automatically
    reactivated unless ``auto_activation_volume_list`` is defined in LVM
    configuration file ``lvm.conf``. See the ``lvm.conf`` file for more
    information.

    If auto activated volumes are restricted, then include the cinder volume
    group into this list:

    .. code-block:: ini

        auto_activation_volume_list = [ "existingVG", "cinder-volumes" ]

    This note does not apply for thinly provisioned volumes
    because they do not need to be deactivated.
