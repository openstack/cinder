======================
SandStone iSCSI Driver
======================

SandStone USP volume can be used as a block storage resource in
the OpenStack Block Storage driver that supports iSCSI protocols.

Before to go,  you should have installed `SandStoneUSP <http:
//www.szsandstone.com>`_.

System requirements
~~~~~~~~~~~~~~~~~~~

+-----------------+--------------------+
| Cluster         | version            |
+=================+====================+
| SandStone USP   | 3.2.3+             |
+-----------------+--------------------+

To use the SandStone driver, the following are required:

- Network connectivity between the OpenStack host and the SandStone
  USP management interfaces.

- HTTPS or HTTP must be enabled on the array.

When creating a volume from image, add the following
configuration keys in the ``[DEFAULT]``
configuration group of the ``/etc/cinder/cinder.conf`` file:

Configuration example
~~~~~~~~~~~~~~~~~~~~~

The following table contains the configuration options supported by
the SandStone driver.

.. code-block:: ini

   [DEFAULT]
   enabled_backends = sds-iscsi

   [sds-iscsi]
   volume_driver = cinder.volume.drivers.sandstone.sds_driver.SdsISCSIDriver
   volume_backend_name = sds-iscsi
   san_ip = 10.10.16.21
   san_login = admin
   san_password = admin
   default_sandstone_target_ips = 10.10.16.21,10.10.16.22,10.10.16.23
   chap_username = 123456789123
   chap_password = 1234567891234
   sandstone_pool = vms
   initiator_assign_sandstone_target_ip = {"iqn.1993-08.org.debian:01:3a9cd5c484a": "10.10.16.21"}

General parameters
~~~~~~~~~~~~~~~~~~

+----------------------+-------------------------------------+
| Parameter            | Description                         |
+======================+=====================================+
| volume_driver        | Indicates the loaded driver         |
+----------------------+-------------------------------------+
| volume_backend_name  | Indicates the name of the backend   |
+----------------------+-------------------------------------+
| san_ip               | IP addresses of the management      |
|                      | interfaces of SandStone USP         |
+----------------------+-------------------------------------+
| san_login            | Storage system user name            |
+----------------------+-------------------------------------+
| san_password         | Storage system password             |
+----------------------+-------------------------------------+
| default_sandstone    | Default IP address of the iSCSI     |
| _target_ips          | target port that is provided for    |
|                      | compute nodes                       |
+----------------------+-------------------------------------+
| chap_username        | CHAP authentication username        |
+----------------------+-------------------------------------+
| chap_password        | CHAP authentication password        |
+----------------------+-------------------------------------+
| sandstone_pool       | SandStone storage pool resource name|
+----------------------+-------------------------------------+
| initiator_assign     | Initiator assign target with assign |
| _sandstone_target_ip | ip                                  |
+----------------------+-------------------------------------+


#. After modifying the ``cinder.conf`` file, restart the ``cinder-volume``
   service.

#. Create and use volume types.

   **Create and use sds-iscsi volume types**

   .. code-block:: console

      $ openstack volume type create sandstone
      $ openstack volume type set --property volume_backend_name=sds-iscsi sandstone
