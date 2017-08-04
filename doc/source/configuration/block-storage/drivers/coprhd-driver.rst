=====================================
CoprHD FC, iSCSI, and ScaleIO drivers
=====================================

CoprHD is an open source software-defined storage controller and API platform.
It enables policy-based management and cloud automation of storage resources
for block, object and file storage providers.
For more details, see `CoprHD <http://coprhd.org/>`_.

EMC ViPR Controller is the commercial offering of CoprHD. These same volume
drivers can also be considered as EMC ViPR Controller Block Storage drivers.


System requirements
~~~~~~~~~~~~~~~~~~~

CoprHD version 3.0 is required. Refer to the CoprHD documentation for
installation and configuration instructions.

If you are using these drivers to integrate with EMC ViPR Controller, use
EMC ViPR Controller 3.0.


Supported operations
~~~~~~~~~~~~~~~~~~~~

The following operations are supported:

- Create, delete, attach, detach, retype, clone, and extend volumes.
- Create, list, and delete volume snapshots.
- Create a volume from a snapshot.
- Copy a volume to an image.
- Copy an image to a volume.
- Clone a volume.
- Extend a volume.
- Retype a volume.
- Get volume statistics.
- Create, delete, and update consistency groups.
- Create and delete consistency group snapshots.


Driver options
~~~~~~~~~~~~~~

The following table contains the configuration options specific to the
CoprHD volume driver.

.. include:: ../../tables/cinder-coprhd.inc


Preparation
~~~~~~~~~~~

This involves setting up the CoprHD environment first and then configuring
the CoprHD Block Storage driver.

CoprHD
------

The CoprHD environment must meet specific configuration requirements to
support the OpenStack Block Storage driver.

- CoprHD users must be assigned a Tenant Administrator role or a Project
  Administrator role for the Project being used. CoprHD roles are configured
  by CoprHD Security Administrators. Consult the CoprHD documentation for
  details.

- A CorprHD system administrator must execute the following configurations
  using the CoprHD UI, CoprHD API, or CoprHD CLI:

  - Create CoprHD virtual array
  - Create CoprHD virtual storage pool
  - Virtual Array designated for iSCSI driver must have an IP network created
    with appropriate IP storage ports
  - Designated tenant for use
  - Designated project for use

.. note:: Use each back end to manage one virtual array and one virtual
          storage pool. However, the user can have multiple instances of
          CoprHD Block Storage driver, sharing the same virtual array and virtual
          storage pool.

- A typical CoprHD virtual storage pool will have the following values
  specified:

  - Storage Type: Block
  - Provisioning Type: Thin
  - Protocol: iSCSI/Fibre Channel(FC)/ScaleIO
  - Multi-Volume Consistency: DISABLED OR ENABLED
  - Maximum Native Snapshots: A value greater than 0 allows the OpenStack user
    to take Snapshots


CoprHD drivers - Single back end
--------------------------------

**cinder.conf**

#. Modify ``/etc/cinder/cinder.conf`` by adding the following lines,
   substituting values for your environment:

   .. code-block:: ini

    [coprhd-iscsi]
    volume_driver = cinder.volume.drivers.coprhd.iscsi.EMCCoprHDISCSIDriver
    volume_backend_name = coprhd-iscsi
    coprhd_hostname = <CoprHD-Host-Name>
    coprhd_port = 4443
    coprhd_username = <username>
    coprhd_password = <password>
    coprhd_tenant = <CoprHD-Tenant-Name>
    coprhd_project = <CoprHD-Project-Name>
    coprhd_varray = <CoprHD-Virtual-Array-Name>
    coprhd_emulate_snapshot = True or False, True if the CoprHD vpool has VMAX or VPLEX as the backing storage

#. If you use the ScaleIO back end, add the following lines:

   .. code-block:: ini

    coprhd_scaleio_rest_gateway_host = <IP or FQDN>
    coprhd_scaleio_rest_gateway_port = 443
    coprhd_scaleio_rest_server_username = <username>
    coprhd_scaleio_rest_server_password = <password>
    scaleio_verify_server_certificate = True or False
    scaleio_server_certificate_path = <path-of-certificate-for-validation>

#. Specify the driver using the ``enabled_backends`` parameter::

     enabled_backends = coprhd-iscsi

   .. note:: To utilize the Fibre Channel driver, replace the
             ``volume_driver`` line above with::

                 volume_driver = cinder.volume.drivers.coprhd.fc.EMCCoprHDFCDriver

   .. note:: To utilize the ScaleIO driver, replace the ``volume_driver`` line
             above with::

                 volume_driver = cinder.volume.drivers.coprhd.fc.EMCCoprHDScaleIODriver

   .. note:: Set ``coprhd_emulate_snapshot`` to True if the CoprHD vpool has
             VMAX or VPLEX as the back-end storage. For these type of back-end
             storages, when a user tries to create a snapshot, an actual volume
             gets created in the back end.

#. Modify the ``rpc_response_timeout`` value in ``/etc/cinder/cinder.conf`` to
   at least 5 minutes. If this entry does not already exist within the
   ``cinder.conf`` file, add it in the ``[DEFAULT]`` section:

   .. code-block:: ini

     [DEFAULT]
     # ...
     rpc_response_timeout = 300

#. Now, restart the ``cinder-volume`` service.

**Volume type creation and extra specs**

#. Create OpenStack volume types:

   .. code-block:: console

      $ openstack volume type create <typename>

#. Map the OpenStack volume type to the CoprHD virtual pool:

   .. code-block:: console

      $ openstack volume type set <typename> --property CoprHD:VPOOL=<CoprHD-PoolName>

