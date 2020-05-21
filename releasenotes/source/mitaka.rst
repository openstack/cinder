===========================
Mitaka Series Release Notes
===========================

.. _Mitaka Series Release Notes_8.1.1-11_stable_mitaka:

8.1.1-11
========

.. _Mitaka Series Release Notes_8.1.1-11_stable_mitaka_Security Issues:

Security Issues
---------------

.. releasenotes/notes/apply-limits-to-qemu-img-29f722a1bf4b91f8.yaml @ b'c6adc020a67ae77e3645d4f6e80fa93b19432177'

- The qemu-img tool now has resource limits applied which prevent it from using more than 1GB of address space or more than 2 seconds of CPU time. This provides protection against denial of service attacks from maliciously crafted or corrupted disk images.


.. _Mitaka Series Release Notes_8.1.1_stable_mitaka:

8.1.1
=====

.. _Mitaka Series Release Notes_8.1.1_stable_mitaka_New Features:

New Features
------------

.. releasenotes/notes/bdd-pools-stats-afb4398daa9248de.yaml @ b'3140f750858f0bb6e919e8673197c9d7c6b157f2'

- Report pools in volume stats for Block Device Driver.

.. releasenotes/notes/nimble-add-force-backup-539e1e5c72f84e61.yaml @ b'0ea086e1131fa3da284e348ee962d61470a99035'

- Support Force backup of in-use cinder volumes for Nimble Storage.

.. releasenotes/notes/vhd-disk-format-upload-to-image-5851f9d35f4ee447.yaml @ b'f45d02bace943eab2806233eff39ffa258ad685e'

- Added support for vhd disk-format for volume upload-to-image.


.. _Mitaka Series Release Notes_8.1.1_stable_mitaka_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/3par-create-fc-vlun-match-set-type-babcf2cbce1ce317.yaml @ b'5f45e0363eadee8aedaf74e11a112ffee82e13de'

- 3PAR driver creates FC VLUN of match-set type instead of host sees. With match-set, the host will see the virtual volume on specified NSP (Node-Slot-Port). This change in vlun type fixes bug 1577993.

.. releasenotes/notes/pure-fc-wwpn-case-c1d97f3fa7663acf.yaml @ b'55a668dea793e232590b24f8362e764a1a572573'

- Fix issue with PureFCDriver where partially case sensitive comparison of connector wwpn could cause initialize_connection to fail when attempting to create duplicate Purity host.


.. _Mitaka Series Release Notes_8.1.0_stable_mitaka:

8.1.0
=====

.. _Mitaka Series Release Notes_8.1.0_stable_mitaka_New Features:

New Features
------------

.. releasenotes/notes/brcd_lookupservice_http_support-f6485b38a1feaa15.yaml @ b'946776cc5934b5889e15275a2e2ba6f3a8218aeb'

- Support for use of 'fc_southbound_protocol' configuration setting in the Brocade FC SAN lookup service.


.. _Mitaka Series Release Notes_8.1.0_stable_mitaka_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/vmware-vmdk-config-eb70892e4ccf8f3c.yaml @ b'83ef56a4187115422bbdb47dc218c243cef13054'

- The VMware VMDK driver supports a new config option 'vmware_host_port' to specify the port number to connect to vCenter server.


.. _Mitaka Series Release Notes_8.1.0_stable_mitaka_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/allow-admin-quota-operations-c1c2236711224023.yaml @ b'76c74ea3c773368431f2a6894cf4ab5181896115'

- Projects with the admin role are now allowed to operate on the quotas of all other projects.

.. releasenotes/notes/vmware_vmdk_paravirtual-3d5eeef96dcbcfb7.yaml @ b'92fa7eed95982e5cb5b483100cb1c5cf53eb95ea'

- Added support for images with vmware_adaptertype set to paraVirtual in the VMDK driver.


.. _Mitaka Series Release Notes_8.0.0_stable_mitaka:

8.0.0
=====

.. _Mitaka Series Release Notes_8.0.0_stable_mitaka_New Features:

New Features
------------

.. releasenotes/notes/3par-create-cg-from-source-cg-5634dcf9feb813f6.yaml @ b'c9e5562dfddf190e124a4169e7cc9193fd82cd3d'

- Added support for creating a consistency group from a source consistency group in the HPE 3PAR driver.

