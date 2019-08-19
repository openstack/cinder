================================
IBM Storage Driver for OpenStack
================================

Introduction
~~~~~~~~~~~~
The IBM Storage Driver for OpenStack is a software component of the
OpenStack cloud environment that enables utilization of storage
resources provided by supported IBM storage systems.

The driver was validated on storage systems, as detailed in the
Supported storage systems section below.

After the driver is configured on the OpenStack Cinder nodes, storage volumes
can be allocated by the Cinder nodes to the Nova nodes. Virtual machines on
the Nova nodes can then utilize these storage resources.

.. note::

    Unless stated otherwise, all references to XIV storage
    system in this guide relate all members of the Spectrum Accelerate
    Family (SAF): XIV, Spectrum Accelerate, FlashSystem A9000/A9000R.

Concept diagram
---------------
This figure illustrates how an IBM storage system is connected
to the OpenStack cloud environment and provides storage resources when the
IBM Storage Driver for OpenStack is configured on the OpenStack Cinder nodes.
The OpenStack cloud is connected to the IBM storage system over Fibre
Channel or iSCSI (DS8000 systems support only Fibre Channel connections).
Remote cloud users can issue requests for storage resources from the
OpenStack cloud. These requests are transparently handled by the IBM Storage
Driver, which communicates with the IBM storage system and controls the
storage volumes on it. The IBM storage resources are then provided to the
Nova nodes in the OpenStack cloud.

.. figure:: ../../figures/ibm-storage-nova-concept.png

Preparation
~~~~~~~~~~~

If you intend to manage a Spectrum Accelerate Family product,
you need to install a Python client for executing CLI commands
on all Cinder nodes. The IBM Python XCLI Client allows full
management and monitoring of the relevant storage systems.

The client package and its documentation are available at `GitHub
<https://github.com/IBM/pyxcli>`_.

Compatibility and requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
This section specifies the compatibility and requirements of
the IBM Storage Driver for OpenStack.

Supported storage systems
-------------------------
The IBM Storage Driver for OpenStack supports the IBM storage
systems, as detailed in the following table.

+-----------------+--------------------+--------------------+
| Storage system  | Microcode version  | Connectivity       |
+=================+====================+====================+
| IBM DS8870      | 7.5 SP4 or later,  | Fibre Channel (FC) |
|                 | 7.5 with RESTful   |                    |
|                 | API patch          |                    |
+-----------------+--------------------+--------------------+
| IBM DS8880      | 8.1 or later       | Fibre Channel (FC) |
+-----------------+--------------------+--------------------+
| IBM XIV         | 11.1.x, 11.2.x,    | Fibre Channel (FC) |
| Storage System  | 11.3.x, 11.4.x,    | iSCSI              |
|                 | 11.5.x, 11.6.x     |                    |
+-----------------+--------------------+--------------------+
| IBM Spectrum    | 11.5.x             | iSCSI              |
| Accelerate      |                    |                    |
+-----------------+--------------------+--------------------+
| IBM FlashSystem | 12.0.x, 12.1.x,    | Fibre Channel (FC) |
| A9000/A9000R    | 12.2.x             | iSCSI              |
+-----------------+--------------------+--------------------+


Copy Services license
---------------------
Copy Services features help you implement storage solutions to keep
your business running 24 hours a day, 7 days a week by providing
image caching, replication and cloning functions. The Copy Services
license is based on usable capacity of the volumes involved in Copy
Services functionality.

The Copy Services license is available for the following license
scopes: FB and ALL (both FB and CKD).

The Copy Services license includes the following features:

* Global Mirror
* Metro Mirror
* Metro/Global Mirror
* Point-in-Time Copy/FlashCopy®
* z/OS® Global Mirror
* z/OS Metro/Global Mirror Incremental Resync (RMZ)

The Copy Services license feature codes are ordered in increments up
to a specific capacity. For example, if you require 160 TB of capacity,
order 10 of feature code 8251 (10 TB each up to 100 TB capacity), and
4 of feature code 8252 (15 TB each, for an extra 60 TB).

The Copy Services license includes the following feature codes.

