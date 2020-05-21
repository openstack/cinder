==========================
Ocata Series Release Notes
==========================

.. _Ocata Series Release Notes_10.0.8-20_stable_ocata:

10.0.8-20
=========

.. _Ocata Series Release Notes_10.0.8-20_stable_ocata_New Features:

New Features
------------

.. releasenotes/notes/feature-rbd-exclusive-pool-a9bdebdeb1f0bf37.yaml @ b'b1a0d62f357e431a6b74d38440a8392de972b824'

- When using the RBD pool exclusively for Cinder we can now set
  `rbd_exclusive_cinder_pool` to `true` and Cinder will use DB information
  to calculate provisioned size instead of querying all volumes in the
  backend, which will reduce the load on the Ceph cluster and the volume
  service.

.. releasenotes/notes/generic-group-quota-manage-support-559629ad07a406f4.yaml @ b'492cf46f63c829ec722c0b8fb06de678e85afc5e'

- Generic group is added into quota management.

.. releasenotes/notes/unity-remove-empty-host-17d567dbb6738e4e.yaml @ b'9773f963fea7e8a7033a047fda8967259ef4f99f'

- Dell EMC Unity Driver: Adds support for removing empty host. The new option
  named `remove_empty_host` could be configured as `True` to notify Unity
  driver to remove the host after the last LUN is detached from it.

.. releasenotes/notes/vnx-add-force-detach-support-26f215e6f70cc03b.yaml @ b'39f1f020f46eaf57ed106648047da4f318c37d5d'

- Add support to force detach a volume from all hosts on VNX.


.. _Ocata Series Release Notes_10.0.8-20_stable_ocata_Known Issues:

Known Issues
------------

.. releasenotes/notes/feature-rbd-exclusive-pool-a9bdebdeb1f0bf37.yaml @ b'b1a0d62f357e431a6b74d38440a8392de972b824'

- If RBD stats collection is taking too long in your environment maybe even
  leading to the service appearing as down you'll want to use the
  `rbd_exclusive_cinder_pool = true` configuration option if you are using
  the pool exclusively for Cinder and maybe even if you are not and can live
  with the innacuracy.


.. _Ocata Series Release Notes_10.0.8-20_stable_ocata_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1775518-fix-unity-empty-list-issue-2d6b7c33aae1ffcc.yaml @ b'5be96ca9c58c52ce11db0d2f19a6ce527118556a'

- Dell EMC Unity: Fixes bug 1775518 to make sure driver succeed
  to initialize even though the value of unity_io_ports and
  unity_storage_pool_names are empty

.. releasenotes/notes/fail-detach-lun-when-auto-zone-enabled-9c87b18a3acac9d1.yaml @ b'e704e834024cf4ec156527b16f7437f9dba4d551'

- Dell EMC Unity Driver: Fixes `bug 1759175
  <https://bugs.launchpad.net/cinder/+bug/1759175>`__
  to detach the lun correctly when auto zone was enabled and the lun was the
  last one attached to the host.

.. releasenotes/notes/kaminario-cinder-driver-bug-44c728f026394a85.yaml @ b'633e2d5205e4718e270f260e24d606fa104ff9a3'

- Kaminario FC and iSCSI drivers: Fixed `bug 1829398
  <https://bugs.launchpad.net/cinder/+bug/1829398>`_ where
  force detach would fail.

.. releasenotes/notes/unity-force-detach-7c89e72105f9de61.yaml @ b'9dbcb24f0313c1187bc6269e61421bef4c45b3c9'

- Corrected support to force detach a volume from all hosts on Unity.

.. releasenotes/notes/vnx-update-sg-in-cache-3ecb673727bea79b.yaml @ b'187016c2852533c1806c7fdb34aa8dc6dfcd528e'

- Dell EMC VNX Driver: Fixes `bug 1817385
  <https://bugs.launchpad.net/cinder/+bug/1817385>`__ to make sure the sg can
  be created again after it was destroyed under `destroy_empty_storage_group`
  setting to `True`.


.. _Ocata Series Release Notes_10.0.8_stable_ocata:

10.0.8
======

.. _Ocata Series Release Notes_10.0.8_stable_ocata_Security Issues:

Security Issues
---------------

.. releasenotes/notes/scaleio-zeropadding-a0273c56c4d14fca.yaml @ b'2dc52153215bb6a37532a959c5c98239be21bb56'

- Removed the ability to create volumes in a ScaleIO Storage Pool that has
  zero-padding disabled. A new configuration option
  ``sio_allow_non_padded_volumes`` has been added to override this new
  behavior and allow unpadded volumes, but should not be enabled if multiple
  tenants will utilize volumes from a shared Storage Pool.


.. _Ocata Series Release Notes_10.0.8_stable_ocata_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1690954-40fc21683977e996.yaml @ b'dbca62c207d63bbc192acf75ae39c6b56702295a'

- NetApp ONTAP NFS (bug 1690954): Fix wrong usage of export path
  as volume name when deleting volumes and snapshots.

.. releasenotes/notes/bug-1762424-f76af2f37fe408f1.yaml @ b'ee330b9a27cc49b5566a2df878a6da51e701f83c'

- NetApp ONTAP (bug 1762424): Fix ONTAP NetApp driver not being able to extend
  a volume to a size greater than the corresponding LUN max geometry.

.. releasenotes/notes/fix-abort-backup-df196e9dcb992586.yaml @ b'f3aa39f21505dddaab592a85648678d628f5616e'

- We no longer leave orphaned chunks on the backup backend or leave a
  temporary volume/snapshot when aborting a backup.

.. releasenotes/notes/netapp_fix_svm_scoped_permissions.yaml @ b'd67448fdad668a35c5c35a5a06d2ac2af5b26bcd'

- NetApp cDOT block and file drivers have improved support for SVM scoped user accounts. Features not supported for SVM scoped users include QoS, aggregate usage reporting, and dedupe usage reporting.


.. _Ocata Series Release Notes_10.0.7_stable_ocata:

10.0.7
======

.. _Ocata Series Release Notes_10.0.7_stable_ocata_New Features:

New Features
------------

.. releasenotes/notes/k2-disable-discovery-bca0d65b5672ec7b.yaml @ b'c3464ac5cb523fecb3c265e1f1ed26831507d126'