.. releasenotes/notes/3par-license-check-51a16b5247675760.yaml @ b'6fddcf6da018c1c394a3d841eede1118d94d4e36'

- Disable standard capabilities based on 3PAR licenses.

.. releasenotes/notes/3par-manage-unmanage-snapshot-eb4e504e8782ba43.yaml @ b'9c3cbdd90fbf4e462c23f640e68cd88034c873c2'

- Added snapshot manage/unmanage support to the HPE 3PAR driver.

.. releasenotes/notes/Dell-SC-v2.1-replication-ef6b1d6a4e2795a0.yaml @ b'87b9380e20e5ff9a1c429930a28321b8fe31f00d'

- Added replication v2.1 support to the Dell Storage Center drivers.

.. releasenotes/notes/Huawei-volume-driver-replication-v2.1-ada5bc3ad62dc633.yaml @ b'eb3fcbb9bc32f7589ea5b974ae084f30b7ac9822'

- Added v2.1 replication support in Huawei Cinder driver.

.. releasenotes/notes/NetApp-ONTAP-full-cg-support-cfdc91bf0acf9fe1.yaml @ b'3b2d17a5db07dfba5d20a1697025706dda6f0a0a'

- Added support for creating, deleting, and updating consistency groups for NetApp 7mode and CDOT backends.

.. releasenotes/notes/NetApp-ONTAP-full-cg-support-cfdc91bf0acf9fe1.yaml @ b'3b2d17a5db07dfba5d20a1697025706dda6f0a0a'

- Added support for taking, deleting, and restoring a cgsnapshot for NetApp 7mode and CDOT backends.

.. releasenotes/notes/add-coho-driver-b4472bff3f64aa41.yaml @ b'f7e9c240dcc25bdf17e3ad0e4591a7368fe8032a'

- Added backend driver for Coho Data storage.

.. releasenotes/notes/add-google-backup-driver-d1e7ac33d5780b79.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added cinder backup driver for Google Cloud Storage.

.. releasenotes/notes/add-tegile-driver-b7919c5f30911998.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added driver for Tegile IntelliFlash arrays.

.. releasenotes/notes/backup-snapshots-2f547c8788bc11e1.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added ability to backup snapshots.

.. releasenotes/notes/balanced-fc-port-selection-fbf6b841fea99156.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Support balanced FC port selection for Huawei drivers.

.. releasenotes/notes/brocade_http_connector-0021e41dfa56e671.yaml @ b'935aa1a5b401d086334fa8ac52bf01170a3eb9ca'

- HTTP connector for the Cinder Brocade FC Zone plugin. This connector allows for communication between the Brocade FC zone plugin and the switch to be over HTTP or HTTPs.  To make use of this connector, the user would add a configuration setting in the fabric block for a Brocade switch with the name as 'fc_southbound_protocol' with a value as 'HTTP' or 'HTTPS'.

.. releasenotes/notes/brocade_virtual_fabrics_support-d2d0b95b19457c1d.yaml @ b'3abd22f7bbc1b00c01de7b8b53fd19c453f822a6'

- Support for configuring Fibre Channel zoning on Brocade switches through Cinder Fibre Channel Zone Manager and Brocade Fibre Channel zone plugin. To zone in a Virtual Fabric, set the configuration option 'fc_virtual_fabric_id' for the fabric.

.. releasenotes/notes/cg_api_volume_type-7db1856776e707c7.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- The consistency group API now returns volume type IDs.

.. releasenotes/notes/cinder-api-microversions-d2082a095c322ce6.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added support for API microversions, as well as /v3 API endpoint.

.. releasenotes/notes/cloudbyte-retype-support-4b9f79f351465279.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- Retype support added to CloudByte iSCSI driver.

.. releasenotes/notes/datera-driver-v2-update-930468e8259c8e86.yaml @ b'3962a77f050f4a3760c362539650ca1b95045d2d'

- All Datera DataFabric backed volume-types will now use API version 2 with Datera DataFabric

.. releasenotes/notes/delete-volume-with-snapshots-0b104e212d5d36b1.yaml @ b'0b2a2172ce0f6605e04e2f66757a8be3e25be3fe'

- It is now possible to delete a volume and its snapshots by passing an additional argument to volume delete, "cascade=True".

