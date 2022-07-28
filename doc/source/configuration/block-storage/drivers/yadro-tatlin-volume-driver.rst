============================
YADRO Cinder Driver
============================

YADRO Cinder driver provides iSCSI support for
TATLIN.UNIFIED storages.


Supported Functions
~~~~~~~~~~~~~~~~~~~~

Basic Functions
---------------
* Create Volume
* Delete Volume
* Attach Volume
* Detach Volume
* Extend Volume
* Create Volume from Volume (clone)
* Create Image from Volume
* Volume Migration (host assisted)

Additional Functions
--------------------

* Extend an Attached Volume
* Thin Provisioning
* Manage/Unmanage Volume
* Image Cache
* Multiattach
* High Availability

Configuration
~~~~~~~~~~~~~

Set up TATLIN.UNIFIED storage
-----------------------------

You need to specify settings as described below for storage systems. For
details about each setting, see the user's guide of the storage system.

#. User account

   Create a storage account belonging to the admin user group.

#. Pool

   Create a storage pool that is used by the driver.

#. Ports

   Setup data ETH ports you want to export volumes to.

#. Hosts

   Create storage hosts and set ports of the initiators. One host must
   correspond to one initiator.

#. Host Group

   Create storage host group and add hosts created on the previous step
   to the host group.

#. CHAP Authentication

   Set up CHAP credentials for iSCSI storage hosts (if CHAP is used).

Set up YADRO Cinder Driver
------------------------------------

Add the following configuration to ``/etc/cinder/cinder.conf``:

.. code-block:: ini

   [iscsi-1]
   volume_driver=cinder.volume.drivers.yadro.tatlin_iscsi.TatlinISCSIVolumeDriver
   san_ip=<management_ip>
   san_login=<login>
   san_password=<password>
   tat_api_retry_count=<count>
   api_port=<management_port>
   pool_name=<cinder_volumes_pool>
   export_ports=<port1>,<port2>
   host_group=<name>
   max_resource_count=<count>
   auth_method=<CHAP|NONE>
   chap_username=<chap_username>
   chap_password=<chap_password>

``volume_driver``
 Volume driver name.

``san_ip``
 TATLIN.UNIFIED management IP address or FQDN.

``san_login``
 TATLIN.UNIFIED user name.

``san_password``
 TATLIN.UNIFIED user password.

``tat_api_retry_count``
 Number of repeated requests to TATLIN.UNIFIED.

``api_port``
 TATLIN.UNIFIED management port. Default: 443.

``pool_name``
 TATLIN.UNIFIED name of pool for Cinder Volumes.

``export_ports``
  Comma-separated data ports for volumes to be exported to.

``host_group``
 TATLIN.UNIFIED host group name.

``max_resource_count``
  Limit on the number of resources for TATLIN.UNIFIED. Default: 150

``auth_method`` (only iSCSI)
  Authentication method:
   * ``CHAP`` — use CHAP authentication (default)

``chap_username``, ``chap_password`` (if ``auth_method=CHAP``)
  CHAP credentials to validate the initiator.