+--------------+-----------------------------------------------------+
| Feature Code | Feature code for licensed function indicator        |
+==============+=====================================================+
| 8250         |  CS - inactive                                      |
+--------------+-----------------------------------------------------+
| 8251         |  CS - 10 TB (up to 100 TB capacity)                 |
+--------------+-----------------------------------------------------+
| 8252         |  CS - 15 TB (from 100.1 TB to 250 TB capacity)      |
+--------------+-----------------------------------------------------+
| 8253         |  CS - 25 TB (from 250.1 TB to 500 TB capacity)      |
+--------------+-----------------------------------------------------+
| 8254         |  CS - 75 TB (from 500.1 to 1250 TB capacity)        |
+--------------+-----------------------------------------------------+
| 8255         |  CS - 175 TB (from 1250.1 TB to 3000 TB capacity)   |
+--------------+-----------------------------------------------------+
| 8256         |  CS - 300 TB (from 3000.1 TB to 6000 TB capacity)   |
+--------------+-----------------------------------------------------+
| 8260         |  CS - 500 TB (from 6000.1 TB to 10,000 TB capacity) |
+--------------+-----------------------------------------------------+

The following ordering rules apply when you order the Copy Services
license:

* The Copy Services license should be ordered based on the total
  usable capacity of all volumes involved in one or more Copy
  Services relationships.

* The licensed authorization must be equal to or less that the
  total usable capacity allocated to the volumes that participate in
  Copy Services operations.

* You must purchase features for both the source (primary) and
  target (secondary) storage system.

Required software on the OpenStack Cinder and Nova nodes
--------------------------------------------------------
The IBM Storage Driver makes use of the following software on the
OpenStack Cinder and Nova-compute nodes.

+------------------------+----------------------------------+
| Software               | Installed on                     |
+========================+==================================+
| Ubuntu Server (16.04), | All OpenStack Cinder nodes       |
| x64                    |                                  |
|                        |                                  |
| Red Hat Enterprise     |                                  |
| Linux (RHEL) 7.x, x64  |                                  |
|                        |                                  |
| CentOS Linux 7.x, x64  |                                  |
|                        |                                  |
| KVM for IBM z Systems  |                                  |
+------------------------+----------------------------------+
| IBM Storage Host       | All OpenStack Cinder and Nova    |
| Attachment Kit for     | compute nodes that connect to    |
| Linux                  | storage systems and use RHEL 7.x |
|                        | or CentOS Linux 7.x              |
+------------------------+----------------------------------+
| Linux patch package    | All OpenStack Cinder nodes       |
+------------------------+----------------------------------+
| sysfsutils utility     | All OpenStack Cinder nodes on FC |
|                        | network                          |
+------------------------+----------------------------------+
| iscsi-initiator-utils  | All OpenStack Cinder and Nova    |
| utility (RHEL and      | compute nodes on iSCSI network   |
| CentOS) or open-iscsi  |                                  |
| utility (Ubuntu)       |                                  |
+------------------------+----------------------------------+
| IBM Python XCLI client | All OpenStack Cinder nodes       |
+------------------------+----------------------------------+

Configuration
~~~~~~~~~~~~~

Configure the driver manually by changing the ``cinder.conf`` file as
follows:


.. code-block:: ini

  volume_driver = cinder.volume.drivers.ibm.ibm_storage.IBMStorageDriver


Configuration Description for DS8000
------------------------------------
.. include:: ../../tables/cinder-ibm_storage.inc

Replication parameters
----------------------

+-----------------+------------------------------+---------------+
| Parameter       | Description                  | Applicable to |
+=================+==============================+===============+
| replication     | Volume replication           | DS8000        |
| _device         | parameters                   |               |
+-----------------+------------------------------+---------------+
| backend_id      | IP address or host name of   | DS8000        |
|                 | the target storage system    |               |
+-----------------+------------------------------+---------------+
| san_login       | User name to be used during  | DS8000        |
|                 | replication procedure        |               |
+-----------------+------------------------------+---------------+
| san_password    | Password to be used during   | DS8000        |
|                 | replication procedure        |               |
|                 | (base64-encoded)             |               |
+-----------------+------------------------------+---------------+
| san_clustername | Pool name on the target      | DS8000        |
|                 | storage system               |               |
+-----------------+------------------------------+---------------+
| port_pairs      | ID pairs of IO ports,        | DS8000        |
|                 | participating in             |               |
|                 | replication                  |               |
+-----------------+------------------------------+---------------+
| lss_range_for   | LSS range to reserve for     | DS8000        |
| _cg             | consistency groups           |               |
+-----------------+------------------------------+---------------+