.. releasenotes/notes/discard-config-option-711a7fbf20685834.yaml @ b'63e54b80d0b3103621e248122c48b8bbb167580a'

- New config option to enable discard (trim/unmap) support for any backend.

.. releasenotes/notes/disco-cinder-driver-9dac5fb04511de1f.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added backend driver for DISCO storage.

.. releasenotes/notes/friendly-zone-names-d5e131d356040de0.yaml @ b'c346612cc7c9ff0b6e4534534b1818b5db2cfbc4'

- Cinder FC Zone Manager Friendly Zone Names This feature adds support for Fibre Channel user friendly zone names if implemented by the volume driver. If the volume driver passes the host name and storage system to the Fibre Channel Zone Manager in the conn_info structure, the zone manager will use these names in structuring the zone name to provide a user friendly zone name.

.. releasenotes/notes/fujitsu-eternus-dx-fc-741319960195215c.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added backend driver for Fujitsu ETERNUS DX (FC).

.. releasenotes/notes/fujitsu-eternus-dx-iscsi-e796beffb740db89.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added backend driver for Fujitsu ETERNUS DX (iSCSI).

.. releasenotes/notes/huawei-manage-unmanage-snapshot-e35ff844d72fedfb.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added manage/unmanage snapshot support for Huawei drivers.

.. releasenotes/notes/huawei-support-manage-volume-2a746cd05621423d.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added manage/unmanage volume support for Huawei drivers.

.. releasenotes/notes/image-volume-type-c91b7cff3cb41c13.yaml @ b'dc12ecd1ea7ab5fe6f90e4479d4e5727ff64e16c'

- Support cinder_img_volume_type property in glance image metadata to specify volume type.

.. releasenotes/notes/lefthand-consistency-groups-d73f8e418884fcc6.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- Consistency group support has been added to the LeftHand backend driver.

.. releasenotes/notes/lefthand-manage-unmanage-snapshot-04de39d268d51169.yaml @ b'6fa9ac877b7d29596199da1d6d0ad12f01eb134b'

- Added snapshot manage/unmanage support to the HPE LeftHand driver.

.. releasenotes/notes/netapp-chap-iscsi-auth-264cd942b2a76094.yaml @ b'ce3052a867771875f8f472438bcc187caa3021e7'

- Added iSCSI CHAP uni-directional authentication for NetApp drivers.

.. releasenotes/notes/netapp-eseries-consistency-groups-4f6b2af2d20c94e9.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Support for Consistency Groups in the NetApp E-Series Volume Driver.

.. releasenotes/notes/nexenta-edge-iscsi-b3f12c7a719e8b8c.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- Added backend driver for Nexenta Edge iSCSI storage.

.. releasenotes/notes/nexentastor5_iscsi-e1d88b07d15c660b.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added backend driver for NexentaStor5 iSCSI storage.

.. releasenotes/notes/nexentastor5_nfs-bcc8848716daea63.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added backend driver for NexentaStor5 NFS storage.

.. releasenotes/notes/nimble-manage-unmanage-1d6d5fc23cbe59a1.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- Manage and unmanage support has been added to the Nimble backend driver.

.. releasenotes/notes/pure-enhanced-stats-42a684fe4546d1b1.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added additional metrics reported to the scheduler for Pure Volume Drivers for better filtering and weighing functions.

.. releasenotes/notes/pure-enhanced-stats-42a684fe4546d1b1.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added config option to enable/disable automatically calculation an over-subscription ratio max for Pure Volume Drivers. When disabled the drivers will now respect the max_oversubscription_ratio config option.

.. releasenotes/notes/pure-eradicate-on-delete-1e15e1440d5cd4d6.yaml @ b'b85caca74a90a9b9215c9c8a4a6b868f8f300952'

- New config option for Pure Storage volume drivers pure_eradicate_on_delete. When enabled will permanantly eradicate data instead of placing into pending eradication state.

.. releasenotes/notes/pure-v2.1-replication-0246223caaa8a9b5.yaml @ b'04f4aa158d7390f1e0412398dbe962a192fa6eaa'

- Added Cheesecake (v2.1) replication support to the Pure Storage Volume drivers.

.. releasenotes/notes/re-add-nexenta-driver-d3af97e33551a485.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added Migrate and Extend for Nexenta NFS driver.

