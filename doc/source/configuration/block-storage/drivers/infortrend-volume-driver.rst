========================
Infortrend volume driver
========================

The `Infortrend <http://www.infortrend.com/global>`__ volume driver is a Block Storage driver
providing iSCSI and Fibre Channel support for Infortrend storages.

Supported operations
~~~~~~~~~~~~~~~~~~~~

The Infortrend volume driver supports the following volume operations:

* Create, delete, attach, and detach volumes.
* Create and delete a snapshot.
* Create a volume from a snapshot.
* Copy an image to a volume.
* Copy a volume to an image.
* Clone a volume.
* Extend a volume
* Retype a volume.
* Manage and unmanage a volume.
* Migrate a volume with back-end assistance.
* Live migrate an instance with volumes hosted on an Infortrend backend.

System requirements
~~~~~~~~~~~~~~~~~~~

To use the Infortrend volume driver, the following settings are required:

Set up Infortrend storage
-------------------------

* Create logical volumes in advance.
* Host side setting ``Peripheral device type`` should be
  ``No Device Present (Type=0x7f)``.

Set up cinder-volume node
-------------------------

* Install Oracle Java 7 or later.

* Download the Infortrend storage CLI from the
  `release page <https://github.com/infortrend-openstack/infortrend-cinder-driver/releases>`__,
  and assign it to the default path ``/opt/bin/Infortrend/``.

Driver configuration
~~~~~~~~~~~~~~~~~~~~

On ``cinder-volume`` nodes, set the following in your
``/etc/cinder/cinder.conf``, and use the following options to configure it:

Driver options
--------------

.. include:: ../../tables/cinder-infortrend.inc

iSCSI configuration example
---------------------------

.. code-block:: ini

   [DEFAULT]
   default_volume_type = IFT-ISCSI
   enabled_backends = IFT-ISCSI

   [IFT-ISCSI]
   volume_driver = cinder.volume.drivers.infortrend.infortrend_iscsi_cli.InfortrendCLIISCSIDriver
   volume_backend_name = IFT-ISCSI
   infortrend_pools_name = POOL-1,POOL-2
   san_ip = MANAGEMENT_PORT_IP
   infortrend_slots_a_channels_id = 0,1,2,3
   infortrend_slots_b_channels_id = 0,1,2,3

Fibre Channel configuration example
-----------------------------------

.. code-block:: ini

   [DEFAULT]
   default_volume_type = IFT-FC
   enabled_backends = IFT-FC

   [IFT-FC]
   volume_driver = cinder.volume.drivers.infortrend.infortrend_fc_cli.InfortrendCLIFCDriver
   volume_backend_name = IFT-FC
   infortrend_pools_name = POOL-1,POOL-2,POOL-3
   san_ip = MANAGEMENT_PORT_IP
   infortrend_slots_a_channels_id = 4,5

Multipath configuration
-----------------------

* Enable multipath for image transfer in ``/etc/cinder/cinder.conf``.

  .. code-block:: ini

     use_multipath_for_image_xfer = True

  Restart the ``cinder-volume`` service.

* Enable multipath for volume attach and detach in ``/etc/nova/nova.conf``.

  .. code-block:: ini

     [libvirt]
     ...
     volume_use_multipath = True
     ...

  Restart the ``nova-compute`` service.

Extra spec usage
----------------

* ``infortrend:provisioning`` - Defaults to ``full`` provisioning,
  the valid values are thin and full.

* ``infortrend:tiering`` - Defaults to use ``all`` tiering,
  the valid values are subsets of 0, 1, 2, 3.

  If multi-pools are configured in ``cinder.conf``,
  it can be specified for each pool, separated by semicolon.

  For example:

  ``infortrend:provisioning``: ``POOL-1:thin; POOL-2:full``

  ``infortrend:tiering``: ``POOL-1:all; POOL-2:0; POOL-3:0,1,3``

For more details, see `Infortrend documents <http://www.infortrend.com/ImageLoader/LoadDoc/715>`_.