Configuration Description for SAF
---------------------------------

+-----------------+------------------------------+---------------+
| Parameter       | Description                  | Applicable to |
+=================+==============================+===============+
| management_ips  | IP addresses of the          | SAF           |
|                 | management interfaces of a   |               |
|                 | storage system               |               |
+-----------------+------------------------------+---------------+
| san_password    | Storage system password      | SAF           |
|                 | (base64-encoded)             |               |
+-----------------+------------------------------+---------------+
| san_login       | Storage system user name     | SAF           |
+-----------------+------------------------------+---------------+
| volume_driver   | Driver to use for volume     | SAF           |
|                 | creation                     |               |
+-----------------+------------------------------+---------------+
| proxy           | Proxy for IBM storage driver | SAF           |
|                 | location within Cinder       |               |
|                 |                              |               |
|                 | SAF: cinder.volume.drivers.  |               |
|                 | ibm.ibm_storage.xiv_proxy.   |               |
|                 | XIVProxy                     |               |
|                 |                              |               |
|                 | DS8000: cinder.volume.       |               |
|                 | drivers.ibm.ibm_storage.     |               |
|                 | xiv_proxy.XIVProxy           |               |
+-----------------+------------------------------+---------------+
| san_ip          | Storage system IP address or | SAF           |
|                 | hostname                     |               |
+-----------------+------------------------------+---------------+
| connection_type | Network connection type      | SAF           |
|                 |                              |               |
|                 | Values: fibre_channel, iscsi |               |
+-----------------+------------------------------+---------------+
| san_clustername | Storage pool name            | SAF           |
+-----------------+------------------------------+---------------+
| chap            | iSCSI CHAP authentication    | SAF           |
|                 | usage                        |               |
|                 |                              |               |
|                 | Values: disabled, enabled    |               |
+-----------------+------------------------------+---------------+
| system_id       | Storage system ID            | SAF           |
+-----------------+------------------------------+---------------+

Security
~~~~~~~~

The following information provides an overview of security for the
IBM Storage Driver for OpenStack.

Avoiding man-in-the-middle attacks
----------------------------------

When using a Spectrum Accelerate Family product, you can prevent
man-in-the-middle (MITM) attacks by following these rules:

* Upgrade to IBM XIV storage system version 11.3 or later.

* If working in a secure mode, do not work insecurely against another
  storage system in the same environment.

* Validate the storage certificate. If you are using an XIV-provided
  certificate, use the CA file that was provided with your storage
  system (``XIV-CA.pem``). The certificate files should be copied
  to one of the following directories:

  * ``/etc/ssl/certs``
  * ``/etc/ssl/certs/xiv``
  * ``/etc/pki``
  * ``/etc/pki/xiv``

If you are using your own certificates, copy them to the same
directories with the prefix ``XIV`` and in the ``.pem`` format.
For example: XIV-my_cert.pem.

* In order to prevent the CVE-2014-3566 MITM attack, follow these `directions
  <https://www.ibm.com/support/knowledgecenter/en/HSG_NOVA_141/UG/nova_ig_ch4_mitm_attacks.html?cp=HW213_7.4.0>`_.

Configuring Cinder nodes for trusted communication (DS8000 Family)
------------------------------------------------------------------
The IBM Storage Driver for OpenStack communicates with DS8000
over HTTPS, using self-signed certificate or certificate signed
by a certificate authority (CA).
Configure a trusted communication link to ensure a successful
attachment of a Cinder node to a DS8000 storage system, as detailed
in the following sections.

Configuring trusted communication link
--------------------------------------

Before configuring a DS8000 backend, complete the following steps
to establish the chain of trust.

#. In your operating system shell, run this command to obtain the
   certificate: ``openssl x509 -in <(openssl s_client -connect
   <host fqdn>:8452 -prexit 2>/dev/null) -text -out <host fqdn>.pem``

   If the certificate is self-signed, the following information
   is displayed:

   .. code-block:: ini

       ---
       Certificate chain
       0 s:/CN=ds8000.ibm.com
       i:/CN=ds8000.ibm.com
       ---


#. Create an exception by moving the certificate ``<fqdn>.pem to the
   /opt/ibm/ds8k_certs/<host>.pem`` file.

#. Verify that the <host fqdn> is the same as configured in san_ip.


