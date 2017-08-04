=======================================================
FalconStor FSS Storage Fibre Channel and iSCSI drivers
=======================================================

The ``FSSISCSIDriver`` and ``FSSFCDriver`` drivers run volume operations
by communicating with the FalconStor FSS storage system over HTTP.

System requirements
~~~~~~~~~~~~~~~~~~~

To use the FalconStor FSS drivers, the following are required:

-  FalconStor FSS storage with:

   -  iSCSI or FC host interfaces

   -  FSS-8.00-8865 or later

Supported operations
~~~~~~~~~~~~~~~~~~~~

The FalconStor volume driver provides the following Cinder
volume operations:

*  Create, delete, attach, and detach volumes.

*  Create, list, and delete volume snapshots.

*  Create a volume from a snapshot.

*  Clone a volume.

*  Extend a volume.

*  Get volume statistics.

*  Create and delete consistency group.

*  Create and delete consistency group snapshots.

*  Modify consistency groups.

*  Manage and unmanage a volume.

iSCSI configuration
~~~~~~~~~~~~~~~~~~~

Use the following instructions to update the configuration file for iSCSI:

.. code-block:: ini

    default_volume_type = FSS
    enabled_backends = FSS

    [FSS]

    # IP address of FSS server
    san_ip = 172.23.0.1
    # FSS server user name
    san_login = Admin
    # FSS server password
    san_password = secret
    # FSS server storage pool id list
    fss_pools=P:2,O:3
    # Name to give this storage back-end
    volume_backend_name = FSSISCSIDriver
    # The iSCSI driver to load
    volume_driver = cinder.volume.drivers.falconstor.iscsi.FSSISCSIDriver


    # ==Optional settings==

    # Enable FSS log message
    fss_debug = true
    # Enable FSS thin provision
    san_thin_provision=true

Fibre Channel configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the following instructions to update the configuration file for fibre
channel:

.. code-block:: ini

    default_volume_type = FSSFC
    enabled_backends = FSSFC

    [FSSFC]
    # IP address of FSS server
    san_ip = 172.23.0.2
    # FSS server user name
    san_login = Admin
    # FSS server password
    san_password = secret
    # FSS server storage pool id list
    fss_pools=A:1
    # Name to give this storage back-end
    volume_backend_name = FSSFCDriver
    # The FC driver to load
    volume_driver = cinder.volume.drivers.falconstor.fc.FSSFCDriver


    # ==Optional settings==

    # Enable FSS log message
    fss_debug = true
    # Enable FSS thin provision
    san_thin_provision=true

Driver options
~~~~~~~~~~~~~~

The following table contains the configuration options specific to the
FalconStor FSS storage volume driver.

.. include:: ../../tables/cinder-falconstor.inc