.. releasenotes/notes/re-add-nexenta-driver-d3af97e33551a485.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added Retype functionality to Nexenta iSCSI and NFS drivers.

.. releasenotes/notes/replication-v2.1-3par-b3f780a109f9195c.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added v2.1 replication support to the HPE 3PAR driver.

.. releasenotes/notes/replication-v2.1-lefthand-745b72b64e5944c3.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added v2.1 replication support to the HPE LeftHand driver.

.. releasenotes/notes/replication-v2.1-storwize-2df7bfd8c253090b.yaml @ b'c8cf5504cc6c49b3060b8c8c0f1304b19d00bfb1'

- Added replication v2.1 support to the IBM Storwize driver.

.. releasenotes/notes/rpc_compatibility-375be8ac3158981d.yaml @ b'c9a55d852e3f56a955039e99b628ce0b1c1e95af'

- Added RPC backward compatibility layer similar to the one implemented in Nova. This means that Cinder services can be upgraded one-by-one without breakage. After all the services are upgraded SIGHUP signals should be issued to all the services to signal them to reload cached minimum RPC versions. Alternative is of course restart of them. Please note that cinder-api service doesn't support SIGHUP yet. Please also take into account that all the rolling upgrades capabilities are considered tech preview, as we don't have a CI testing it yet.

.. releasenotes/notes/scaleio-consistency-groups-707f9b4ffcb3c14c.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added Consistency Group support in ScaleIO driver.

.. releasenotes/notes/scaleio-manage-existing-32217f6d1c295193.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added support for manage/unmanage volume in the ScaleIO driver.

.. releasenotes/notes/scaleio-qos-support-2ba20be58150f251.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added QoS support in ScaleIO driver.

.. releasenotes/notes/scaling-backup-service-7e5058802d2fb3dc.yaml @ b'05a516da01225bed8b99ca49e558d40d71df3fe1'

- cinder-backup service is now decoupled from cinder-volume, which allows more flexible scaling.

.. releasenotes/notes/split-out-nested-quota-driver-e9493f478d2b8be5.yaml @ b'7ebd4904b977d29c97447b53fbd718bccfa39969'

- Split nested quota support into a separate driver. In order to use nested quotas, change the following config ``quota_driver = cinder.quota.NestedDbQuotaDriver`` after running the following admin API "os-quota-sets/validate_setup_for_nested_quota_use" command to ensure the existing quota values make sense to nest.

.. releasenotes/notes/storwize-multiple-management-ip-1cd364d63879d9b8.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added multiple management IP support to Storwize SVC driver.

.. releasenotes/notes/storwize-pool-aware-support-7a40c9934642b202.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added multiple pools support to Storwize SVC driver.

.. releasenotes/notes/support-zeromq-messaging-driver-d26a1141290f5548.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added support for ZeroMQ messaging driver in cinder single backend config.

.. releasenotes/notes/tooz-locks-0f9f2cc15f8dad5a.yaml @ b'd6fabaa6cf7700cfb957e37594d0da818afea806'

- Locks may use Tooz as abstraction layer now, to support distributed lock managers and prepare Cinder to better support HA configurations.

.. releasenotes/notes/updated-at-list-0f899098f7258331.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- The updated_at timestamp is now returned in listing detail.

.. releasenotes/notes/vmware-vmdk-manage-existing-0edc20d9d4d19172.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Added support for manage volume in the VMware VMDK driver.

.. releasenotes/notes/vnx-configurable-migration-rate-5e0a2235777c314f.yaml @ b'719bedd6254b4203e19fa7467d8fa524e673ae56'

- Configrable migration rate in VNX driver via metadata

.. releasenotes/notes/vnx-replication-v2.1-4d89935547183cc9.yaml @ b'ab2a05aab3b5cb19c656808d137a3c69ffe6e741'

- Adds v2.1 replication support in VNX Cinder driver.

.. releasenotes/notes/vnx_clone_cg-db74ee2ea71bedcb.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- Cloning of consistency group added to EMC VNX backend driver.

.. releasenotes/notes/xiv-ds8k-replication-2.1-996c871391152e31.yaml @ b'9952531da4eb63689ed390c3dc2e291180e81f29'

- Added replication v2.1 support to the IBM XIV/DS8K driver.