#. If the certificate subject and issuer are different, the
   certificate is signed by a CA, as illustrated below:

   .. code-block:: ini

       ---
       Certificate chain
       0 s:/C=US/ST=New York/L=Armonk/O=IBM/OU=EI/CN=www.ibm.com
       i:/C=US/O=GeoTrust Inc./CN=GeoTrust SSL CA - G3
       1 s:/C=US/O=GeoTrust Inc./CN=GeoTrust SSL CA - G3
       i:/C=US/O=GeoTrust Inc./CN=GeoTrust Global CA
       ---


#. Add a public certificate to trusted CA certificate store to
   complete the chain of trust, as explained below.

#. Verify trusted communication link, as explained below.

Adding a public certificate to trusted CA certificate store
-----------------------------------------------------------

Add the CA public certificate to the trusted CA certificates store
on the Cinder node, according to procedures for the operating system
in use.

#. For RHEL 7.x or CentOS 7.x, place the certificate to be trusted
   (in PEM format) into the /etc/pki/ca-trust/source/anchors/ directory.
   Then, run the ``sudo update-ca-trust`` command.

#. For Ubuntu 16.04, place the certificate to be trusted
   (in PEM format) into the /usr/local/share/ca-certificates/
   directory. Rename the file, using the ``*.crt`` extension.
   Then, run the ``sudo update-ca-certificates`` command.

#. For Python requests library with certifi, run the ``cat
   ca_public_certificate.pem`` command to append the certificate
   to the location of the certifi trust store file. For example:

   .. code-block:: ini

       cat ca_public_certificate.pem >> /usr/local/lib/python2.7/
       dist-packages/certifi/cacert.pem.


Verifying trusted communication link
------------------------------------

Verify the chain of trust has been established successfully.

#. Obtain the location of the Python library requests trust store,
   according to the installation type.

#. RHEL 7.x or CentOS 7.x:

   .. code-block:: console

       # python
           Python 2.7.5 (default, Oct 11 2015, 17:47:16)
           [GCC 4.8.3 20140911 (Red Hat 4.8.3-9)] on linux2
           Type "help", "copyright", "credits" or "license" for
           more information.
           >>> import requests
           >>> print requests.certs.where()
           /etc/pki/tls/certs/ca-bundle.crt

#. Ubuntu 16.04:

   .. code-block:: console

       # python
           Python 2.7.6 (default, Jun 22 2015, 17:58:13)
           [GCC 4.8.2] on linux2
           Type "help", "copyright", "credits" or "license" for
           more information.
           >>> import requests
           >>> print requests.certs.where()
           /etc/ssl/certs/ca-certificates.crt

#. Python requests library with certifi:

   .. code-block:: console

       # python
           Python 2.7.6 (default, Jun 22 2015, 17:58:13)
           [GCC 4.8.2] on linux2 Type "help", "copyright", "credits"
           or "license" for more information.
           >>> import requests
           >>> print requests.certs.where() /usr/local/lib/python2.7/
           dist-packages/certifi/cacert.pem

#. Run the ``openssl s_client -CAfile <location> -connect
   <host fqdn>:8452 </dev/null`` command. The following return codes
   indicate a successful or failed attempt in establishing a trusted
   communication link.

* Verify return code: 0 (ok): success.

* Verify return code: 21 (unable to verify the first certificate),
  or any other non-zero value: failure.

Troubleshooting
~~~~~~~~~~~~~~~

Refer to this information to troubleshoot technical problems that you
might encounter when using the IBM Storage Driver for OpenStack.

Checking the Cinder log files
-----------------------------

The Cinder log files record operation information that might be useful
for troubleshooting.

To achieve optimal and clear logging of events, activate the verbose
logging level in the cinder.conf file, located in the ``/etc/cinder``
folder. Add the following line in the file, save the file, and then
restart the cinder-volume service:

.. code-block:: console

    verbose = True
    debug = True

To turn off the verbose logging level, change ``True`` to ``False``,
save the file, and then restart the cinder-volume service.

Check the log files on a periodic basis to ensure that the IBM
Storage Driver is functioning properly. To check the log file on a
Cinder node, go to the /var/log/cinder folder and open the
activity log file named cinder-volume.log or volume.log. The IBM
Storage Driver writes to this log file using the [IBM DS8K STORAGE]
or [IBM XIV STORAGE] prefix (depending on the relevant storage system)
for each event that it records in the file.

