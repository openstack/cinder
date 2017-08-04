==========================
Synology DSM volume driver
==========================

The ``SynoISCSIDriver`` volume driver allows Synology NAS to be used for Block
Storage (cinder) in OpenStack deployments. Information on OpenStack Block
Storage volumes is available in the DSM Storage Manager.

System requirements
~~~~~~~~~~~~~~~~~~~

The Synology driver has the following requirements:

* DSM version 6.0.2 or later.

* Your Synology NAS model must support advanced file LUN, iSCSI Target, and
  snapshot features. Refer to the `Support List for applied models
  <https://www.synology.com/en-global/dsm/6.0/iSCSI_virtualization#OpenStack>`_.

.. note::

   The DSM driver is available in the OpenStack Newton release.


Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, clone, attach, and detach volumes.

* Create and delete volume snapshots.

* Create a volume from a snapshot.

* Copy an image to a volume.

* Copy a volume to an image.

* Extend a volume.

* Get volume statistics.

Driver configuration
~~~~~~~~~~~~~~~~~~~~

Edit the ``/etc/cinder/cinder.conf`` file on your volume driver host.

Synology driver uses a volume in Synology NAS as the back end of Block Storage.
Every time you create a new Block Storage volume, the system will create an
advanced file LUN in your Synology volume to be used for this new Block Storage
volume.

The following example shows how to use different Synology NAS servers as the
back end. If you want to use all volumes on your Synology NAS, add another
section with the volume number to differentiate between volumes within the same
Synology NAS.

.. code-block:: ini

   [default]
   enabled_backends = ds1515pV1, ds1515pV2, rs3017xsV3, others

   [ds1515pV1]
   # configuration for volume 1 in DS1515+

   [ds1515pV2]
   # configuration for volume 2 in DS1515+

   [rs3017xsV1]
   # configuration for volume 1 in RS3017xs

Each section indicates the volume number and the way in which the connection is
established. Below is an example of a basic configuration:

.. code-block:: ini

   [Your_Section_Name]

   # Required settings
   volume_driver = cinder.volume.drivers.synology.synology_iscsi.SynoISCSIDriver
   iscs_protocol = iscsi
   iscsi_ip_address = DS_IP
   synology_admin_port = DS_PORT
   synology_username = DS_USER
   synology_password = DS_PW
   synology_pool_name = DS_VOLUME

   # Optional settings
   volume_backend_name = VOLUME_BACKEND_NAME
   iscsi_secondary_ip_addresses = IP_ADDRESSES
   driver_use_ssl = True
   use_chap_auth = True
   chap_username = CHAP_USER_NAME
   chap_password = CHAP_PASSWORD

``DS_PORT``
    This is the port for DSM management. The default value for DSM is 5000
    (HTTP) and 5001 (HTTPS). To use HTTPS connections, you must set
    ``driver_use_ssl = True``.

``DS_IP``
    This is the IP address of your Synology NAS.

``DS_USER``
    This is the account of any DSM administrator.

``DS_PW``
    This is the password for ``DS_USER``.

``DS_VOLUME``
    This is the volume you want to use as the storage pool for the Block
    Storage service. The format is ``volume[0-9]+``, and the number is the same
    as the volume number in DSM.

.. note::

   If you set ``driver_use_ssl`` as ``True``, ``synology_admin_port`` must be
   an HTTPS port.

Configuration options
~~~~~~~~~~~~~~~~~~~~~

The Synology DSM driver supports the following configuration options:

.. include:: ../../tables/cinder-synology.inc
