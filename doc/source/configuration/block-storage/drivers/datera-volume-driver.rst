==============
Datera drivers
==============

Datera iSCSI driver
-------------------

The Datera Elastic Data Fabric (EDF) is a scale-out storage software that
turns standard, commodity hardware into a RESTful API-driven, intent-based
policy controlled storage fabric for large-scale clouds. The Datera EDF
integrates seamlessly with the Block Storage service. It provides storage
through the iSCSI block protocol framework over the iSCSI block protocol.
Datera supports all of the Block Storage services.

System requirements, prerequisites, and recommendations
-------------------------------------------------------

Prerequisites
~~~~~~~~~~~~~

* Must be running compatible versions of OpenStack and Datera EDF.
  Please visit `here <https://github.com/Datera/cinder>`_ to determine the
  correct version.

* All nodes must have access to Datera EDF through the iSCSI block protocol.

* All nodes accessing the Datera EDF must have the following packages
  installed:

  * Linux I/O (LIO)
  * open-iscsi
  * open-iscsi-utils
  * wget

.. include:: ../../tables/cinder-datera.inc



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

* Create a new section for the Datera back-end definition. The ``san_ip`` can
  be either the Datera Management Network VIP or one of the Datera iSCSI
  Access Network VIPs depending on the network segregation requirements:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.datera.DateraDriver
   san_ip = <IP_ADDR>            # The OOB Management IP of the cluster
   san_login = admin             # Your cluster admin login
   san_password = password       # Your cluster admin password
   san_is_local = true
   datera_num_replicas = 3       # Number of replicas to use for volume

Enable the Datera volume driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Verify the OpenStack control node can reach the Datera ``san_ip``:

.. code-block:: bash

   $ ping -c 4 <san_IP>

* Start the Block Storage service on all nodes running the ``cinder-volume``
  services:

.. code-block:: bash

   $ service cinder-volume restart

QoS support for the Datera drivers includes the ability to set the
following capabilities in QoS Specs

* **read_iops_max** -- must be positive integer

* **write_iops_max** -- must be positive integer

* **total_iops_max** -- must be positive integer

* **read_bandwidth_max** -- in KB per second, must be positive integer

* **write_bandwidth_max** -- in KB per second, must be positive integer

* **total_bandwidth_max** -- in KB per second, must be positive integer

.. code-block:: bash

   # Create qos spec
   $ openstack volume qos create --property total_iops_max=1000 total_bandwidth_max=2000 DateraBronze

   # Associate qos-spec with volume type
   $ openstack volume qos associate DateraBronze VOLUME_TYPE

   # Add additional qos values or update existing ones
   $ openstack volume qos set --property read_bandwidth_max=500 DateraBronze

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

The following configuration is for 3.X Linux kernels, some parameters in
different Linux distributions may be different. Make the following changes
in the ``multipath.conf`` file:

.. code-block:: text

    defaults {
    checker_timer 5
    }
    devices {
        device {
            vendor "DATERA"
            product "IBLOCK"
            getuid_callout "/lib/udev/scsi_id --whitelisted –
            replace-whitespace --page=0x80 --device=/dev/%n"
            path_grouping_policy group_by_prio
            path_checker tur
            prio alua
            path_selector "queue-length 0"
            hardware_handler "1 alua"
            failback 5
        }
    }
    blacklist {
        device {
            vendor ".*"
            product ".*"
        }
    }
    blacklist_exceptions {
        device {
            vendor "DATERA.*"
            product "IBLOCK.*"
        }
    }