- Kaminario K2 iSCSI driver now supports non discovery multipathing (Nova and
  Cinder won't use iSCSI sendtargets) which can be enabled by setting
  `disable_discovery` to `true` in the configuration.

.. releasenotes/notes/rbd-stats-report-0c7e803bb0b1aedb.yaml @ b'69a79e38afbdc67f61568c0b82cf6d06ca304e56'

- RBD driver supports returning a static total capacity value instead of a
  dynamic value like it's been doing.  Configurable with
  `report_dynamic_total_capacity` configuration option.


.. _Ocata Series Release Notes_10.0.7_stable_ocata_Known Issues:

Known Issues
------------

.. releasenotes/notes/k2-non-unique-fqdns-b62a269a26fd53d5.yaml @ b'caceaa52a7070548b7b42df877e23bc4d3845def'

- Kaminario K2 now supports networks with duplicated FQDNs via configuration
  option `unique_fqdn_network` so attaching in these networks will work
  (bug #1720147).


.. _Ocata Series Release Notes_10.0.7_stable_ocata_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1714209-netapp-ontap-drivers-oversubscription-issue-c4655b9c4858d7c6.yaml @ b'83a849a78c93ad7a1a7f2c9c0cd3b7ae08a2ff32'

- If using the NetApp ONTAP drivers (7mode/cmode), the configuration value for "max_over_subscription_ratio" may need to be increased to avoid scheduling problems where storage pools that previously were valid to schedule new volumes suddenly appear to be out of space to the Cinder scheduler. See documentation `here <https://docs.openstack .org/cinder/latest/admin/blockstorage-over-subscription.html>`_.

.. releasenotes/notes/rbd-stats-report-0c7e803bb0b1aedb.yaml @ b'69a79e38afbdc67f61568c0b82cf6d06ca304e56'

- RBD/Ceph backends should adjust `max_over_subscription_ratio` to take into
  account that the driver is no longer reporting volume's physical usage but
  it's provisioned size.


.. _Ocata Series Release Notes_10.0.7_stable_ocata_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1632333-netapp-ontap-copyoffload-downloads-glance-image-twice-08801d8c7b9eed2c.yaml @ b'6d59c490c262d7634af5b2e03149c9f028f4d81c'

- Fixed bug 1632333 with the NetApp ONTAP Driver. Now the copy offload method is invoked
  early to avoid downloading Glance images twice.

.. releasenotes/notes/bug-1714209-netapp-ontap-drivers-oversubscription-issue-c4655b9c4858d7c6.yaml @ b'83a849a78c93ad7a1a7f2c9c0cd3b7ae08a2ff32'

- The ONTAP drivers ("7mode" and "cmode") have been fixed to not report consumed space as "provisioned_capacity_gb". They instead rely on the cinder scheduler's calculation of "provisioned_capacity_gb". This fixes the oversubscription miscalculations with the ONTAP drivers. This bugfix affects all three protocols supported by these drivers (iSCSI/FC/NFS).

.. releasenotes/notes/dell-emc-sc-bugfix-1756914-ffca3133273040f6.yaml @ b'd2bff999dbf9fdf48e4b1f4c402217ceb97bf6a0'

- Dell EMC SC driver correctly returns initialize_connection data when more than one IQN is attached to a volume. This fixes some random Nova Live Migration failures where the connection information being returned was for an IQN other than the one for which it was being requested.

.. releasenotes/notes/netapp-ontap-use_exact_size-d03c90efbb8a30ac.yaml @ b'013d6183c434ec05a11115e603f02cf6e57a85b1'

- Fixed bug #1731474 on NetApp Data ONTAP driver that was causing LUNs to be created
  with larger size than requested. This fix requires version 9.1 of ONTAP
  or later.

.. releasenotes/notes/ps-duplicate-ACL-5aa447c50f2474e7.yaml @ b'c96512aab0ee00201e26b0efa9c87c7f62fd463e'

- Dell EMC PS Series Driver code was creating duplicate ACL records during live migration. Fixes the initialize_connection code to not create access record for a host if one exists previously. This change fixes bug 1726591.

.. releasenotes/notes/ps-extend_volume-no-snap-8aa447c50f2475a7.yaml @ b'09b1b1351901b5cf042b2a59624751451707c87a'

- Dell EMC PS Series Driver was creating unmanaged snapshots when extending volumes. Fixed it by adding the missing no-snap parameter. This change fixes bug 1720454.

.. releasenotes/notes/ps-optimize-parsing-8aa447c50f2474c7.yaml @ b'047c3f87b590ea2d627692d05347fcb49c060bab'

- Dell EMC PS Series Driver code reporting volume stats is now optimized to return the information earlier and accelerate the process. This change fixes bug 1661154.

.. releasenotes/notes/ps-over-subscription-ratio-cal-8aa447c50f2474a8.yaml @ b'e205ab8dc7ac73d182958e60b6b9a9cb7b54601d'

- Dell EMC PS Driver stats report has been fixed, now reports the
  `provisioned_capacity_gb` properly. Fixes bug 1719659.

.. releasenotes/notes/rbd-stats-report-0c7e803bb0b1aedb.yaml @ b'69a79e38afbdc67f61568c0b82cf6d06ca304e56'

- RBD stats report has been fixed, now properly reports
  `allocated_capacity_gb` and `provisioned_capacity_gb` with the sum of the
  sizes of the volumes (not physical sizes) for volumes created by Cinder and
  all available in the pool respectively.  Free capacity will now properly
  handle quota size restrictions of the pool.


.. _Ocata Series Release Notes_10.0.5_stable_ocata:

10.0.5
======

.. _Ocata Series Release Notes_10.0.5_stable_ocata_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1705375-prohibit-group-deletion-if-groupsnapshot-exists.yaml @ b'42aa97ba3ef8f31e3188d0676aabc769121a2368'

- Prohibit the deletion of group if group snapshot exists.


.. _Ocata Series Release Notes_10.0.4_stable_ocata:

10.0.4
======

.. _Ocata Series Release Notes_10.0.4_stable_ocata_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/support-tenants-project-in-attachment-list-3edd8g138a28s4r8.yaml @ b'c09f4ffbb967d87254b9a364b5f49557348f960c'

- Add ``all_tenants``, ``project_id`` support in attachment list&detail APIs.


.. _Ocata Series Release Notes_10.0.3_stable_ocata:

10.0.3
======

.. _Ocata Series Release Notes_10.0.3_stable_ocata_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/nfs_backup_no_overwrite-be7b545453baf7a3.yaml @ b'640b9dc2b739b04f1f7d70c2172f5b5fbc3b9b28'

- Fix NFS backup driver, we now support multiple backups on the same
  container, they are no longer overwritten.


.. _Ocata Series Release Notes_10.0.1_stable_ocata:

10.0.1
======

.. _Ocata Series Release Notes_10.0.1_stable_ocata_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1671220-4d521be71d0b8aa4.yaml @ b'25a1805b198080425e9244d7dcc79e81dd9d024f'

- Fixed consistency groups API which was always returning groups
  scoped to project ID from user context instead of given input
  project ID.


.. _Ocata Series Release Notes_10.0.0_stable_ocata:

10.0.0
======

.. _Ocata Series Release Notes_10.0.0_stable_ocata_New Features:

New Features
------------

.. releasenotes/notes/Dell-SC-New-Extra-Specs-1de0d3f1ebc62881.yaml @ b'c5368a739456a2864b731ed40de9d48190dd1765'

- Dell SC - Compression and Dedupe support added for Storage Centers that support the options.

.. releasenotes/notes/Dell-SC-New-Extra-Specs-1de0d3f1ebc62881.yaml @ b'c5368a739456a2864b731ed40de9d48190dd1765'

- Dell SC - Volume and Group QOS support added for Storage Centers that support and have enabled the option.

.. releasenotes/notes/add-backup-project-attribute-3f57051ef9159b08.yaml @ b'3f7acda20fb1e9e2623c86e560c4a5ab25b475e4'

- Added ability to query backups by project ID.

.. releasenotes/notes/add-io-ports-option-c751d1bd395dd614.yaml @ b'8e4e0c86c32d802389e4718e5610fb06765e4308'

- Add support to configure IO ports option in Dell EMC Unity driver.

.. releasenotes/notes/add-reset-group-snapshot-status-sd21a31cde5fa035.yaml @ b'304ff4c23db878262a553d0d15771c0beb970b42'

- Added reset status API to group snapshot.

.. releasenotes/notes/add-reset-group-status-sd21a31cde5fa034.yaml @ b'15c555445bb61ec856ce3b0b9d3fb90df00d349f'

- Added reset status API to generic volume group.

.. releasenotes/notes/add-vmax-replication-490202c15503ae03.yaml @ b'67a2178eb490e35320138bd25da650eddc9cd79a'

- Add v2.1 volume replication support in VMAX driver.

.. releasenotes/notes/bp-open-src-ibm-storage-driver-d17808e52aa4eacb.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The IBM_Storage driver has been open sourced. This means that there is no
  more need to download the package from the IBM site. The only requirement
  remaining is to install pyxcli, which is available through pypi::

      ``sudo pip install pyxcli``

.. releasenotes/notes/capacity-headroom-4b07701f1df9e5c4.yaml @ b'b67a416bb94bc0f2e64fc896e1c04581956f777d'

- Cinder is now collecting capacity data, including virtual free capacity etc from the backends. A notification which includes that data is periodically emitted.

.. releasenotes/notes/consistency_group_manage-d30a2ad8917a7a86.yaml @ b'67520e5eb2de79cbb270c7703e715a73c187ec09'

- Added update-host command for consistency groups in cinder-manage.

.. releasenotes/notes/datera-2.3-driver-update-12d0221fd4bb9fb0.yaml @ b'9a8dc08346964a58023992eb1d7b00cb0e4e7679'

- Added Datera EDF API 2.1 support.

.. releasenotes/notes/datera-2.3-driver-update-12d0221fd4bb9fb0.yaml @ b'9a8dc08346964a58023992eb1d7b00cb0e4e7679'

- Added Datera Multi-Tenancy Support.

.. releasenotes/notes/datera-2.3-driver-update-12d0221fd4bb9fb0.yaml @ b'9a8dc08346964a58023992eb1d7b00cb0e4e7679'

- Added Datera Template Support.

.. releasenotes/notes/datera-2.3-driver-update-12d0221fd4bb9fb0.yaml @ b'9a8dc08346964a58023992eb1d7b00cb0e4e7679'

- Broke Datera driver up into modules.

.. releasenotes/notes/delete_parameters-6f44fece22a7787d.yaml @ b'4d454f6eb1d3948e9c33563dce2f12b69a1b7392'

- The ``force`` boolean parameter has been added to the volume delete API.  It may be used in combination with ``cascade``. This also means that volume force delete is available in the base volume API rather than only in the ``volume_admin_actions`` extension.

.. releasenotes/notes/dell-emc-unity-driver-72cb901467b23b22.yaml @ b'5a8f26eb62ac7130dec476db8661b96ed9c96715'

- Added backend driver for Dell EMC Unity storage.

.. releasenotes/notes/generic-groups-in-vnx-cbbe1346e889b5c2.yaml @ b'6359dcecd54b54b18edbffbd55e91809383cea6a'

- Add consistent group capability to generic volume groups in VNX driver.

.. releasenotes/notes/hitachi-vsp-driver-87659bb496bb459b.yaml @ b'5c815388e2d8d4b62f7a66dd14d07ce961143435'

- Added new Hitachi VSP FC Driver. The VSP driver supports all Hitachi VSP Family and HUSVM.

.. releasenotes/notes/hitachi-vsp-iscsi-driver-cac31d7c54d7718d.yaml @ b'3f6a9739b351980f938b4f4346586ba1012f2ce0'

- Adds new Hitachi VSP iSCSI Driver.

.. releasenotes/notes/hitachi-vsp-ports-option-7147289e6529d7fe.yaml @ b'b9b352fe6199569351f5e53e603480b2f8d6927f'

- Hitachi VSP drivers have a new config option ``vsp_compute_target_ports`` to specify IDs of the storage ports used to attach volumes to compute nodes. The default is the value specified for the existing ``vsp_target_ports`` option. Either or both of ``vsp_compute_target_ports`` and ``vsp_target_ports`` must be specified.

.. releasenotes/notes/hitachi-vsp-ports-option-7147289e6529d7fe.yaml @ b'b9b352fe6199569351f5e53e603480b2f8d6927f'

- Hitachi VSP drivers have a new config option ``vsp_horcm_pair_target_ports`` to specify IDs of the storage ports used to copy volumes by Shadow Image or Thin Image. The default is the value specified for the existing ``vsp_target_ports`` option. Either or both of ``vsp_horcm_pair_target_ports`` and ``vsp_target_ports`` must be specified.

.. releasenotes/notes/hnas-list-manageable-9329866618fa9a9c.yaml @ b'fb87dc52bf2e29f038d669c657e34f928352f51d'

- Added the ability to list manageable volumes and snapshots to HNAS NFS driver.

.. releasenotes/notes/huawei-backend-capabilities-report-optimization-d1c18d9f62ef71aa.yaml @ b'c557f3bd912db78e9c6fe7786315afc939733c81'

- Optimize backend reporting capabilities for Huawei drivers.

.. releasenotes/notes/improvement-to-get-group-detail-0e8b68114e79a8a2.yaml @ b'5e0393b26d01250a296866408ddd3b1620a5396c'

- Added support for querying group details with volume ids which are in this group. For example, "groups/{group_id}?list_volume=True".

.. releasenotes/notes/infinidat-add-infinibox-driver-67cc33fc3fbff1bb.yaml @ b'8020d32b078f7c4e2f179413abdb96777509343a'

- Added driver for the InfiniBox storage array.

.. releasenotes/notes/nec_storage_volume_driver-57663f9ecce1ae19.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- Added backend FC and iSCSI drivers for NEC Storage.

.. releasenotes/notes/netapp_cdot_report_shared_blocks_exhaustion-073a73e05daf09d4.yaml @ b'685e4c98eef0fbf73d1408d50383cfdaca583dcb'

- The NetApp cDOT drivers report to the scheduler, for each FlexVol pool, the fraction of the shared block limit that has been consumed by dedupe and cloning operations. This value, netapp_dedupe_used_percent, may be used in the filter & goodness functions for better placement of new Cinder volumes.

.. releasenotes/notes/nexenta-ns5-5d223f3b60f58aad.yaml @ b'e0a6071b594b3ef9194ac569addc0e42ebccb105'

- Added extend method to NFS driver for NexentaStor 5.

.. releasenotes/notes/nexentastor5-https-6d58004838cfab30.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- Added secure HTTP support for REST API calls in the NexentaStor5 driver. Use of HTTPS is set True by default with option ``nexenta_use_https``.

.. releasenotes/notes/nfs-snapshots-21b641300341cba1.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- Added support for snapshots in the NFS driver. This functionality is only enabled if ``nfs_snapshot_support`` is set to ``True`` in cinder.conf. Cloning volumes is only supported if the source volume is not attached.

.. releasenotes/notes/nimble-add-fc-support-0007fdbd647be947.yaml @ b'c3d1dd1048bff4976bc771539d1f44cc423b7adf'

- Added Nimble Storage Fibre Channel backend driver.

.. releasenotes/notes/nimble-qos-specs-8cd006777c66a64e.yaml @ b'd7931d7fc58166ef02b5936f5b1a1f1bd8bee151'

- Add Support for QoS in the Nimble Storage driver. QoS is available from Nimble OS release 4.x and above.

.. releasenotes/notes/nimble-qos-specs-8cd006777c66a64e.yaml @ b'd7931d7fc58166ef02b5936f5b1a1f1bd8bee151'

- Add Support for deduplication of volumes in the Nimble Storage driver.

.. releasenotes/notes/nimble-rest-api-support-75c2324ee462d026.yaml @ b'c9eada86f29406a72c9d5d5a8b123c65ae69a4b9'

- The Nimble backend driver has been updated to use REST for array communication.

.. releasenotes/notes/pure-generic-volume-groups-2b0941103f7c01cb.yaml @ b'abf53e0815014b1ffc9d8d03bec1570faef18327'

- Add consistent group capability to generic volume groups in Pure drivers.

.. releasenotes/notes/rbd-thin-provisioning-c98522d6fe7b71ff.yaml @ b'd4fd5660736a1363a4e78480b116532c71b5ce49'

- Allow the RBD driver to work with max_over_subscription_ratio.

.. releasenotes/notes/rbd-v2.1-replication-64a9d0bec5987faf.yaml @ b'f81d8a37debce61b9f5414257419af87bfce536d'

- Added v2.1 replication support to RBD driver.

.. releasenotes/notes/reduxio-iscsci-driver-5827c32a0c498949.yaml @ b'5bb68e49d3323c7a73166aef147c248c69503e9a'

- Added backend ISCSI driver for Reduxio.

.. releasenotes/notes/show-provider-id-for-admin-ff4fd5a2518a4bfa.yaml @ b'ef0d793e9b9d99ebf4eb54766a1d5a915f54c2e8'

- Add provider_id in the detailed view of a volume for admin.

.. releasenotes/notes/slug-qnap-driver-d4465ea6009c66df.yaml @ b'f6342d029ece2872c47857da68c20e141b17f464'

- Added volume driver for QNAP ES Storage Driver.

.. releasenotes/notes/solidfire-scaled-qos-9b8632453909e2db.yaml @ b'409391d6a607f5905d48e4885a174d1da9f6456b'

- The SolidFire driver will recognize 4 new QoS spec keys to allow an administrator to specify QoS settings which are scaled by the size of the volume. 'ScaledIOPS' is a flag which will tell the driver to look for 'scaleMin', 'scaleMax' and 'scaleBurst' which provide the scaling factor from the minimum values specified by the previous QoS keys ('minIOPS', 'maxIOPS', 'burstIOPS'). The administrator must take care to assure that no matter what the final calculated QoS values follow minIOPS <= maxIOPS <= burstIOPS. A exception will be thrown if not. The QoS settings are also checked against the cluster min and max allowed and truncated at the min or max if they exceed.

.. releasenotes/notes/storwize_iscsi_multipath_enhance-9de9dc29661869cd.yaml @ b'ad59cb5ac2fdc93cdcc93ac582c948a2a820a124'

- Add multipath enhancement to Storwize iSCSI driver.

.. releasenotes/notes/support-metadata-based-snapshot-list-filtering-6e6df68a7ce981f5.yaml @ b'f5cdbe8f74e64ce912e875141c2e092655988344'

- Added support to querying snapshots filtered by metadata key/value using 'metadata' optional URL parameter. For example, "/v3/snapshots?metadata=={'key1':'value1'}".

.. releasenotes/notes/support-zmq-messaging-41085787156fbda1.yaml @ b'df647d0ccd56b7a10b003b8c7372ed3b5b717cc1'

- Added support for ZMQ messaging layer in multibackend configuration.

.. releasenotes/notes/unity-backup-via-snapshot-81a2d5a118c97042.yaml @ b'17171f6b15a422629b12357fe9274abe4cca7f2e'

- Add support to backup volume using snapshot in the Unity driver.

.. releasenotes/notes/vmax-attach-snapshot-3137e59ab4ff39a4.yaml @ b'efd07037ea9c47c3906319df0d4083d7f41a3002'

- Enable backup snapshot optimal path by implementing attach and detach snapshot in the VMAX driver.

.. releasenotes/notes/vmax-clone-cg-09fce492931c957f.yaml @ b'4e3eb04b569a85e81301239cb4a354b34c47ecda'

- Added the ability to create a CG from a source CG with the VMAX driver.

.. releasenotes/notes/vmax-compression-support-1dfe463328b56d7f.yaml @ b'a9a3eddaf26d4705c06f25152ccb0a6a427eaf7b'

- Support for compression on VMAX All Flash in the VMAX driver.

.. releasenotes/notes/vmax-volume-migration-992c8c68e2207bbc.yaml @ b'6624c3197bfce7092a1b16ae74f1c3c9532d0a04'

- Storage assisted volume migration from one Pool/SLO/Workload combination to another, on the same array, via retype, for the VMAX driver. Both All Flash and Hybrid VMAX3 arrays are supported. VMAX2 is not supported.

.. releasenotes/notes/vnx-async-migration-support-3c449139bb264004.yaml @ b'6ccfcafd45c445bc48593a310a3649e18c8b8a51'

- VNX cinder driver now supports async migration during volume cloning. By default, the cloned volume will be available after the migration starts in the VNX instead of waiting for the completion of migration. This greatly accelerates the cloning process. If user wants to disable this, he could add ``--metadata async_migrate=False`` when creating volume from source volume/snapshot.

.. releasenotes/notes/xtremio-generic-groups-912e11525573e970.yaml @ b'ca77a489dc5a172b89f0609e2901e399daea925b'

- Add consistent group capability to generic volume groups in the XtremIO driver.


.. _Ocata Series Release Notes_10.0.0_stable_ocata_Known Issues:

Known Issues
------------

.. releasenotes/notes/Dell-SC-Retype-Limitations-74f4b5f6a94ffe4f.yaml @ b'c514b25b0783769d5349b0a34880545c54e1ca4c'

- With the Dell SC Cinder Driver if a volume is retyped to a new storage profile all volumes created via snapshots from this volume will also change to the new storage profile.

.. releasenotes/notes/Dell-SC-Retype-Limitations-74f4b5f6a94ffe4f.yaml @ b'c514b25b0783769d5349b0a34880545c54e1ca4c'

- With the Dell SC Cinder Driver retyping from one replication type to another type (ex. regular replication to live volume replication) is not supported.

.. releasenotes/notes/Dell-SC-thaw_backend-b9362d381fabd4c9.yaml @ b'3f5a7e1bc84f0c202487955d8587ba041dcc1450'

- Dell SC Cinder driver has limited support in a failed over state so thaw_backend has been implemented to reject the thaw call when in such a state.


.. _Ocata Series Release Notes_10.0.0_stable_ocata_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/add-suppress-lvm-fd-warnings-option.402bebc03b0a9f00.yaml @ b'055ec1ce73ca55c463481c349b42dee66e5e86d6'

- In certain environments (Kubernetes for example) indirect calls to the LVM
  commands result in file descriptor leak warning messages which in turn cause
  the process_execution method to raise and exception.

  To accommodate these environments, and to maintain backward compatibility
  in Newton we add a ``lvm_suppress_fd_warnings`` bool config to the LVM driver.
  Setting this to True will append the LVM env vars to include the variable
  ``LVM_SUPPRESS_FD_WARNINGS=1``.

  This is made an optional configuration because it only applies to very specific
  environments.  If we were to make this global that would require a rootwrap/privsep
  update that could break compatibility when trying to do rolling upgrades of the
  volume service.

.. releasenotes/notes/bp-open-src-ibm-storage-driver-d17808e52aa4eacb.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- Previous installations of IBM Storage must be un-installed first and the
  new driver should be installed on top. In addition the cinder.conf values
  should be updated to reflect the new paths. For example the proxy setting
  of ``storage.proxy.IBMStorageProxy`` should be updated to
  ``cinder.volume.drivers.ibm.ibm_storage.proxy.IBMStorageProxy``.

.. releasenotes/notes/cinder-api-middleware-remove-deprecated-option-98912ab7e8b472e8.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- Removed deprecated option ``osapi_max_request_body_size``.

.. releasenotes/notes/cinder-manage-db-online-schema-migrations-d1c0d40f26d0f033.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- To get rid of long running DB data migrations that must be run offline, Cinder will now be able to execute them online, on a live cloud. Before upgrading from Ocata to Pike, operator needs to perform all the Newton data migrations. To achieve that he needs to perform ``cinder-manage db online_data_migrations`` until there are no records to be updated. To limit DB performance impact migrations can be performed in chunks limited by ``--max_number`` option. If your intent is to upgrade Cinder in a non-live manner, you can use ``--ignore_state`` option safely. Please note that finishing all the Newton data migrations will be enforced by the first schema migration in Pike, so you won't be able to upgrade to Pike without that.

.. releasenotes/notes/datera-2.3-driver-update-12d0221fd4bb9fb0.yaml @ b'9a8dc08346964a58023992eb1d7b00cb0e4e7679'

- Datera driver location has changed from cinder.volume.drivers .datera.DateraDriver to cinder.volume.drivers.datera.datera_iscsi .DateraDriver.

.. releasenotes/notes/db-schema-from-liberty-f5fa57d67441dece.yaml @ b'38f2ad54b343152f0edba817b191d456d4303d17'

- The Cinder database can now only be upgraded from changes since the Liberty release. In order to upgrade from a version prior to that, you must now upgrade to at least Liberty first, then to Ocata or later.

.. releasenotes/notes/default-apiv1-disabled-9f6bb0c67b38e670.yaml @ b'7fcca079ff63f1a1b6d4d3067508883f01515add'

- The v1 API was deprecated in the Juno release and is now defaulted to disabled. In order to still use the v1 API, you must now set ``enable_v1_api`` to ``True`` in your cinder.conf file.

.. releasenotes/notes/delete_parameters-6f44fece22a7787d.yaml @ b'4d454f6eb1d3948e9c33563dce2f12b69a1b7392'

- There is a new policy option ``volume:force_delete`` which controls access to the ability to specify force delete via the volume delete API.  This is separate from the pre-existing ``volume-admin-actions:force_delete`` policy check.

.. releasenotes/notes/hnas-deprecate-iscsi-driver-cd521b3a2ba948f3.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The Hitachi NAS iSCSI driver has been marked as unsupported and is now deprecated. ``enable_unsupported_drivers`` will need to be set to ``True`` in cinder.conf to continue to use it.

.. releasenotes/notes/kaminario-cinder-driver-remove-deprecate-option-831920f4d25e2979.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- Removed deprecated option ``kaminario_nodedup_substring`` in Kaminario FC and iSCSI Cinder drivers.

.. releasenotes/notes/mark-cloudbyte-unsupported-8615a127439ed262.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The CloudByte driver has been marked as unsupported and is now deprecated. ``enable_unsupported_drivers`` will need to be set to ``True`` in cinder.conf to continue to use it.

.. releasenotes/notes/mark-dothill-unsupported-7f95115b7b24e53c.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The DotHill drivers have been marked as unsupported and are now deprecated. ``enable_unsupported_drivers`` will need to be set to ``True`` in cinder.conf to continue to use it.

.. releasenotes/notes/mark-hpe-xp-unsupported-c9ce6cfbab622e46.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The HPE XP driver has been marked as unsupported and is now deprecated. ``enable_unsupported_drivers`` will need to be set to ``True`` in cinder.conf to continue to use it.

.. releasenotes/notes/mark-nexentaedge-unsupported-56d184fdccc6eaac.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The Nexenta Edge drivers have been marked as unsupported and are now deprecated. ``enable_unsupported_drivers`` will need to be set to ``True`` in cinder.conf to continue to use it.

.. releasenotes/notes/migrate-cg-to-generic-volume-groups-f82ad3658f3e567c.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- Operator needs to perform ``cinder-manage db online_data_migrations`` to migrate existing consistency groups to generic volume groups.

.. releasenotes/notes/move-eqlx-driver-to-dell-emc-fe5d2b484c47b7a6.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The EqualLogic driver is moved to the dell_emc directory and has been rebranded to its current Dell EMC PS Series name. The volume_driver entry in cinder.conf needs to be changed to ``cinder.volume.drivers.dell_emc.ps.PSSeriesISCSIDriver``.

.. releasenotes/notes/move-scaleio-driver-to-dell-emc-dir-c195374ca6b7e98d.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The ScaleIO driver is moved to the dell_emc directory. volume_driver entry in cinder.conf needs to be changed to ``cinder.volume.drivers.dell_emc.scaleio.driver.ScaleIODriver``.

.. releasenotes/notes/move-xtremio-driver-to-dell-emc-dir-f7e07a502cafd78f.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The XtremIO driver is moved to the dell_emc directory. volume_driver entry in cinder.conf needs to be changed to ``cinder.volume.drivers.dell_emc.xtremio.XtremIOISCSIDriver`` or ``cinder.volume.drivers.dell_emc.xtremio.XtremIOFCDriver``.

.. releasenotes/notes/new-osprofiler-call-0bb1a305c8e8f9cc.yaml @ b'd48e9670270305beeaba57ffcfd61b14792d8097'

- New config option added. ``"connection_string"`` in [profiler] section is used to specify OSProfiler driver connection string, for example, ``"connection_string = messaging://"``, ``"connection_string = mongodb://localhost:27017"``

.. releasenotes/notes/operate-migrated-groups-with-cp-apis-e5835c6673191805.yaml @ b'44ebdd22526e9a4ae0646d9f9ae2b391e70bed57'

- After running the migration script to migrate CGs to
  generic volume groups, CG and group APIs work as follows.

  * Create CG only creates in the groups table.
  * Modify CG modifies in the CG table if the CG is in the
    CG table, otherwise it modifies in the groups table.
  * Delete CG deletes from the CG or the groups table
    depending on where the CG is.
  * List CG checks both CG and groups tables.
  * List CG Snapshots checks both the CG and the groups
    tables.
  * Show CG checks both tables.
  * Show CG Snapshot checks both tables.
  * Create CG Snapshot creates either in the CG or the groups
    table depending on where the CG is.
  * Create CG from Source creates in either the CG or the
    groups table depending on the source.
  * Create Volume adds the volume either to the CG or the
    group.
  * default_cgsnapshot_type is reserved for migrating CGs.
  * Group APIs will only write/read in/from the groups table.
  * Group APIs will not work on groups with default_cgsnapshot_type.
  * Groups with default_cgsnapshot_type can only be operated by
    CG APIs.
  * After CG tables are removed, we will allow default_cgsnapshot_type
    to be used by group APIs.

.. releasenotes/notes/rebranded-vnx-driver-2fb7424ddc9c41df.yaml @ b'c479e94901baaba9a9d4991efef4fd9a16124030'

- EMC VNX driver have been rebranded to Dell EMC VNX driver. Existing configurations will continue to work with the legacy name, but will need to be updated by the next release. User needs update ``volume_driver`` to ``cinder.volume.drivers.dell_emc.vnx.driver.VNXDriver``.

.. releasenotes/notes/remove-deprecated-driver-mappings-b927d8ef9fc3b713.yaml @ b'6ac5d02419277982bd12b0954b7feddb0a3f5f82'

- Old driver paths have been removed since they have been through our alloted
  deprecation period. Make sure if you have any of these paths being set in
  your cinder.conf for the volume_driver option, to update to the new driver
  path listed here.

  * Old path - cinder.volume.drivers.huawei.huawei_18000.Huawei18000ISCSIDriver
  * New path - cinder.volume.drivers.huawei.huawei_driver.HuaweiISCSIDriver
  * Old path - cinder.volume.drivers.huawei.huawei_driver.Huawei18000ISCSIDriver
  * New path - cinder.volume.drivers.huawei.huawei_driver.HuaweiISCSIDriver
  * Old path - cinder.volume.drivers.huawei.huawei_18000.Huawei18000FCDriver
  * New path - cinder.volume.drivers.huawei.huawei_driver.HuaweiFCDriver
  * Old path - cinder.volume.drivers.huawei.huawei_driver.Huawei18000FCDriver
  * New path - cinder.volume.drivers.huawei.huawei_driver.HuaweiFCDriver
  * Old path - cinder.volume.drivers.san.hp.hp_3par_fc.HP3PARFCDriver
  * New path - cinder.volume.drivers.hpe.hpe_3par_fc.HPE3PARFCDriver
  * Old path - cinder.volume.drivers.san.hp.hp_3par_iscsi.HP3PARISCSIDriver
  * New path - cinder.volume.drivers.hpe.hpe_3par_iscsi.HPE3PARISCSIDriver
  * Old path - cinder.volume.drivers.san.hp.hp_lefthand_iscsi.HPLeftHandISCSIDriver
  * New path - cinder.volume.drivers.hpe.hpe_lefthand_iscsi.HPELeftHandISCSIDriver
  * Old path - cinder.volume.drivers.san.hp.hp_xp_fc.HPXPFCDriver
  * New path - cinder.volume.drivers.hpe.hpe_xp_fc.HPEXPFCDriver

.. releasenotes/notes/remove-eqlx-deprecated-options-89ba02c41d4da62a.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- 
  Removing the Dell EqualLogic driver's deprecated configuration options.
  Please replace old options in your cinder.conf with the new one.

  * Removed - ``eqlx_cli_timeout``
  * Replaced with - ``ssh_conn_timeout``
  * Removed - ``eqlx_use_chap``
  * Replaced with - ``use_chap_auth``
  * Removed - ``eqlx_chap_login``
  * Replaced with - ``chap_username``
  * Removed - ``eqlx_chap_password``
  * Replaced with - ``chap_password``

.. releasenotes/notes/remove-scality-fa209aae9748a1f3.yaml @ b'a931f9db79554630d8d71fcff1334bb4e37cb398'

- The Scality backend volume driver was marked as not supported in the previous release and has now been removed.

.. releasenotes/notes/remove-single-backend-7bf02e525bbbdd3a.yaml @ b'e8e3ae7616878cc46303ceee40164b9b38a3975c'

- Configurations that are setting backend config in ``[DEFAULT]`` section are now not supported. You should use ``enabled_backends`` option to set up backends.

.. releasenotes/notes/remove-volume-clear-shred-bde9f7f9ff430feb.yaml @ b'f90c49e0062c4e9287b44e11040fa16a26013a58'

- The volume_clear option to use `shred` was deprecated in the Newton release and has now been removed. Since deprecation, this option has performed the same action as the `zero` option. Config settings for `shred` should be updated to be set to `zero` for continued operation.

.. releasenotes/notes/remove_glusterfs_volume_driver-d8fd2cf5f38e754b.yaml @ b'16e93ccd4f3a6d62ed9d277f03b64bccc63ae060'

- The GlusterFS volume driver, which was deprecated in the Newton release, has been removed.

.. releasenotes/notes/remove_volume_tmp_dir_option-c83c5341e5a42378.yaml @ b'e73995308fccc9ae1f8d956d3ceeecca76fec14f'

- The RBD driver no longer uses the "volume_tmp_dir" option to set where temporary files for image conversion are stored.  Set "image_conversion_dir" to configure this in Ocata.

.. releasenotes/notes/removing-cinder-all-9f5c3d1eb230f9e6.yaml @ b'dafc68aa569a607a37c8f31d3230ea5a5efda93f'

- Removing cinder-all binary. Instead use the individual binaries like cinder-api, cinder-backup, cinder-volume, cinder-scheduler.

.. releasenotes/notes/vmax-rename-dell-emc-f9ebfb9eb567f427.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The VMAX driver is moved to the dell_emc directory. volume_driver entry in cinder.conf needs to be changed to ``cinder.volume.drivers.dell_emc.vmax.iscsi.VMAXISCSIDriver`` or ``cinder.volume.drivers.dell_emc.vmax.fc.VMAXFCDriver``.

.. releasenotes/notes/vmdk_config_conn_pool_size-0658c497e118533f.yaml @ b'2fce7a3d0ca264e012d0fb5cf128a74dd9a07fb0'

- Added config option ``vmware_connection_pool_size`` in the VMware VMDK driver to specify the maximum number of connections (to vCenter) in the http connection pool.

.. releasenotes/notes/vnx-repv2.1-config-update-cc2f60c20aec88dd.yaml @ b'8f845056fd49e6ca503e4a08baea4185ad32a4b6'

- In VNX Cinder driver, ``replication_device`` keys, ``backend_id`` and ``san_ip`` are mandatory now. If you prefer security file authentication, please append ``storage_vnx_security_file_dir`` in ``replication_device``, otherwise, append ``san_login``, ``san_password``, ``storage_vnx_authentication_type`` in ``replication_device``.


.. _Ocata Series Release Notes_10.0.0_stable_ocata_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/datera-2.3-driver-update-12d0221fd4bb9fb0.yaml @ b'9a8dc08346964a58023992eb1d7b00cb0e4e7679'

- Deprecated datera_api_version option.

.. releasenotes/notes/datera-2.3-driver-update-12d0221fd4bb9fb0.yaml @ b'9a8dc08346964a58023992eb1d7b00cb0e4e7679'

- Removed datera_acl_allow_all option.

.. releasenotes/notes/datera-2.3-driver-update-12d0221fd4bb9fb0.yaml @ b'9a8dc08346964a58023992eb1d7b00cb0e4e7679'

- Removed datera_num_replicas option.

.. releasenotes/notes/deprecate-block-device-driver-d30232547a31fe1e.yaml @ b'65fe16ea85c2b989c61deefba51e2172822cc7a0'

- The block_driver is deprecated as of the Ocata release and will be removed in the Queens release of Cinder.  Instead the LVM driver with the LIO iSCSI target should be used.  For those that desire higher performance, they should use LVM striping.

.. releasenotes/notes/deprecate-cinder-linux-smb-driver-4aec58f15a963c54.yaml @ b'd623546c9372086ed65b32462cbec596d6b7bcd6'

- The Cinder Linux SMBFS driver is now deprecated and will be removed
  during the following release. Deployers are encouraged to use the
  Windows SMBFS driver instead.

.. releasenotes/notes/hbsd-driver-deletion-d81f7c4513f45d7b.yaml @ b'ba1e0d7940f2268c72b017f6f6ea19c784c617c0'

- The HBSD (Hitachi Block Storage Driver) volume drivers which supports Hitachi Storages HUS100 and VSP family are deprecated. Support for HUS110 family will be no longer provided. Support on VSP will be provided as hitachi.vsp_* drivers.

.. releasenotes/notes/hnas-change-snapshot-names-8153b043eb7e99fc.yaml @ b'8f82bb7966986f8857913ed2366fcf42c134e027'

- Support for snapshots named in the backend as ``snapshot-<snapshot-id>`` is deprecated. Snapshots are now named in the backend as ``<volume-name>.<snapshot-id>``.

.. releasenotes/notes/hnas-deprecate-iscsi-driver-cd521b3a2ba948f3.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The Hitachi NAS iSCSI driver has been marked as unsupported and is now deprecated. ``enable_unsupported_drivers`` will need to be set to ``True`` in cinder.conf to continue to use it. The driver will be removed in the next release.

.. releasenotes/notes/hnas-deprecated-svc-volume-type-77768f27946aadf4.yaml @ b'19ad533a6d403913172142bc83d31adb10d752a8'

- Deprecated the configuration option ``hnas_svcX_volume_type``. Use option ``hnas_svcX_pool_name`` to indicate the name of the services (pools).

.. releasenotes/notes/mark-cloudbyte-unsupported-8615a127439ed262.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The CloudByte driver has been marked as unsupported and is now deprecated. ``enable_unsupported_drivers`` will need to be set to ``True`` in cinder.conf to continue to use it. If its support status does not change it will be removed in the next release.

.. releasenotes/notes/mark-dothill-unsupported-7f95115b7b24e53c.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The DotHill drivers has been marked as unsupported and are now deprecated. ``enable_unsupported_drivers`` will need to be set to ``True`` in cinder.conf to continue to use it. If its support status does not change it will be removed in the next release.

.. releasenotes/notes/mark-hpe-xp-unsupported-c9ce6cfbab622e46.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The HPE XP driver has been marked as unsupported and is now deprecated. ``enable_unsupported_drivers`` will need to be set to ``True`` in cinder.conf to continue to use it. If its support status does not change it will be removed in the next release.

.. releasenotes/notes/mark-nexentaedge-unsupported-56d184fdccc6eaac.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- The Nexenta Edge drivers has been marked as unsupported and are now deprecated. ``enable_unsupported_drivers`` will need to be set to ``True`` in cinder.conf to continue to use it. If its support status does not change it will be removed in the next release.

.. releasenotes/notes/netapp-data-ontap-deprecate-7mode-drivers-a39bfcb3afefc9a5.yaml @ b'd6bd4c87407854c2093fb61e6963777028609f4f'

- The 7-Mode Data ONTAP configuration of the NetApp Unified driver is deprecated as of the Ocata release and will be removed in the Queens release. Other configurations of the NetApp Unified driver, including Clustered Data ONTAP and E-series, are unaffected.

.. releasenotes/notes/refactor-disco-volume-driver-3ff0145707ec0f3e.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- Marked the ITRI DISCO driver option ``disco_wsdl_path`` as deprecated. The new preferred protocol for array communication is REST and SOAP support will be removed.


.. _Ocata Series Release Notes_10.0.0_stable_ocata_Security Issues:

Security Issues
---------------

.. releasenotes/notes/apply-limits-to-qemu-img-29f722a1bf4b91f8.yaml @ b'78f17f0ad79380ee3d9c50f2670252bcc559b62b'

- The qemu-img tool now has resource limits applied which prevent it from using more than 1GB of address space or more than 2 seconds of CPU time. This provides protection against denial of service attacks from maliciously crafted or corrupted disk images.


.. _Ocata Series Release Notes_10.0.0_stable_ocata_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/Dell-SC-Retype-Limitations-74f4b5f6a94ffe4f.yaml @ b'c514b25b0783769d5349b0a34880545c54e1ca4c'

- With the Dell SC Cinder Driver retyping to or from a replicated type should now work.

.. releasenotes/notes/Dell-SC-Retype-Limitations-74f4b5f6a94ffe4f.yaml @ b'c514b25b0783769d5349b0a34880545c54e1ca4c'

- With the Dell SC Cinder Driver retype failed to return a tuple if it had to return an update to the volume state.

.. releasenotes/notes/bug-1622057-netapp-cdot-fix-replication-status-cheesecake-volumes-804dc8b0b1380e6b.yaml @ b'df284e68f9f00282b05eb523e4ee3d5f63b8a750'

- The NetApp cDOT driver now sets the ``replication_status`` attribute appropriately on volumes created within replicated backends when using host level replication.

.. releasenotes/notes/bug-1634203-netapp-cdot-fix-clone-from-nfs-image-cache-2218fb402783bc20.yaml @ b'beed5c7789d4d05137a1f8dce87c56a7c3500cdf'

- Fixed an issue where the NetApp cDOT NFS driver failed to clone new volumes from the image cache.

.. releasenotes/notes/fix-extend-volume-in-thin-pools-57a3d53be4d47704.yaml @ b'31dba529117eab92f7f8bdcd4f417430754fb9cc'

- Fixed volume extend issue that allowed a tenant with enough quota to extend the volume to limits greater than what the volume backend supported.

.. releasenotes/notes/fix-hnas-clone-with-different-volume-type-b969897cba2610cc.yaml @ b'd1f23f3634f032ee0eae26eee2c3057f309c674a'

- Fixed HNAS bug that placed a cloned volume in the same pool as its source, even if the clone had a different pool specification. Driver will not allow to make clones using a different volume type anymore.

.. releasenotes/notes/kaminario-cinder-driver-bug-1646692-7aad3b7496689aa7.yaml @ b'c5630ce51dd7b3902bbf204707a3ae6674884109'

- Fixed Non-WAN port filter issue in Kaminario iSCSI driver.

.. releasenotes/notes/kaminario-cinder-driver-bug-1646766-fe810f5801d24f2f.yaml @ b'6d7125bdbce1c665c9c5e37e1f9928281279d475'

- Fixed issue of managing a VG with more than one volume in Kaminario FC and iSCSI Cinder drivers.

.. releasenotes/notes/solidfire-scaled-qos-9b8632453909e2db.yaml @ b'409391d6a607f5905d48e4885a174d1da9f6456b'

- For SolidFire, QoS specs are now checked to make sure they fall within the min and max constraints. If not the QoS specs are capped at the min or max (i.e. if spec says 50 and minimum supported is 100, the driver will set it to 100).


.. _Ocata Series Release Notes_10.0.0_stable_ocata_Other Notes:

Other Notes
-----------

.. releasenotes/notes/fix-extend-volume-in-thin-pools-57a3d53be4d47704.yaml @ b'31dba529117eab92f7f8bdcd4f417430754fb9cc'

- Now extend won't work on disabled services because it's going through the scheduler, unlike how it worked before.