#. Map the volume type created to appropriate back-end driver:

   .. code-block:: console

      $ openstack volume type set <typename> --property volume_backend_name=<VOLUME_BACKEND_DRIVER>


CoprHD drivers - Multiple back-ends
-----------------------------------

**cinder.conf**

#. Add or modify the following entries if you are planning to use multiple
   back-end drivers:

   .. code-block:: ini

      enabled_backends = coprhddriver-iscsi,coprhddriver-fc,coprhddriver-scaleio

#. Add the following at the end of the file:

   .. code-block:: ini

    [coprhddriver-iscsi]
    volume_driver = cinder.volume.drivers.coprhd.iscsi.EMCCoprHDISCSIDriver
    volume_backend_name = EMCCoprHDISCSIDriver
    coprhd_hostname = <CoprHD Host Name>
    coprhd_port = 4443
    coprhd_username = <username>
    coprhd_password = <password>
    coprhd_tenant = <CoprHD-Tenant-Name>
    coprhd_project = <CoprHD-Project-Name>
    coprhd_varray = <CoprHD-Virtual-Array-Name>


    [coprhddriver-fc]
    volume_driver = cinder.volume.drivers.coprhd.fc.EMCCoprHDFCDriver
    volume_backend_name = EMCCoprHDFCDriver
    coprhd_hostname = <CoprHD Host Name>
    coprhd_port = 4443
    coprhd_username = <username>
    coprhd_password = <password>
    coprhd_tenant = <CoprHD-Tenant-Name>
    coprhd_project = <CoprHD-Project-Name>
    coprhd_varray = <CoprHD-Virtual-Array-Name>


    [coprhddriver-scaleio]
    volume_driver = cinder.volume.drivers.coprhd.scaleio.EMCCoprHDScaleIODriver
    volume_backend_name = EMCCoprHDScaleIODriver
    coprhd_hostname = <CoprHD Host Name>
    coprhd_port = 4443
    coprhd_username = <username>
    coprhd_password = <password>
    coprhd_tenant = <CoprHD-Tenant-Name>
    coprhd_project = <CoprHD-Project-Name>
    coprhd_varray = <CoprHD-Virtual-Array-Name>
    coprhd_scaleio_rest_gateway_host = <ScaleIO Rest Gateway>
    coprhd_scaleio_rest_gateway_port = 443
    coprhd_scaleio_rest_server_username = <rest gateway username>
    coprhd_scaleio_rest_server_password = <rest gateway password>
    scaleio_verify_server_certificate = True or False
    scaleio_server_certificate_path = <certificate path>


#. Restart the ``cinder-volume`` service.


**Volume type creation and extra specs**

Setup the ``volume-types`` and ``volume-type`` to ``volume-backend``
association:

.. code-block:: console

   $ openstack volume type create "CoprHD High Performance ISCSI"
   $ openstack volume type set "CoprHD High Performance ISCSI" --property CoprHD:VPOOL="High Performance ISCSI"
   $ openstack volume type set "CoprHD High Performance ISCSI" --property volume_backend_name= EMCCoprHDISCSIDriver

   $ openstack volume type create "CoprHD High Performance FC"
   $ openstack volume type set "CoprHD High Performance FC" --property CoprHD:VPOOL="High Performance FC"
   $ openstack volume type set "CoprHD High Performance FC" --property volume_backend_name= EMCCoprHDFCDriver

   $ openstack volume type create "CoprHD performance SIO"
   $ openstack volume type set "CoprHD performance SIO" --property CoprHD:VPOOL="Scaled Perf"
   $ openstack volume type set "CoprHD performance SIO" --property volume_backend_name= EMCCoprHDScaleIODriver


ISCSI driver notes
~~~~~~~~~~~~~~~~~~

* The compute host must be added to the CoprHD along with its ISCSI
  initiator.
* The ISCSI initiator must be associated with IP network on the CoprHD.


FC driver notes
~~~~~~~~~~~~~~~

* The compute host must be attached to a VSAN or fabric discovered
  by CoprHD.
* There is no need to perform any SAN zoning operations. CoprHD will perform
  the necessary operations automatically as part of the provisioning process.


ScaleIO driver notes
~~~~~~~~~~~~~~~~~~~~

* Install the ScaleIO SDC on the compute host.
* The compute host must be added as the SDC to the ScaleIO MDS
  using the below commands::

    /opt/emc/scaleio/sdc/bin/drv_cfg --add_mdm --ip List of MDM IPs
    (starting with primary MDM and separated by comma)
    Example:
    /opt/emc/scaleio/sdc/bin/drv_cfg --add_mdm --ip
    10.247.78.45,10.247.78.46,10.247.78.47

This step has to be repeated whenever the SDC (compute host in this case)
is rebooted.


Consistency group configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable the support of consistency group and consistency group snapshot
operations, use a text editor to edit the file ``/etc/cinder/policy.json`` and
change the values of the below fields as specified. Upon editing the file,
restart the ``c-api`` service::

  "consistencygroup:create" : "",
  "consistencygroup:delete": "",
  "consistencygroup:get": "",
  "consistencygroup:get_all": "",
  "consistencygroup:update": "",
  "consistencygroup:create_cgsnapshot" : "",
  "consistencygroup:delete_cgsnapshot": "",
  "consistencygroup:get_cgsnapshot": "",
  "consistencygroup:get_all_cgsnapshots": "",


Names of resources in back-end storage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All the resources like volume, consistency group, snapshot, and consistency
group snapshot will use the display name in OpenStack for naming in the
back-end storage.
