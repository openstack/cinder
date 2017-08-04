=========
SolidFire
=========

The SolidFire Cluster is a high performance all SSD iSCSI storage device that
provides massive scale out capability and extreme fault tolerance.  A key
feature of the SolidFire cluster is the ability to set and modify during
operation specific QoS levels on a volume for volume basis. The SolidFire
cluster offers this along with de-duplication, compression, and an architecture
that takes full advantage of SSDs.

To configure the use of a SolidFire cluster with Block Storage, modify your
``cinder.conf`` file as follows:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.solidfire.SolidFireDriver
   san_ip = 172.17.1.182         # the address of your MVIP
   san_login = sfadmin           # your cluster admin login
   san_password = sfpassword     # your cluster admin password
   sf_account_prefix = ''        # prefix for tenant account creation on solidfire cluster

.. warning::

   Older versions of the SolidFire driver (prior to Icehouse) created a unique
   account prefixed with ``$cinder-volume-service-hostname-$tenant-id`` on the
   SolidFire cluster for each tenant. Unfortunately, this account formation
   resulted in issues for High Availability (HA) installations and
   installations where the ``cinder-volume`` service can move to a new node.
   The current default implementation does not experience this issue as no
   prefix is used. For installations created on a prior release, the OLD
   default behavior can be configured by using the keyword ``hostname`` in
   sf_account_prefix.

.. note::

   The SolidFire driver creates names for volumes on the back end using the
   format UUID-<cinder-id>. This works well, but there is a possibility of a
   UUID collision for customers running multiple clouds against the same
   cluster. In Mitaka the ability was added to eliminate the possibility of
   collisions by introducing the **sf_volume_prefix** configuration variable.
   On the SolidFire cluster each volume will be labeled with the prefix,
   providing the ability to configure unique volume names for each cloud.
   The default prefix is 'UUID-'.

   Changing the setting on an existing deployment will result in the existing
   volumes being inaccessible. To introduce this change to an existing
   deployment it is recommended to add the Cluster as if it were a second
   backend and disable new deployments to the current back end.

.. include:: ../../tables/cinder-solidfire.inc

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, attach, and detach volumes.
* Create, list, and delete volume snapshots.
* Create a volume from a snapshot.
* Copy an image to a volume.
* Copy a volume to an image.
* Clone a volume.
* Extend a volume.
* Retype a volume.
* Manage and unmanage a volume.
* Consistency group snapshots.

QoS support for the SolidFire drivers includes the ability to set the
following capabilities in the OpenStack Block Storage API
``cinder.api.contrib.qos_specs_manage`` qos specs extension module:

* **minIOPS** - The minimum number of IOPS guaranteed for this volume.
  Default = 100.

* **maxIOPS** - The maximum number of IOPS allowed for this volume.
  Default = 15,000.

* **burstIOPS** - The maximum number of IOPS allowed over a short period of
  time. Default = 15,000.

* **scaledIOPS** - The presence of this key is a flag indicating that the
  above IOPS should be scaled by the following scale values. It is recommended
  to set the value of scaledIOPS to True, but any value will work. The
  absence of this key implies false.

* **scaleMin** - The amount to scale the minIOPS by for every 1GB of
  additional volume size. The value must be an integer.

* **scaleMax** - The amount to scale the maxIOPS by for every 1GB of additional
  volume size. The value must be an integer.

* **scaleBurst** - The amount to scale the burstIOPS by for every 1GB of
  additional volume size. The value must be an integer.

The QoS keys above no longer require to be scoped but must be created and
associated to a volume type. For information about how to set the key-value
pairs and associate them with a volume type, see the `volume qos
<https://docs.openstack.org/developer/python-openstackclient/command-objects/volume-qos.html>`_
section in the OpenStackClient command list.

.. note::

  When using scaledIOPS, the scale values must be chosen such that the
  constraint minIOPS <= maxIOPS <= burstIOPS is always true. The driver will
  enforce this constraint.