.. releasenotes/notes/xtremio-cg-from-cg-e05cf286e3a1e943.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Support for creating a consistency group from consistency group in XtremIO.

.. releasenotes/notes/zfssa-volume-manage-unmanage-ccd80807103b69c8.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Volume manage/unmanage support for Oracle ZFSSA iSCSI and NFS drivers.


.. _Mitaka Series Release Notes_8.0.0_stable_mitaka_Known Issues:

Known Issues
------------

.. releasenotes/notes/general-upgrades-notes-120f022aa5bfa1ea.yaml @ b'2b4b4883a3f01e38a34b2ffc814d5a805cd3493a'

- Cinder services are now automatically downgrading RPC messages to be understood by the oldest version of a service among all the deployment. Disabled and dead services are also taken into account. It is important to keep service list up to date, without old, unused records. This can be done using ``cinder-manage service remove`` command. Once situation is cleaned up services should be either restarted or ``SIGHUP`` signal should be issued to their processes to force them to reload version pins.  Please note that cinder-api does not support ``SIGHUP`` signal.


.. _Mitaka Series Release Notes_8.0.0_stable_mitaka_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/1220b8a67602b8e7-update_rootwrap_volume_filters.yaml @ b'81645a9ca68ad7ec4a5986925b835d28df078b4c'

- It is required to copy new rootwrap.d/volume.filters file into /etc/cinder/rootwrap.d directory.

.. releasenotes/notes/VMEM-6000-drivers-removed-9b6675ff7ae5f960.yaml @ b'00b46803e151d99b4813310aa976974e618b4927'

- Violin Memory 6000 array series drivers are removed.

.. releasenotes/notes/add-del-volumeTypeAccess-b1c8cb14a9d14db3.yaml @ b'b2cd356cacad84d925a5781c7ac6c56c68a73e04'

- Adding or removing volume_type_access from any project during DB migration 62 must not be performed.

.. releasenotes/notes/add-del-volumeTypeAccess-b1c8cb14a9d14db3.yaml @ b'b2cd356cacad84d925a5781c7ac6c56c68a73e04'

- When running PostgreSQL it is required to upgrade and restart all the cinder-api services along with DB migration 62.

.. releasenotes/notes/datera-driver-v2-update-930468e8259c8e86.yaml @ b'3962a77f050f4a3760c362539650ca1b95045d2d'

- Users of the Datera Cinder driver are now required to use Datera DataFabric version 1.0+. Versions before 1.0 will not be able to utilize this new driver since they still function on v1 of the Datera DataFabric API

.. releasenotes/notes/enforce_min_vmware-a080055111b04692.yaml @ b'015cb3ab56a8b9d2419feb159aa03b414904113f'

- The VMware VMDK driver now enforces minimum vCenter version of 5.1.

.. releasenotes/notes/general-upgrades-notes-120f022aa5bfa1ea.yaml @ b'2b4b4883a3f01e38a34b2ffc814d5a805cd3493a'

- If during a *live* upgrade from Liberty a backup service will be killed while processing a restore request it may happen that such backup status won't be automatically cleaned up on the service restart. Such orphaned backups need to be cleaned up manually.

.. releasenotes/notes/general-upgrades-notes-120f022aa5bfa1ea.yaml @ b'2b4b4883a3f01e38a34b2ffc814d5a805cd3493a'

- When performing a *live* upgrade from Liberty it may happen that retype calls will reserve additional quota. As by default quota reservations are invalidated after 24 hours (config option ``reservation_expire=86400``), we recommend either decreasing that time or watching for unused quota reservations manually during the upgrade process.

.. releasenotes/notes/rebranded-hpe-drivers-caf1dcef1afe37ba.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- HP drivers have been rebranded to HPE. Existing configurations will continue to work with the legacy name, but will need to be updated by the next release.

.. releasenotes/notes/remove-hp-cliq-41f47fd61e47d13f.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- The deprecated HP CLIQ proxy driver has now been removed.

.. releasenotes/notes/remove-ibm-nas-driver-0ed204ed0a2dcf55.yaml @ b'f63d3217744b9f281df2424b6a31108728f65c75'

