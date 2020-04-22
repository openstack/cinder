==============
Datera drivers
==============

Datera iSCSI driver
-------------------

The Datera Data Services Platform (DSP) is a scale-out storage software that
turns standard, commodity hardware into a RESTful API-driven, intent-based
policy controlled storage fabric for large-scale clouds. The Datera DSP
integrates seamlessly with the Block Storage service. It provides storage
through the iSCSI block protocol framework over the iSCSI block protocol.
Datera supports all of the Block Storage services.

System requirements, prerequisites, and recommendations
-------------------------------------------------------

Prerequisites
~~~~~~~~~~~~~

* All nodes must have access to Datera DSP through the iSCSI block protocol.

* All nodes accessing the Datera DSP must have the following packages
  installed:

  * Linux I/O (LIO)
  * open-iscsi
  * open-iscsi-utils
  * wget

.. config-table::
   :config-target: Datera

   cinder.volume.drivers.datera.datera_iscsi

Configuring the Datera volume driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Modify the ``/etc/cinder/cinder.conf`` file for Block Storage service.

* Enable the Datera volume driver:

.. code-block:: ini

   [DEFAULT]
   # ...
   enabled_backends = datera
   # ...

* Optional. Designate Datera as the default back-end:

.. code-block:: ini

   default_volume_type = datera

* Create a new section for the Datera back-end definition. The ``VIP`` can
  be either the Datera Management Network VIP or one of the Datera iSCSI
  Access Network VIPs depending on the network segregation requirements. For
  a complete list of parameters that can be configured, please see the
  section `Volume Driver Cinder.conf Options <https://github.com/Datera/cinder-driver/blob/master/README.rst#volume-driver-cinderconf-options>`_

.. code-block:: ini

  [datera]
  volume_driver = cinder.volume.drivers.datera.datera_iscsi.DateraDriver
  san_ip = <VIP>
  san_login = admin
  san_password = password
  datera_tenant_id =
  volume_backend_name = datera
  datera_volume_type_defaults=replica_count:3

Enable the Datera volume driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Verify the OpenStack control node can reach the Datera ``VIP``:

.. code-block:: bash

   $ ping -c 4 <VIP>

* Start the Block Storage service on all nodes running the ``cinder-volume``
  services:

.. code-block:: bash

   $ service cinder-volume restart

Configuring one (or more) Datera specific volume types
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There are extra volume type parameters that can be used to define Datera volume
types with specific QoS policies (R/W IOPS, R/W bandwidth) and/or placement
policies (replica count, type of media, IP pool to use, etc.)

For a full list of supported options please see the `Volume-Type ExtraSpecs
<https://github.com/Datera/cinder-driver/blob/master/README.rst#volume-type-extraspecs>`_
section in the driver documentation.  See more examples in the `Usage
<https://github.com/Datera/cinder-driver/blob/master/README.rst#usage>`_
section.

.. code-block:: bash

   # Create 2 replica volume type
   $ openstack volume type create datera_2way --property volume_backend_name=datera --property DF:replica_count=2

   # Create volume type with limited write IOPS
   $ openstack volume type create datera_iops --property volume_backend_name=datera --property DF:write_iops_max=5000


Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, attach, detach, manage, unmanage, and list volumes.

* Create, list, and delete volume snapshots.

* Create a volume from a snapshot.

* Copy an image to a volume.

* Copy a volume to an image.

* Clone a volume.

* Extend a volume.

* Support for naming convention changes.

Configuring multipathing
~~~~~~~~~~~~~~~~~~~~~~~~

Enabling multipathing is strongly reccomended for reliability and availability
reasons.  Please refer to the following `file
<https://github.com/Datera/datera-csi/blob/master/assets/multipath.conf>`_ for
an example of configuring multipathing in Linux 3.x kernels.  Some parameters
in different Linux distributions may be different.