Best practices
~~~~~~~~~~~~~~

This section contains the general guidance and best practices.

Working with multi-tenancy (Spectrum Accelerate Family)
-------------------------------------------------------
The XIV storage systems, running microcode version 11.5 or later,
Spectrum Accelerate and FlashSystem A9000/A9000R can employ
multi-tenancy.

In order to use multi-tenancy with the IBM Storage Driver for
OpenStack:

* For each storage system, verify that all predefined storage pools
  are in the same domain or, that all are not in a domain.

* Use either storage administrator or domain administrator user's
  credentials, as long as the credentials grant a full access to the
  relevant pool.
* If the user is a domain administrator, the storage system domain
  access policy can be CLOSED (``domain_policy: access=CLOSED``).
  Otherwise, verify that the storage system domain access policy is
  OPEN (``domain_policy: access=OPEN``).
* If the user is not a domain administrator, the host management policy
  of the storage system domain can be BASIC (``domain_policy:
  host_management=BASIC``). Otherwise, verify that the storage
  system domain host management policy is EXTENDED
  (``domain_policy: host_management=EXTENDED``).

Working with IBM Real-time Compression™ (Spectrum Accelerate Family)
--------------------------------------------------------------------
XIV storage systems running microcode version 11.6 or later,
Spectrum Accelerate and FlashSystem A9000/A9000R can employ IBM
Real-time Compression™.

Follow these guidelines when working with compressed storage
resources using the IBM Storage Driver for OpenStack:

* Compression mode cannot be changed for storage volumes, using
  the IBM Storage Driver for OpenStack. The volumes are created
  according to the default compression mode of the pool. For example,
  any volume created in a compressed pool will be compressed as well.

* The minimum size for a compressed storage volume is 87 GB.

Working with QoS (Spectrum Accelerate Family)
---------------------------------------------
The IBM Storage Driver for OpenStack provides QoS per volume for
IBM FlashSystem A9000/A9000R storage systems, running microcode
version of 12.0 or later. With QoS classes, the user can control
the maximum bandwidth and I/O operations for each volume.
For detailed instructions on QoS configuration, refer to the
user documentation of the relevant storage system on IBM
`Knowledge Center
<https://www.ibm.com/support/knowledgecenter>`_.

QoS class types:

* Shared (default). Limits the combined rates of all of the volumes
  in the same QoS class. The maximum rate is the sum of the
  combined rate for each volume. For example, two volumes under
  a QoS class of maximum 100 Gbps are allocated a combined
  maximum bandwidth rate of 100 Gbps.

* Independent. Sets the maximum rate separately for each volume
  in the QoS class. For example, for two volumes under a QoS
  class of maximum 100 Gbps, each volume is limited to a rate
  of 100 Gbps. Thus, the combined maximum bandwidth rate is up
  to 200 Gbps.

To define a QoS class:

#. Create the QoS class:

   .. code-block:: console

       cinder qos-create <class_name> <class_specs: bw=#, iops=#>

#. Create a type:

   .. code-block:: console

       cinder type-create type_<qos_class_name>

#. Associate the QoS class with the type:

   .. code-block:: console

       cinder qos-associate <qos uuid> <type uuid>

#. Announce that the type is supporting QoS:

   .. code-block:: console

       cinder type-key <type_name or UUID> set QoS_support=True

#. Create a volume:

   .. code-block:: console

       cinder create 1 --volume-type <type_name>


Configuring volume replication (DS8000 Family)
----------------------------------------------

Volume replication is required for disaster recovery and
high-availability applications running on top of
OpenStack-based clouds. The IBM Storage Driver for OpenStack
supports synchronous (Metro Mirror) volume replication for
DS8000 storage systems.

#. Verify that:

   * Master and remote storage pools exist on DS8000 systems.

   * Reliable communication link is established between the primary
     and secondary sites, including physical connection and PPRC path.

   * Metro Mirror replication is enabled on DS8000 storage systems.