- Users of the ibmnas driver should switch to using the IBM GPFS driver to enable Cinder access to IBM NAS resources.  For details configuring the IBM GPFS driver, see the GPFS config reference. - http://docs.openstack.org/liberty/config-reference/content/GPFS-driver.html

.. releasenotes/notes/remove_lvmdriver-9c35f83132cd2ac8.yaml @ b'dbce6abe96de0f046e8432bbd1ce0426a692750a'

- Removed deprecated LVMISCSIDriver and LVMISERDriver. These should be switched to use the LVMVolumeDriver with the desired iscsi_helper configuration set to the desired iSCSI helper.

.. releasenotes/notes/remove_storwize_npiv-b704ff2d97207666.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- Removed the deprecated NPIV options for the Storwize backend driver.

.. releasenotes/notes/removed-scality-7151638fdac3ed9d.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- Backend driver for Scality SRB has been removed.

.. releasenotes/notes/rename-huawei-driver-092025e46b65cd48.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Rename Huawei18000ISCSIDriver and Huawei18000FCDriver to HuaweiISCSIDriver and HuaweiFCDriver.

.. releasenotes/notes/rpc_compatibility-375be8ac3158981d.yaml @ b'c9a55d852e3f56a955039e99b628ce0b1c1e95af'

- Starting from Mitaka release Cinder is having a tech preview of rolling upgrades support.

.. releasenotes/notes/scaleio-remove-force-delete-config-48fae029e3622d6d.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Removed force_delete option from ScaleIO configuration.

.. releasenotes/notes/scaling-backup-service-7e5058802d2fb3dc.yaml @ b'05a516da01225bed8b99ca49e558d40d71df3fe1'

- As cinder-backup was strongly reworked in this release, the recommended upgrade order when executing live (rolling) upgrade is c-api->c-sch->c-vol->c-bak.

.. releasenotes/notes/split-out-nested-quota-driver-e9493f478d2b8be5.yaml @ b'7ebd4904b977d29c97447b53fbd718bccfa39969'

- Nested quotas will no longer be used by default, but can be configured by setting ``quota_driver = cinder.quota.NestedDbQuotaDriver``

.. releasenotes/notes/storwize-split-up-__init__-153fa8f097a81e37.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Removed storwize_svc_connection_protocol config setting. Users will now need to set different values for volume_driver in cinder.conf. FC:volume_driver = cinder.volume.drivers.ibm.storwize_svc.storwize_svc_fc.StorwizeSVCFCDriver iSCSI:volume_driver = cinder.volume.drivers.ibm.storwize_svc.storwize_svc_iscsi.StorwizeSVCISCSIDriver

.. releasenotes/notes/vmware-vmdk-removed-bfb04eed77b95fdf.yaml @ b'015cb3ab56a8b9d2419feb159aa03b414904113f'

- The VMware VMDK driver for ESX server has been removed.


.. _Mitaka Series Release Notes_8.0.0_stable_mitaka_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/datera-driver-v2-update-930468e8259c8e86.yaml @ b'3962a77f050f4a3760c362539650ca1b95045d2d'

- datera_api_token -- this has been replaced by san_login and san_password

.. releasenotes/notes/deprecate-xml-api-bf3e4079f1dc5eae.yaml @ b'32cb195f0343a0835c3fcccc5962345941fe6025'

- The XML API has been marked deprecated and will be removed in a future release.

.. releasenotes/notes/deprecated-ibm-multipath-f06c0e907a6301de.yaml @ b'32cb195f0343a0835c3fcccc5962345941fe6025'

- Deprecated IBM driver _multipath_enabled config flags.


.. _Mitaka Series Release Notes_8.0.0_stable_mitaka_Security Issues:

Security Issues
---------------

.. releasenotes/notes/pure-verify-https-requests-464320c97ba77a1f.yaml @ b'615cc81051164c8e53c4237a28563264d1edc768'

- Pure Storage Volume Drivers can now utilize driver_ssl_cert_verify and driver_ssl_cert_path config options to allow for secure https requests to the FlashArray.


.. _Mitaka Series Release Notes_8.0.0_stable_mitaka_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/1220b8a67602b8e7-update_rootwrap_volume_filters.yaml @ b'81645a9ca68ad7ec4a5986925b835d28df078b4c'

- Fixed bug causing snapshot creation to fail on systems with LC_NUMERIC set to locale using ',' as decimal separator.

