================================
HPE LeftHand/StoreVirtual driver
================================

The ``HPELeftHandISCSIDriver`` is based on the Block Storage service plug-in
architecture. Volume operations are run by communicating with the HPE
LeftHand/StoreVirtual system over HTTPS, or SSH connections. HTTPS
communications use the ``python-lefthandclient``, which is part of the Python
standard library.

The ``HPELeftHandISCSIDriver`` can be configured to run using a REST client to
communicate with the array. For performance improvements and new functionality
the ``python-lefthandclient`` must be downloaded, and HP LeftHand/StoreVirtual
Operating System software version 11.5 or higher is required on the array. To
configure the driver in standard mode, see
`HPE LeftHand/StoreVirtual REST driver`_.

For information about how to manage HPE LeftHand/StoreVirtual storage systems,
see the HPE LeftHand/StoreVirtual user documentation.

HPE LeftHand/StoreVirtual REST driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section describes how to configure the HPE LeftHand/StoreVirtual Block
Storage driver.

System requirements
-------------------

To use the HPE LeftHand/StoreVirtual driver, do the following:

* Install LeftHand/StoreVirtual Operating System software version 11.5 or
  higher on the HPE LeftHand/StoreVirtual storage system.

* Create a cluster group.

* Install the ``python-lefthandclient`` version 2.1.0 from the Python Package
  Index on the system with the enabled Block Storage service
  volume drivers.

Supported operations
--------------------

* Create, delete, attach, and detach volumes.

* Create, list, and delete volume snapshots.

* Create a volume from a snapshot.

* Copy an image to a volume.

* Copy a volume to an image.

* Clone a volume.

* Extend a volume.

* Get volume statistics.

* Migrate a volume with back-end assistance.

* Retype a volume.

* Manage and unmanage a volume.

* Manage and unmanage a snapshot.

* Replicate host volumes.

* Fail-over host volumes.

* Fail-back host volumes.

* Create, delete, update, snapshot, and clone generic volume groups.

* Create and delete generic volume group snapshots.

* Create a generic volume group from a group snapshot or another group.

When you use back end assisted volume migration, both source and destination
clusters must be in the same HPE LeftHand/StoreVirtual management group.
The HPE LeftHand/StoreVirtual array will use native LeftHand APIs to migrate
the volume. The volume cannot be attached or have snapshots to migrate.

Volume type support for the driver includes the ability to set the
following capabilities in the Block Storage API
``cinder.api.contrib.types_extra_specs`` volume type extra specs
extension module.

* ``hpelh:provisioning``

* ``hpelh:ao``

* ``hpelh:data_pl``

To work with the default filter scheduler, the key-value pairs are
case-sensitive and scoped with ``hpelh:``. For information about how to set
the key-value pairs and associate them with a volume type, run the following
command:

.. code-block:: console

   $ openstack help volume type

* The following keys require the HPE LeftHand/StoreVirtual storage
  array be configured for:

  ``hpelh:ao``
    The HPE LeftHand/StoreVirtual storage array must be configured for
    Adaptive Optimization.

  ``hpelh:data_pl``
    The HPE LeftHand/StoreVirtual storage array must be able to support the
    Data Protection level specified by the extra spec.

* If volume types are not used or a particular key is not set for a volume
  type, the following defaults are used:

  ``hpelh:provisioning``
    Defaults to ``thin`` provisioning, the valid values are, ``thin`` and
    ``full``

  ``hpelh:ao``
    Defaults to ``true``, the valid values are, ``true`` and ``false``.

  ``hpelh:data_pl``
    Defaults to ``r-0``, Network RAID-0 (None), the valid values are,

    * ``r-0``, Network RAID-0 (None)

    * ``r-5``, Network RAID-5 (Single Parity)

    * ``r-10-2``, Network RAID-10 (2-Way Mirror)

    * ``r-10-3``, Network RAID-10 (3-Way Mirror)

    * ``r-10-4``, Network RAID-10 (4-Way Mirror)

    * ``r-6``, Network RAID-6 (Dual Parity)

Enable the HPE LeftHand/StoreVirtual iSCSI driver
-------------------------------------------------

The ``HPELeftHandISCSIDriver`` is installed with the OpenStack software.

#. Install the ``python-lefthandclient`` Python package on the OpenStack Block
   Storage system.

   .. code-block:: console

      $ pip install 'python-lefthandclient>=2.1,<3.0'

#. If you are not using an existing cluster, create a cluster on the HPE
   LeftHand storage system to be used as the cluster for creating volumes.

#. Make the following changes in the ``/etc/cinder/cinder.conf`` file:

   .. code-block:: ini

      # LeftHand WS API Server URL
      hpelefthand_api_url=https://10.10.0.141:8081/lhos

      # LeftHand Super user username
      hpelefthand_username=lhuser

      # LeftHand Super user password
      hpelefthand_password=lhpass

      # LeftHand cluster to use for volume creation
      hpelefthand_clustername=ClusterLefthand

      # LeftHand iSCSI driver
      volume_driver=cinder.volume.drivers.hpe.hpe_lefthand_iscsi.HPELeftHandISCSIDriver

      # Should CHAPS authentication be used (default=false)
      hpelefthand_iscsi_chap_enabled=false

      # Enable HTTP debugging to LeftHand (default=false)
      hpelefthand_debug=false

      # The ratio of oversubscription when thin provisioned volumes are
      # involved. Default ratio is 20.0, this means that a provisioned capacity
      # can be 20 times of the total physical capacity.
      max_over_subscription_ratio=20.0

      # This flag represents the percentage of reserved back-end capacity.
      reserved_percentage=15

   You can enable only one driver on each cinder instance unless you enable
   multiple back end support. See the Cinder multiple back end support
   instructions to enable this feature.

   If the ``hpelefthand_iscsi_chap_enabled`` is set to ``true``, the driver
   will associate randomly-generated CHAP secrets with all hosts on the HPE
   LeftHand/StoreVirtual system. OpenStack Compute nodes use these secrets
   when creating iSCSI connections.

   .. important::

      CHAP secrets are passed from OpenStack Block Storage to Compute in clear
      text. This communication should be secured to ensure that CHAP secrets
      are not discovered.

   .. note::

      CHAP secrets are added to existing hosts as well as newly-created ones.
      If the CHAP option is enabled, hosts will not be able to access the
      storage without the generated secrets.

#. Save the changes to the ``cinder.conf`` file and restart the
   ``cinder-volume`` service.

The HPE LeftHand/StoreVirtual driver is now enabled on your OpenStack system.
If you experience problems, review the Block Storage service log files for
errors.

.. note::
   Previous versions implement a HPE LeftHand/StoreVirtual CLIQ driver that
   enable the Block Storage service driver configuration in legacy mode. This
   is removed from Mitaka onwards.