#. Perform the following procedure, replacing the values in the example with
   your own:

   .. code-block:: console

       enabled_backends = ibm_ds8k_1, ibm_ds8k_2
       [ibm_ds8k_1]
       proxy = cinder.volume.drivers.ds8k_proxy.DS8KProxy
       volume_backend_name = ibm_ds8k_1
       san_clustername = P2,P3
       san_password = actual_password
       san_login = actual_username
       san_ip = host_fqdn
       volume_driver = cinder.volume.drivers.ibm.ibm_storage.IBMStorageDriver
       chap = disabled
       connection_type = fibre_channel
       replication_device = connection_type: fibre_channel,
       backend_id: bar, san_ip: host_fqdn,
       san_login: actual_username, san_password: actual_password,
       san_clustername: P4, port_pairs: I0236-I0306; I0237-I0307

       [ibm_ds8k_2]
       proxy = cinder.volume.drivers.ibm.ds8k_proxy.DS8KProxy
       volume_backend_name = ibm_ds8k_2
       san_clustername = P4,P5
       san_password = actual_password
       san_login = actual_username
       san_ip = 10.0.0.1
       volume_driver = cinder.volume.drivers.ibm.ibm_storage.IBMStorageDriver
       chap = disabled
       connection_type = fibre_channel

Configuring groups
--------------------
The IBM Storage Driver for OpenStack supports volume grouping.
These groups can be assigned a group type, and used for replication
and group snapshotting.

Replication groups
------------------
For better control over replication granularity, the user can employ
volume grouping. This enables volume group replication and failover
without affecting the entire backend.
The user can choose between a generic group replication and
consistency group (CG) replication. For consistency group
replication, the driver utilizes the storage capabilities to handle
CGs and replicate them to a remote site. On the other hand,
in generic group replication, the driver replicates each volume
individually. In addition, the user can select the replication type.

To configure group replication:

#. Create sync replicated consistency-group.

   * Create a volume type for replication.

   .. code-block:: console

       #cinder type-create rep-vol-1

   * Create a volume type for replication.

   .. code-block:: console

       #cinder type-key rep-vol-1
       set replication_type='<is> sync'
       replication_enabled='<is> True'

   * Create a group type.

   .. code-block:: console

       #cinder group-type-create rep-gr-1

   * Configure the group type.

   .. code-block:: console

       #cinder group-type-key rep-gr-1 set group_replication_enabled='<is> True' replication_type='<is> sync'

   * Create a replicated group, using existing group type and volume type.

   .. code-block:: console

       #cinder group-create rep-gr-1 rep-vol-1 --name replicated-gr-1

#. Create a volume and add it to the group.

   * Create a replicated volume.

   .. code-block:: console

       #cinder create --name vol-1 --volume-type rep-vol-1 1

   * Add the volume to the group.

   .. code-block:: console

       #cinder group-update --add-volumes 91492ed9-c3cf-4732-a525-60e146510b90 replicated-gr-1

   .. note::

       You can also create the volume directly into the group by
       using the --group-id parameter, followed by ID of a group
       that the new volume belongs to. This function is supported
       by API version 3.13 and later.

#. Enable replication.

   .. code-block:: console

       #cinder group-enable-replication replicated-gr-1

#. Disable replication.

   .. code-block:: console

       #cinder group-disable-replication replicated-gr-1

#. Fail over the replicated group.

   .. code-block:: console

       #cinder group-failover-replication replicated-gr-1

Consistency groups
------------------
Consistency groups are mostly the same as replication groups, but
with additional support of group snapshots
(``consistent_group_snapshot_enabled`` parameter). See configuration
example below.

.. code-block:: console

    #cinder group-type-create cg1
    #cinder group-type-show cg1
    #cinder group-type-key cg1 set consistent_group_snapshot_enabled="<is> True"
    #cinder group-create --name cg1 IBM-DS8K_ibm.com_P0_P1_fibre_channel_not_thin,
    IBM-DS8K_ibm.com_P0_P1_fibre_channel_thin,
    IBM-DS8K_ibm.com_P0_P1_fibre_channel_not_thin_replica,
    IBM-DS8K_ibm.com_P0_P1_fibre_channel_thin_replica

Using volume types for volume allocation control (DS8000 Family)
----------------------------------------------------------------
For better controls over volume placement granularity, you can use
volume types. This enables volumes to be created on specific LSSes
or pools. You can combine both types.

* Storage pool

  .. code-block:: console

      #cinder type-key pool-1_2 set drivers:storage_pool_ids='P1,P2'

* LSS

  .. code-block:: console

      #cinder type-key lss80_81 set drivers:storage_lss_ids='80,81'
