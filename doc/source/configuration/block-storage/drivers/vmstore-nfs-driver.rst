=====================================
VMstore Openstack Cinder Driver (NFS)
=====================================

Compatibility Matrix
====================

================== ==================
Vmstore version    CSI driver version
================== ==================
>=6.0.1.1          >=3.0.2
================== ==================

Prerequisites
=============

Install NFS client::

    apt install nfs-common

Installation
============
Configure ``/etc/cinder/cinder.conf`` to use the Vmstore cinder driver.

Example configuration::

    [DEFAULT]
    default_volume_type = vmstore
    enabled_backends = vmstore

    [vmstore]
    volume_driver = cinder.volume.drivers.vmstore.nfs.VmstoreNfsDriver
    nas_host = <VMstoreDataIP>
    nas_share_path = <VMstoreSharePath>  # example: /tintri/cinder
    nfs_mount_options = vers=3
    vmstore_user = <VMstore_UserName>
    vmstore_password = <VMstore_Password>
    vmstore_rest_address = <VMstoreAdminIP, or FQDN>
    volume_backend_name = vmstore
    vmstore_qcow2_volumes = False

Configuration Parameters
========================

.. list-table::
   :header-rows: 1
   :widths: 25 10 15 10 40

   * - Configuration Option
     - Type
     - Default Value
     - Required
     - Description
   * - ``vmstore_rest_address``
     - String
     - \-
     - yes
     - IP address or hostname for management communication with Vmstore REST API interface.
   * - ``vmstore_rest_protocol``
     - String
     - ``https``
     - no
     - Vmstore RESTful API interface protocol.
   * - ``vmstore_rest_port``
     - Integer
     - ``443``
     - no
     - Vmstore RESTful API interface port.
   * - ``nas_host``
     - String
     - \-
     - yes
     - Vmstore data IP for volume mount, IO operations.
   * - ``vmstore_user``
     - String
     - ``2240``
     - yes
     - Username to connect to Vmstore REST API interface.
   * - ``vmstore_password``
     - String
     - \-
     - yes
     - User password to connect to Vmstore RESTful API interface.
   * - ``vmstore_rest_connect_timeout``
     - Float
     - ``30``
     - no
     - Specifies the time limit (in seconds) to establish connection to Vmstore REST API interface.
   * - ``vmstore_rest_read_timeout``
     - Float
     - ``300``
     - no
     - Specifies the time limit (in seconds) for Vmstore REST API interface to send a response.
   * - ``vmstore_rest_backoff_factor``
     - Float
     - ``1``
     - no
     - Specifies the backoff factor to apply between connection attempts to Vmstore REST API interface.
   * - ``vmstore_rest_retry_count``
     - Int
     - ``5``
     - no
     - Specifies the number of times to repeat Vmstore REST API calls in case of connection errors or retriable errors.
   * - ``vmstore_refresh_retry_count``
     - Int
     - ``1``
     - no
     - Specifies the number of times to repeat Vmstore RESTful API call to cinder/host/refresh in case of connection errors or Vmstore appliance retriable errors.
   * - ``vmstore_qcow2_volumes``
     - Boolean
     - ``False``
     - no
     - Use qcow2 volumes.
   * - ``vmstore_mount_point_base``
     - String
     - ``$state_path/mnt``
     - no
     - Base directory containing NFS share mount points.
   * - ``vmstore_sparsed_volumes``
     - Boolean
     - ``True``
     - no
     - Defines whether the volumes need to be thin-provisioned.
   * - ``vmstore_dataset_description``
     - String
     - \-
     - no
     - Human-readable description for the backend.
   * - ``vmstore_refresh_openstack_region``
     - String
     - ``RegionOne``
     - no
     - OpenStack region for Vmstore hypervisor refresh call.
   * - ``vmstore_openstack_hostname``
     - String
     - \-
     - no
     - OpenStack controller hostname or IP. Used for VMstore hypervisor refresh. If not set, attempts to resolve from Keystone config.


Creating Volume Types
=====================

.. code-block:: console

   $ openstack volume type create vmstore
   $ openstack volume type set --property volume_backend_name=vmstore vmstore
