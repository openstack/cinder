===========================
Veritas ACCESS iSCSI driver
===========================

Veritas Access is a software-defined scale-out network-attached
storage (NAS) solution for unstructured data that works on commodity
hardware and takes advantage of placing data on premise or in the
cloud based on intelligent policies. Through Veritas Access iSCSI
Driver, OpenStack Block Storage can use Veritas Access backend as a
block storage resource. The driver enables you to create iSCSI volumes
that an OpenStack Block Storage server can allocate to any virtual machine
running on a compute host.

Requirements
~~~~~~~~~~~~

The Veritas ACCESS iSCSI Driver, version ``1.0.0`` and later, supports
Veritas ACCESS release ``7.4`` and later.

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create and delete volumes.
- Create and delete snapshots.
- Create volume from snapshot.
- Extend a volume.
- Attach and detach volumes.
- Clone volumes.

Configuration
~~~~~~~~~~~~~

#. Enable RESTful service on the Veritas Access Backend.

#. Create Veritas Access iSCSI target, add store and portal IP to it.

   You can create target and add portal IP, store to it as follows:

   .. code-block:: console

      Target> iscsi target create iqn.2018-02.com.veritas:target02
      Target> iscsi target store add target_fs iqn.2018-02.com.veritas:target02
      Target> iscsi target portal add iqn.2018-02.com.veritas:target02 10.10.10.1
      ...

   You can add authentication to target as follows:

   .. code-block:: console

      Target> iscsi target auth incominguser add iqn.2018-02.com.veritas:target02 user1
      ...

#. Ensure that the Veritas Access iSCSI target service is online. If the
   Veritas Access
   iSCSI target service is not online, enable the service by using the CLI or
   REST API.

   .. code-block:: console

      Target> iscsi service start
      Target> iscsi service status
      ...

   Define the following required properties in the ``cinder.conf`` file:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.veritas_access.veritas_iscsi.ACCESSIscsiDriver
      san_ip = va_console_ip
      san_api_port = 14161
      san_login = master
      san_password = password
      target_port = 3260
      vrts_lun_sparse = True
      vrts_target_config = /etc/cinder/vrts_target.xml

#. Define Veritas Access Target details in ``/etc/cinder/vrts_target.xml``:

   .. code-block:: console

      <?xml version="1.0" ?>
      <VRTS>
           <VrtsTargets>
                <Target>
                        <Name>iqn.2018-02.com.veritas:target02</Name>
                        <PortalIP>10.10.10.1</PortalIP>
                        <Authentication>0</Authentication>
                </Target>
           </VrtsTargets>
      </VRTS>
      ...