.. releasenotes/notes/a7401ead26a7c83b-keystone-url.yaml @ b'109353dedbe53201eb6999984c5658d9193115df'

- Cinder will now correctly read Keystone's endpoint for quota calls from keystone_authtoken.auth_uri instead of keymgr.encryption_auth_url config option.

.. releasenotes/notes/backup_driver_init_state-d4834fa927e502ab.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- Fixed service state reporting when backup manager is unable to initialize one of the backup drivers.

.. releasenotes/notes/cg-scheduler-change-180a36b77e8cc26b.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Consistency group creation previously scheduled at the pool level. Now it is fixed to schedule at the backend level as designed.

.. releasenotes/notes/downstream_genconfig-e50791497ce87ce3.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- Removed the need for deployers to run tox for config reference generation.

.. releasenotes/notes/glance_v2_upload-939c5693bcc25483.yaml @ b'edf00659aadaf898ae679f358a6ea8533f4dd891'

- upload-to-image using Image API v2 now correctly handles custom image properties.

.. releasenotes/notes/permit_volume_type_operations-b2e130fd7088f335.yaml @ b'4ccd1bd15100b7046e634323e55ad610ef52e0ab'

- Enabled a cloud operator to correctly manage policy for
  volume type operations. To permit volume type operations
  for specific user, you can for example do as follows.

   * Add ``storage_type_admin`` role.
   * Add ``admin_or_storage_type_admin`` rule to ``policy.json``, e.g.
         ``"admin_or_storage_type_admin": "is_admin:True or role:storage_type_admin",``
   * Modify rule for types_manage and volume_type_access, e.g.
         ``"volume_extension:types_manage": "rule:admin_or_storage_type_admin",
         "volume_extension:volume_type_access:addProjectAccess": "rule:admin_or_storage_type_admin",
         "volume_extension:volume_type_access:removeProjectAccess": "rule:admin_or_storage_type_admin",``

.. releasenotes/notes/pure-enhanced-stats-42a684fe4546d1b1.yaml @ b'4566b6f550c52d5cf1e2763bc2b9607ad25e57a5'

- Fixed issue where Pure Volume Drivers would ignore reserved_percentage config option.

.. releasenotes/notes/pure-eradicate-on-delete-1e15e1440d5cd4d6.yaml @ b'b85caca74a90a9b9215c9c8a4a6b868f8f300952'

- Allow for eradicating Pure Storage volumes, snapshots, and pgroups when deleting their Cinder counterpart.

.. releasenotes/notes/quota-volume-transfer-abd1f418c6c63db0.yaml @ b'7fdc8baf4e32fe59165b7511b3336420bec8c8ef'

- Corrected quota usage when transferring a volume between tenants.

.. releasenotes/notes/remove-vol-in-error-from-cg-1ed0fde04ab2b5be.yaml @ b'80620b1fea79a24f4b22fdfb9213e2aec69ef826'

- Previously the only way to remove volumes in error states from a consistency-group was to delete the consistency group and create it again. Now it is possible to remove volumes in error and error_deleting states.

.. releasenotes/notes/tintri_image_direct_clone-f73e561985aad867.yaml @ b'bc86c4b44713f34793b7a4693c919a6a1e618875'

- Fix for Tintri image direct clone feature. Fix for the bug 1400966 prevents user from specifying image "nfs share location" as location value for an image. Now, in order to use Tintri image direct clone, user can specify "provider_location" in image metadata to specify image nfs share location. NFS share which hosts images should be specified in a file using tintri_image_shares_config config option.

.. releasenotes/notes/volume-filtering-for-quoted-display-name-7f5e8ac888a73001.yaml @ b'fc119315f1931f4893fb4e7423b4c806772f77a5'

- Filtering volumes by their display name now correctly handles display names with single and double quotes.


.. _Mitaka Series Release Notes_8.0.0_stable_mitaka_Other Notes:

Other Notes
-----------

.. releasenotes/notes/remove-ibm-nas-driver-0ed204ed0a2dcf55.yaml @ b'f63d3217744b9f281df2424b6a31108728f65c75'

- Due to the ibmnas (SONAS) driver being rendered redundant by the addition of NFS capabilities to the IBM GPFS driver, the ibmnas driver is being removed in the Mitaka release.


