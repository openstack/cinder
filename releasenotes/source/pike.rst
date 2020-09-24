=========================
Pike Series Release Notes
=========================

.. _Pike Series Release Notes_11.2.2-15_stable_pike:

11.2.2-15
=========

.. _Pike Series Release Notes_11.2.2-15_stable_pike_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/kaminario-cinder-driver-bug-44c728f026394a85.yaml @ b'7dcd50a0bfc533221b52a2d5611ab4cc986311c9'

- Kaminario FC and iSCSI drivers: Fixed `bug 1829398
  <https://bugs.launchpad.net/cinder/+bug/1829398>`_ where
  force detach would fail.

.. releasenotes/notes/netapp-non-discovery-19af4e10f7b190ea.yaml @ b'd440a94baf360bb9b4b1dc0c83ee4559a8d80d13'

- NetApp iSCSI drivers no longer use the discovery mechanism for multipathing
  and they always return all target/portals when attaching a volume.  Thanks
  to this, volumes will be successfully attached even if the target/portal
  selected as primary is down, this will be the case for both, multipath and
  single path connections.


.. _Pike Series Release Notes_11.2.2_stable_pike:

11.2.2
======

.. _Pike Series Release Notes_11.2.2_stable_pike_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/vnx-update-sg-in-cache-3ecb673727bea79b.yaml @ b'dcfc2f3d5ac69e0fd0c6ecbdd6ce26ed1cecd96c'

- Dell EMC VNX Driver: Fixes `bug 1817385
  <https://bugs.launchpad.net/cinder/+bug/1817385>`__ to make sure the sg can
  be created again after it was destroyed under `destroy_empty_storage_group`
  setting to `True`.


.. _Pike Series Release Notes_11.2.1_stable_pike:

11.2.1
======

.. _Pike Series Release Notes_11.2.1_stable_pike_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/fix-cross-az-migration-ce97eff61280e1c7.yaml @ b'056281d1079deca7a1e7d5343eb0a7cdd691a859'

- Resolve issue with cross AZ migrations and retypes where the destination
  volume kept the source volume's AZ, so we ended up with a volume where the
  AZ does not match the backend. (bug 1747949)


.. _Pike Series Release Notes_11.2.0_stable_pike:

11.2.0
======

.. _Pike Series Release Notes_11.2.0_stable_pike_New Features:

New Features
------------

.. releasenotes/notes/bug-1730933-1bb0272e3c51eed3.yaml @ b'a1d67d52f79656ce9c7f4b326d2703d972c35d9a'

- The Quobyte Cinder driver now supports identifying Quobyte mounts
  via the mounts fstype field.

.. releasenotes/notes/feature-rbd-exclusive-pool-a9bdebdeb1f0bf37.yaml @ b'1dca272d8f47bc180cc481e6c6a835eda0bb06a8'

- When using the RBD pool exclusively for Cinder we can now set
  `rbd_exclusive_cinder_pool` to `true` and Cinder will use DB information
  to calculate provisioned size instead of querying all volumes in the
  backend, which will reduce the load on the Ceph cluster and the volume
  service.

.. releasenotes/notes/unity-enable-ssl-14db2497225c4395.yaml @ b'95fe19850e875d769e361eb78a9003af2ee3db56'

- Dell EMC Unity Cinder driver allows enabling/disabling the SSL verification. Admin can set `True` or `False` for `driver_ssl_cert_verify` to enable or disable this function, alternatively set the `driver_ssl_cert_path=<PATH>` for customized CA path. Both above 2 options should go under the driver section.

.. releasenotes/notes/unity-remove-empty-host-17d567dbb6738e4e.yaml @ b'66c50600def5f8f25106afaa316e7fc300d72c87'

- Dell EMC Unity Driver: Adds support for removing empty host. The new option
  named `remove_empty_host` could be configured as `True` to notify Unity
  driver to remove the host after the last LUN is detached from it.

.. releasenotes/notes/vmware-vmdk-snapshot-template-d3dcfc0906c02edd.yaml @ b'a5e86c387e67650451d957c5ef525b452203c2fd'

- VMware VMDK driver now supports vSphere template as a
  volume snapshot format in vCenter server. The snapshot
  format in vCenter server can be specified using driver
  config option ``vmware_snapshot_format``.


.. _Pike Series Release Notes_11.2.0_stable_pike_Known Issues:

Known Issues
------------

.. releasenotes/notes/feature-rbd-exclusive-pool-a9bdebdeb1f0bf37.yaml @ b'1dca272d8f47bc180cc481e6c6a835eda0bb06a8'

- If RBD stats collection is taking too long in your environment maybe even
  leading to the service appearing as down you'll want to use the
  `rbd_exclusive_cinder_pool = true` configuration option if you are using
  the pool exclusively for Cinder and maybe even if you are not and can live
  with the innacuracy.


.. _Pike Series Release Notes_11.2.0_stable_pike_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/vmware-vmdk-snapshot-template-d3dcfc0906c02edd.yaml @ b'a5e86c387e67650451d957c5ef525b452203c2fd'

- VMware VMDK driver will use vSphere template as the
  default snapshot format in vCenter server.


.. _Pike Series Release Notes_11.2.0_stable_pike_Security Issues:

Security Issues
---------------

.. releasenotes/notes/scaleio-zeropadding-a0273c56c4d14fca.yaml @ b'6309c097e653c5f8b40e0602950d0ef54a9efb37'

- Removed the ability to create volumes in a ScaleIO Storage Pool that has
  zero-padding disabled. A new configuration option
  ``sio_allow_non_padded_volumes`` has been added to override this new
  behavior and allow unpadded volumes, but should not be enabled if multiple
  tenants will utilize volumes from a shared Storage Pool.


.. _Pike Series Release Notes_11.2.0_stable_pike_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1775518-fix-unity-empty-list-issue-2d6b7c33aae1ffcc.yaml @ b'b8b5de985359fe07f235e8c10f375246b1608fbb'

- Dell EMC Unity: Fixes bug 1775518 to make sure driver succeed
  to initialize even though the value of unity_io_ports and
  unity_storage_pool_names are empty

.. releasenotes/notes/bug-1799221-fix-truncated-volumes-in-case-of-glance-errors-6cae19218249c3cf.yaml @ b'0551f0a9ff7b787fcb3e1b686b83e25f99cad874'

- Fixed a bug which could create volumes with invalid content in case of
  unhandled errors from glance client
  (Bug `#1799221 <https://bugs.launchpad.net/cinder/+bug/1799221>`_).

.. releasenotes/notes/fix-import-backup-quota-issue-8yh69hd19u7tuu23.yaml @ b'40f5aef94a88a55cd20aad02e4f9ff2c38943b77'

- Cinder will now consume quota when importing new backup resource.

.. releasenotes/notes/fix-netapp-cg-da4fd6c396e5bedb.yaml @ b'fcae2f086f159b865a3624bfcff125a56f298fd2'

- Fixes a bug in NetApp SolidFire where the deletion of group snapshots was failing.

.. releasenotes/notes/fix-netapp-force_detach-36bdf75dd2c9a030.yaml @ b'90233982d249486aebaa996db744e3820aee1ddb'

- Fixes force_detach behavior for volumes in NetApp SolidFire driver.

.. releasenotes/notes/fix-quota-deleting-temporary-volume-274e371b425e92cc.yaml @ b'9bd60bbdb997c07ce22d590dfc66272ac5325836'

- Fix a quota usage error triggered by a non-admin user backing up an
  in-use volume. The forced backup uses a temporary volume, and quota
  usage was incorrectly updated when the temporary volume was deleted
  after the backup operation completed.
  Fixes `bug 1778774 <https://bugs.launchpad.net/tripleo/+bug/1778774>`__.

.. releasenotes/notes/netapp-ontap-fix-force-detach-55be3f4ac962b493.yaml @ b'93399a32bf994a3129a798be72f27a9731cb2750'

- Fixed bug #1783582, where calls to os-force_detach were failing on NetApp
  ONTAP iSCSI/FC drivers.

.. releasenotes/notes/unity-return-logged-out-initiator-6ab1f96f21bb284c.yaml @ b'f85193b5be6f4b69cf91137c40a34c64af676f52'

- Dell EMC Unity Driver: Fixes `bug 1773305
  <https://bugs.launchpad.net/cinder/+bug/1773305>`__
  to return the targets which connect to the logged-out initiators. Then the
  zone manager could clean up the FC zone based on the correct target wwns.


.. _Pike Series Release Notes_11.1.1_stable_pike:

11.1.1
======

.. _Pike Series Release Notes_11.1.1_stable_pike_New Features:

New Features
------------

.. releasenotes/notes/vnx-add-force-detach-support-26f215e6f70cc03b.yaml @ b'c0935c030266398a89ffcb1ebbfdb2d38a2197c2'

- Add support to force detach a volume from all hosts on VNX.


.. _Pike Series Release Notes_11.1.1_stable_pike_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1632333-netapp-ontap-copyoffload-downloads-glance-image-twice-08801d8c7b9eed2c.yaml @ b'82a13da48e7451c2f7813bf2de6990625c05624c'

- Fixed bug 1632333 with the NetApp ONTAP Driver. Now the copy offload method is invoked
  early to avoid downloading Glance images twice.

.. releasenotes/notes/bug-1690954-40fc21683977e996.yaml @ b'fd2c17edc0332e20149e1aed652a613f2f90de61'

- NetApp ONTAP NFS (bug 1690954): Fix wrong usage of export path
  as volume name when deleting volumes and snapshots.

.. releasenotes/notes/bug-1712651-7bc90264eb5001ea.yaml @ b'e7d8a3997938e20541c9f00d508ffaee75a7c7ba'

- NetApp ONTAP iSCSI (bug 1712651): Fix ONTAP NetApp iSCSI driver not
  raising a proper exception when trying to extend an attached volume
  beyond its max geometry.

.. releasenotes/notes/bug-1718739-netapp-eseries-fix-provisioned-capacity-report-8c51fd1173c15dbf.yaml @ b'e2b755590a952dbdd490d0d02f53cf6852463cce'

- NetApp E-series (bug 1718739):The NetApp E-series driver has been fixed to correctly report the "provisioned_capacity_gb". Now it sums the capacity of all the volumes in the configured backend to get the correct value. This bug fix affects all the protocols supported by the driver (FC and iSCSI).

.. releasenotes/notes/bug-1762424-f76af2f37fe408f1.yaml @ b'e3145a30cf3d904cba05834086039487dddcf714'

- NetApp ONTAP (bug 1762424): Fix ONTAP NetApp driver not being able to extend
  a volume to a size greater than the corresponding LUN max geometry.

.. releasenotes/notes/dell-emc-sc-bugfix-1756914-ffca3133273040f6.yaml @ b'adf7d84b66fdbbfba03721cc5f3f1f392a702eb4'

- Dell EMC SC driver correctly returns initialize_connection data when more than one IQN is attached to a volume. This fixes some random Nova Live Migration failures where the connection information being returned was for an IQN other than the one for which it was being requested.

.. releasenotes/notes/fail-detach-lun-when-auto-zone-enabled-9c87b18a3acac9d1.yaml @ b'ead818199e07923760e525c0367c9dcb5f4ab343'

- Dell EMC Unity Driver: Fixes `bug 1759175
  <https://bugs.launchpad.net/cinder/+bug/1759175>`__
  to detach the lun correctly when auto zone was enabled and the lun was the
  last one attached to the host.

.. releasenotes/notes/fix-abort-backup-df196e9dcb992586.yaml @ b'94393daaa057b604ab212a99cd5cd18c693c95c1'

- We no longer leave orphaned chunks on the backup backend or leave a
  temporary volume/snapshot when aborting a backup.

.. releasenotes/notes/netapp-ontap-use_exact_size-d03c90efbb8a30ac.yaml @ b'3e462d29f47594ab485aa8eb8091929ee9c30516'

- Fixed bug #1731474 on NetApp Data ONTAP driver that was causing LUNs to be created
  with larger size than requested. This fix requires version 9.1 of ONTAP
  or later.

.. releasenotes/notes/netapp_fix_svm_scoped_permissions.yaml @ b'0cc92ee4b5d3f4c87ed40685246537c7fbfa1891'

- NetApp cDOT block and file drivers have improved support for SVM scoped user accounts. Features not supported for SVM scoped users include QoS, aggregate usage reporting, and dedupe usage reporting.

.. releasenotes/notes/unity-force-detach-7c89e72105f9de61.yaml @ b'25d76990d0f2c4fb9dba6a7424e7f0c89d1c70a3'

- Corrected support to force detach a volume from all hosts on Unity.


.. _Pike Series Release Notes_11.0.2_stable_pike:

11.0.2
======

.. _Pike Series Release Notes_11.0.2_stable_pike_New Features:

New Features
------------

.. releasenotes/notes/k2-disable-discovery-bca0d65b5672ec7b.yaml @ b'7bcb2ff94cf38eaa9def1115569981760e36510c'

- Kaminario K2 iSCSI driver now supports non discovery multipathing (Nova and
  Cinder won't use iSCSI sendtargets) which can be enabled by setting
  `disable_discovery` to `true` in the configuration.


.. _Pike Series Release Notes_11.0.2_stable_pike_Known Issues:

Known Issues
------------

.. releasenotes/notes/k2-non-unique-fqdns-b62a269a26fd53d5.yaml @ b'c11b6a9da277f91d86a963db48045d9dcc44deca'

- Kaminario K2 now supports networks with duplicated FQDNs via configuration
  option `unique_fqdn_network` so attaching in these networks will work
  (bug #1720147).


.. _Pike Series Release Notes_11.0.2_stable_pike_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/ps-duplicate-ACL-5aa447c50f2474e7.yaml @ b'1efed3a4345a3a6d51172fad726aa48a972008e8'

- Dell EMC PS Series Driver code was creating duplicate ACL records during live migration. Fixes the initialize_connection code to not create access record for a host if one exists previously. This change fixes bug 1726591.

.. releasenotes/notes/ps-extend_volume-no-snap-8aa447c50f2475a7.yaml @ b'1e5cd9ba2a7906a182b0f2b0d7678213d80cd493'

- Dell EMC PS Series Driver was creating unmanaged snapshots when extending volumes. Fixed it by adding the missing no-snap parameter. This change fixes bug 1720454.


.. _Pike Series Release Notes_11.0.1_stable_pike:

11.0.1
======

.. _Pike Series Release Notes_11.0.1_stable_pike_New Features:

New Features
------------

.. releasenotes/notes/rbd-stats-report-0c7e803bb0b1aedb.yaml @ b'8d7f37e810d3228d8b79e4add1a383abe516d9bb'

- RBD driver supports returning a static total capacity value instead of a
  dynamic value like it's been doing.  Configurable with
  `report_dynamic_total_capacity` configuration option.


.. _Pike Series Release Notes_11.0.1_stable_pike_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1714209-netapp-ontap-drivers-oversubscription-issue-c4655b9c4858d7c6.yaml @ b'558571b44d9cd2195993e42539fd2c689b179ee6'

- If using the NetApp ONTAP drivers (7mode/cmode), the configuration value for "max_over_subscription_ratio" may need to be increased to avoid scheduling problems where storage pools that previously were valid to schedule new volumes suddenly appear to be out of space to the Cinder scheduler. See documentation `here <https://docs.openstack .org/cinder/latest/admin/blockstorage-over-subscription.html>`_.

.. releasenotes/notes/rbd-stats-report-0c7e803bb0b1aedb.yaml @ b'8d7f37e810d3228d8b79e4add1a383abe516d9bb'

- RBD/Ceph backends should adjust `max_over_subscription_ratio` to take into
  account that the driver is no longer reporting volume's physical usage but
  it's provisioned size.


.. _Pike Series Release Notes_11.0.1_stable_pike_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1714209-netapp-ontap-drivers-oversubscription-issue-c4655b9c4858d7c6.yaml @ b'558571b44d9cd2195993e42539fd2c689b179ee6'

- The ONTAP drivers ("7mode" and "cmode") have been fixed to not report consumed space as "provisioned_capacity_gb". They instead rely on the cinder scheduler's calculation of "provisioned_capacity_gb". This fixes the oversubscription miscalculations with the ONTAP drivers. This bugfix affects all three protocols supported by these drivers (iSCSI/FC/NFS).

.. releasenotes/notes/ps-optimize-parsing-8aa447c50f2474c7.yaml @ b'dbde6a3cad318ad8a9e23e23184bccb442b069aa'

- Dell EMC PS Series Driver code reporting volume stats is now optimized to return the information earlier and accelerate the process. This change fixes bug 1661154.

.. releasenotes/notes/ps-over-subscription-ratio-cal-8aa447c50f2474a8.yaml @ b'a6632b7a79a13e3611801080dfdb4131b90985a5'

- Dell EMC PS Driver stats report has been fixed, now reports the
  `provisioned_capacity_gb` properly. Fixes bug 1719659.

.. releasenotes/notes/rbd-stats-report-0c7e803bb0b1aedb.yaml @ b'8d7f37e810d3228d8b79e4add1a383abe516d9bb'

- RBD stats report has been fixed, now properly reports
  `allocated_capacity_gb` and `provisioned_capacity_gb` with the sum of the
  sizes of the volumes (not physical sizes) for volumes created by Cinder and
  all available in the pool respectively.  Free capacity will now properly
  handle quota size restrictions of the pool.


.. _Pike Series Release Notes_11.0.0_stable_pike:

11.0.0
======

.. _Pike Series Release Notes_11.0.0_stable_pike_Prelude:

Prelude
-------

.. releasenotes/notes/add-cg-capability-to-groups-2eb3e71682a88600.yaml @ b'aa277fe1b606525e724af0d3e432edff90310903'

Drivers supporting consistent group snapshot in generic volume groups reports "consistent_group_snapshot_enabled = True" instead of "consistencygroup_support = True". As a result, a spec such as "consistencygroup_support: '<is> True'" in either group type or volume type will cause the scheduler not to choose the backend that does not report "consistencygroup_support = True".
In order to create a generic volume group that supports consistent group snapshot, "consistent_group_snapshot_enable: '<is> True'" should be set in the group type specs and volume type extra specs, and "consistencygroup_support: '<is> True'" should not be set in group type spec and volume type extra specs.


.. _Pike Series Release Notes_11.0.0_stable_pike_New Features:

New Features
------------

.. releasenotes/notes/Enable-HPE-3PAR-Compression-Feature-90e4de4b64a74a46.yaml @ b'd7940f57438a7e10d74bffdbc0240867b52ae341'

- HPE 3PAR driver adds following functionalities Creating thin/dedup compresssed volume. Retype for tpvv/tdvv volumes to be compressed. Migration of compressed volumes. Create compressed volume from compressed volume/snapshot source. Compression support to create cg from source.

.. releasenotes/notes/HPE-3par-Generic-Volume-Group-e048002e1c3469a3.yaml @ b'fadefc8206a612f035ce0530ce97c6703c4957b1'

- Added consistency group capability to generic volume groups in the HPE 3PAR driver.

.. releasenotes/notes/Lefthand-generic-volume-group-570d07b4786b93c2.yaml @ b'81ece6a9f2ac9b4ff3efe304bab847006f8b0aef'

- Add consistent group capability to generic volume groups in Lefthand driver.

.. releasenotes/notes/SolidFire-generic-volume-group-1b1e55661cd83a43.yaml @ b'1cbf1194203945308bfcae2656e800e5b084275f'

- Add consistent group capability to generic volume groups in the SolidFire driver.

.. releasenotes/notes/add-connection-info-to-attachment-84d4dg45uh41db15.yaml @ b'8031fb1e98f189b165f00c919f4f33d9e0d01226'

- Added attribute ``connection_info`` to attachment object.

.. releasenotes/notes/add-filters-support-to-get_pools-0852e9c0e42fbf98.yaml @ b'ba80322a5789a4b240108a7911db9235e8140016'

- Add filters support to get_pools API v3.28.

.. releasenotes/notes/add-like-filter-support-7d4r78d6de3984dv.yaml @ b'6df8415411f5166a8682114cb8a972d3b51a47e3'

- Added like operator support to filters for the following resources::

  - volume
  - snapshot
  - backup
  - group
  - group-snapshot
  - attachment
  - message

.. releasenotes/notes/add-periodic-task-to-clean-expired-messages-84f47gxc88hda035.yaml @ b'c1cb931ecbb785e7196c233087ee368474b604a4'

- Added periodic task to clean expired messages in cinder scheduler, also added a configuration option ``message_reap_interval`` to handle the interval.

.. releasenotes/notes/add-resource-filters-api-8g3dub1700qaye98.yaml @ b'8fcb809509fbdd4d5b0ecee2c33fa44f405b4aeb'

- Added ``resource_filters`` API to retrieve configured resource filters.

.. releasenotes/notes/add-revert-to-snapshot-support-2d21a3dv4f5fa087.yaml @ b'8fba9a90807714f8869c470af6e28bb1da027a54'

- Add revert to snapshot API and support in LVM driver.

.. releasenotes/notes/add-volume-type-filter-to_get-pools-c791132540921398.yaml @ b'd5a3fdabca25a63bd3d01c86442ef649e7613aff'

- Add ``volume-type`` filter to API Get-Pools

.. releasenotes/notes/add_ceph_custom_keyring_path-43a3b8c21a1ab3c4.yaml @ b'd0520a07e9dcee53fe2f13900f4c36c7e455c6f0'

- Added RBD keyring configuration parameter ``rbd_keyring_conf`` to define
  custom path of Ceph keyring file.

.. releasenotes/notes/allow-huawei-driver-lun-copy-speed-configurable-361a480e7b7e361d.yaml @ b'045b1647c0ae4c03ee588ca7874fd4a9aa7f6879'

- Allow users to specify the copy speed while using Huawei driver to create volume from snapshot or clone volume, by the new added metadata 'copyspeed'. For example, user can add --metadata copyspeed=1 when creating volume from source volume/snapshot. The valid optional range of copyspeed is [1, 2, 3, 4], respectively representing LOW, MEDIUM, HIGH and HIGHEST.

.. releasenotes/notes/backup-ceph-driver-journaling-exculsive-lock-features-6b6044138a288a83.yaml @ b'dc96c948f7b69d5b60f10fb6ad130226bdfab368'

- Added new BoolOpt ``backup_ceph_image_journals`` for enabling the Ceph image features required to support RBD mirroring of Cinder backup pool.

.. releasenotes/notes/bug-1614095-add-user_id-to-snapshot_show-4884fab825983c3a.yaml @ b'b1e2b0459ca4dd5b84eb8fcb66e4a2414c154183'

- Add ``user_id`` field to snapshot list/detail and snapshot show.

.. releasenotes/notes/coprhd-generic-volume-group-a1d41d439f94ae19.yaml @ b'b248aad12a223095b22b312b16b18c108df81fd4'

- Add consistent group capability to generic volume groups in CoprHD driver.

.. releasenotes/notes/datera-2.4.0-driver-update-164bbc77e6b45eb7.yaml @ b'1e23faf82a3babe710e9c7a1264925cb32c6f78d'

- Added ``datera_disable_profiler`` boolean config option.

.. releasenotes/notes/datera-2.4.0-driver-update-164bbc77e6b45eb7.yaml @ b'1e23faf82a3babe710e9c7a1264925cb32c6f78d'

- Added Cinder fast-retype support to Datera EDF driver.

.. releasenotes/notes/datera-2.4.0-driver-update-164bbc77e6b45eb7.yaml @ b'1e23faf82a3babe710e9c7a1264925cb32c6f78d'

- Added Volume Placement extra-specs support to Datera EDF driver.

.. releasenotes/notes/datera-2.4.0-driver-update-164bbc77e6b45eb7.yaml @ b'1e23faf82a3babe710e9c7a1264925cb32c6f78d'

- Fixed ACL multi-attach bug in Datera EDF driver.

.. releasenotes/notes/datera-2.4.0-driver-update-164bbc77e6b45eb7.yaml @ b'1e23faf82a3babe710e9c7a1264925cb32c6f78d'

- Fixed a few scalability bugs in the Datera EDF driver.

.. releasenotes/notes/dell-emc-sc-support-generic-groups-98c7452d705b36f9.yaml @ b'bd619f2ceac28eabb78e6fcb9fff54348463bf44'

- Add consistency group capability to Generic Volume Groups in the Dell EMC SC driver.

.. releasenotes/notes/ds8k-replication-group-3f2e8cd3c2e291a3.yaml @ b'b5e46bb9bb4ad37dba01011d8d8f12eb99916cf9'

- Add replication consistency group support in DS8K cinder driver.

.. releasenotes/notes/ds8k_specify_pool_lss-5329489c263951ba.yaml @ b'b401355c6ffa8e933b72ec9db63496da6998c1f5'

- DS8K driver adds two new properties into extra-specs so that user can specify pool or lss or both of them to allocate volume in their expected area.

.. releasenotes/notes/falconstor-extend-driver-to-utilize-multiple-fss-pools-dc6f2bc84432a672.yaml @ b'213001f931c469bd16f2558b91eef8152caf8fab'

- Added ability to specify multiple storage pools in the FalconStor driver.

.. releasenotes/notes/generalized-resource-filter-hg598uyvuh119008.yaml @ b'dc31763c582169509ed2f1c3cacd3b6950baa44c'

- Added generalized resource filter support in ``list volume``, ``list backup``, ``list snapshot``, ``list group``, ``list group-snapshot``, ``list attachment``, ``list message`` and ``list pools`` APIs.

.. releasenotes/notes/generic-group-quota-manage-support-559629ad07a406f4.yaml @ b'608de666fabf9ab65fa905a3b9a95f7cbad83013'

- Generic group is added into quota management.

.. releasenotes/notes/generic-groups-in-gpfs-00bb093945a02642.yaml @ b'6252bd8e5ad77e52e720132455ccc3410d45bf65'

- Added consistent group capability to generic volume groups in GPFS driver.

.. releasenotes/notes/huawei-generic-group-bc3fb7236efc58e7.yaml @ b'2e06995ad5153f5d76ad9ba0f0ca0e2134fea43c'

- Add CG capability to generic volume groups in Huawei driver.

.. releasenotes/notes/ibm-storwzie-mirror-volume-ffe4c9bde78cdf1d.yaml @ b'76fc4edc64b04d6a736387f1b0f1acdff815e496'

- Add mirrored volume support in IBM SVC/Storwize driver.

.. releasenotes/notes/ibmsvciogrpselection-e607739b6f655a27.yaml @ b'edfa61c61f1ff007f43051591dfccaccd61ba4ac'

- In IBM Storwize_SVC driver, user could specify only one IO
  group per backend definition. The user now may specify a comma separated
  list of IO groups, and at the time of creating the volume, the driver will
  select an IO group which has the least number of volumes associated with
  it. The change is backward compatible, meaning single value is still
  supported.

.. releasenotes/notes/infinidat-compression-a828904aaba90da2.yaml @ b'ec55bc239caac7d849ab2aa7cbd0e0428aefc450'

- Added support for volume compression in INFINIDAT driver. Compression is available on InfiniBox 3.0 onward. To enable volume compression, set ``infinidat_use_compression`` to True in the backend section in the Cinder configuration file.

.. releasenotes/notes/infinidat-group-support-44cd0715de1ea502.yaml @ b'f308007862bd7362a509fc549f683b1aa94aa159'

- Add CG capability to generic volume groups in INFINIDAT driver.

.. releasenotes/notes/infinidat-iscsi-support-78e0d34d9e7e08c4.yaml @ b'747d4464c7fd8ea75711874e467f9cdede7560bf'

- Support for iSCSI in INFINIDAT InfiniBox driver.

.. releasenotes/notes/infinidat-qos-50d743591543db98.yaml @ b'd5030ca7d57532957bb4c1e6a395fe0f3e091cb6'

- Added support for QoS in the INFINIDAT InfiniBox driver. QoS is available on InfiniBox 4.0 onward.

.. releasenotes/notes/metadata-for-volume-summary-729ba648db4e4e54.yaml @ b'bf40945dccacdc4c75c1afb2f963f2668525f9f8'

- Added support for get all distinct volumes' metadata from volume-summary API.

.. releasenotes/notes/nec-nondisruptive-backup-471284d07cd806ce.yaml @ b'55e8befc4cf5cfa0ba544cefcebc475016f2a930'

- Enable backup snapshot optimal path by implementing attach and detach snapshot in the NEC driver.

.. releasenotes/notes/netapp-add-generic-group-support-cdot-9bebd13356694e13.yaml @ b'0215fcc022d60608a0d887dd6510496ab2162f5b'

- Added generic volume group capability to NetApp cDot drivers with support for write consistent group snapshots.

.. releasenotes/notes/new-nova-config-section-2a7a51a0572e7064.yaml @ b'9f213981ac349e0fa22a1aed217dbe7aee3813ae'

- a [nova] section is added to configure the connection to the compute service, which is needed to the InstanceLocalityFilter, for example.

.. releasenotes/notes/per-backend-az-28727aca360a1cc8.yaml @ b'7c1e92278cce54a3a0cb3dc9a059988ddc2ec3bc'

- Availability zones may now be configured per backend in a multi-backend
  configuration. Individual backend sections can now set the configuration
  option ``backend_availability_zone``. If set, this value will override
  the [DEFAULT] ``storage_availability_zone`` setting.

.. releasenotes/notes/period-task-clean-reservation-0e0617a7905df923.yaml @ b'07f242d68cac8c23e92a1ebc64094b0df26e7812'

- Added periodic task to clean expired reservation in cinder scheduler. Added a configuration option ``reservation_clean_interval`` to handle the interval.

.. releasenotes/notes/prophetstor-generic-groups-c7136c32b2f75c0a.yaml @ b'3cc8eef15df76d99bdcb3cbe5b89d7b6f0a5436b'

- Added consistent group capability to generic volume groups in ProphetStor driver.

.. releasenotes/notes/rbd-support-managing-existing-snapshot-fb871a3ea98dc572.yaml @ b'e5abf57fe985fd0e837e3d92c0087dfbe13ad56c'

- Allow rbd driver to manage existing snapshot.

.. releasenotes/notes/replication-group-7c6c8a153460ca58.yaml @ b'18744ba1991a7e1599d256857727454bac1ae2d2'

- Introduced replication group support and added group action APIs
  enable_replication, disable_replication, failover_replication and
  list_replication_targets.

.. releasenotes/notes/scaleio-generic-volume-group-ee36e4dba8893422.yaml @ b'fcbd762d9d7923ac403324c8aafa6731cb52632a'

- Added consistency group support to generic volume groups in ScaleIO Driver.

.. releasenotes/notes/scaleio-get-manageable-volumes-dda1e7b8e22be59e.yaml @ b'c129e80cb0f985f0d16af59360affd1dc377f707'

- Added ability to list all manageable volumes within ScaleIO Driver.

.. releasenotes/notes/service_dynamic_log_change-55147d288be903f1.yaml @ b'a60a09ce5fec847ee4af1cf2661f04ad15459c98'

- Added new APIs on microversion 3.32 to support dynamically changing log
  levels in Cinder services without restart as well as retrieving current log
  levels, which is an easy way to ping via the message broker a service.

.. releasenotes/notes/shared-backend-config-d841b806354ad5be.yaml @ b'76016fffc946301ba4df6b2b58713dcb41d45dff'

- New config format to allow for using shared Volume Driver configuration defaults via the [backend_defaults] stanza. Config options defined there will be used as defaults for each backend enabled via enabled_backends.

.. releasenotes/notes/smbfs-pools-support-bc43c653cfb1a34f.yaml @ b'd60f1a8a7c58e3413d966f449e5139f1da3e3a01'

- The SMBFS driver now exposes share information to the scheduler via pools.
  The pool names are configurable, defaulting to the share names.

.. releasenotes/notes/storwize-generic-volume-group-74495fa23e059bf9.yaml @ b'103870f40d8a65892dab1edc69413c3e16321edd'

- Add consistency group capability to generic volume groups in Storwize drivers.

.. releasenotes/notes/storwize-gmcv-support-8aceee3f40eddb9f.yaml @ b'b03992b6161ea1852b2abad9f04062bebd51a10c'

- Add global mirror with change volumes(gmcv) support and user can manage gmcv replication volume by SVC driver. An example to set a gmcv replication volume type, set property replication_type as "<in> gmcv", property replication_enabled as "<is> True" and set property drivers:cycle_period_seconds as 500.

.. releasenotes/notes/support-extend-inuse-volume-9e4atf8912qaye99.yaml @ b'3dd842de8282efc95f3727d486cfc061888fe0a5'

- Add ability to extend ``in-use`` volume. User should be aware of the
  whole environment before using this feature because it's dependent
  on several external factors below:

  * nova-compute version - needs to be the latest for Pike.
  * only the libvirt compute driver supports this currently.
  * only iscsi and fibre channel volume types are supported on the nova side currently.

  Administrator can disable this ability by updating the
  ``volume:extend_attached_volume`` policy rule.

.. releasenotes/notes/support-metadata-for-backup-3d8753f67e2934fa.yaml @ b'39c732bbce64665531140411669d3bd163d513cf'

- Added metadata support for backup source. Now users can create/update metadata for a specified backup.

.. releasenotes/notes/support-project-id-filter-for-limit-bc5d49e239baee2a.yaml @ b'4a2448bd15a0191df8bb4710870e2e0b5750278a'

- Supported ``project_id`` admin filters to limits API.

.. releasenotes/notes/support_sort_backup_by_name-0b080bcb60c0eaa0.yaml @ b'2c7758d4513fa257b0d684de878f921184b47ae1'

- Add support for sorting backups by "name".

.. releasenotes/notes/support_sort_snapshot_with_name-7b66a2d8e587275d.yaml @ b'8b5264f559e60a8947f9d879070ff67960ae86f3'

- Support to sort snapshots with "name".

.. releasenotes/notes/unity-fast-clone-02ae88ba8fdef145.yaml @ b'a6c22238e1021f51d0348e58402db4f56dbe539d'

- Add thin clone support in the Unity driver. Unity storage supports the thin clone of a LUN from OE version 4.2.0. It is more efficient than the dd solution. However, there is a limit of thin clone inside each LUN family. Every time the limit reaches, a new LUN family will be created by a dd-copy, and then the volume clone afterward will use the thin clone of the new LUN family.

.. releasenotes/notes/verbose-online-migrations-94fb7e8a85cdbc10.yaml @ b'939fa2c0ff6527258a9b4e17be8f0f5a765eefce'

- The cinder-manage online_data_migrations command now prints a tabular summary of completed and remaining records. The goal here is to get all your numbers to zero. The previous execution return code behavior is retained for scripting.

.. releasenotes/notes/veritas_access_driver-c73b2320ba9f46a8.yaml @ b'5993af92ef9fe86e23942b6c0e2188c4831de8f8'

- Added NFS based driver for Veritas Access.

.. releasenotes/notes/vmax-generic-volume-group-28b3b2674c492bbc.yaml @ b'1ee279bd901b36e3ca84500a4d7339b09aa84524'

- Add consistent group snapshot support to generic volume groups in
  VMAX driver version 3.0.

.. releasenotes/notes/vmax-rest-94e48bed6f9c134c.yaml @ b'f6d9fbadb23a5dcd7aea026895b38e11f1d3ec2a'

- VMAX driver version 3.0, replacing SMI-S with Unisphere REST.
  This driver supports VMAX3 hybrid and All Flash arrays.

.. releasenotes/notes/vmax-rest-compression-10c2590052a9465e.yaml @ b'51252cf5049e1e714411ea7ce3f309c31e51822a'

- Adding compression functionality to VMAX driver version 3.0.

.. releasenotes/notes/vmax-rest-livemigration-885dd8731d5a8a88.yaml @ b'dd065f8e191ffb2762e4cd75a1350e41aed0caae'

- Adding Live Migration functionality to VMAX driver version 3.0.

.. releasenotes/notes/vmax-rest-qos-6bb4073b92c932c6.yaml @ b'95dd5b488142801a7cac575b1901938051bee1bf'

- Adding Qos functionality to VMAX driver version 3.0.

.. releasenotes/notes/vmax-rest-replication-612fcfd136cc076e.yaml @ b'22eb9b69c1c7ee11ab5cfdec4957ce7b86ccbf14'

- Adding Replication V2.1 functionality to VMAX driver version 3.0.

.. releasenotes/notes/vmax-rest-retype-ceba5e8d04f637b4.yaml @ b'2f08c8dea3c4506ce186ac6ab58148f734cfacca'

- Add retype functionality to VMAX driver version 3.0.

.. releasenotes/notes/vmware_adapter_type-66164bc3857f244f.yaml @ b'8dbf2b7e980678f3f7dd8a0071d5f70cc3ad266a'

- VMware VMDK driver now supports volume type extra-spec
  option ``vmware:adapter_type`` to specify the adapter
  type of volumes in vCenter server.

.. releasenotes/notes/vmware_vmdk_default_adapter_type-8e247bce5b229c7a.yaml @ b'fdd49d09a6c85b4b07be18d56ac29c5af2ac224f'

- Added config option ``vmware_adapter_type`` for the VMware VMDK driver to specify the default adapter type for volumes in vCenter server.

.. releasenotes/notes/vnx-qos-support-7057196782e2c388.yaml @ b'93993a0cedbe2105d7481fda0b1f83dee0a63fe4'

- Adds QoS support for VNX Cinder driver.

.. releasenotes/notes/vnx-replication-group-2ebf04c80e2171f7.yaml @ b'c52323babd11432156eaa7cb44ee16c766b70f6a'

- Add consistent replication group support in VNX cinder driver.

.. releasenotes/notes/vrts_hyperscale_driver-5b63ab706ea8ae89.yaml @ b'2902da9c58fb531a719036583885f8894ae6ac2d'

- Added volume backend driver for Veritas HyperScale storage.

.. releasenotes/notes/win-iscsi-config-portals-51895294228d7883.yaml @ b'b2ddad27522a79e7d18e5a6c74776c82faf12fc6'

- The Windows iSCSI driver now returns multiple portals when available
  and multipath is requested.

.. releasenotes/notes/xiv-generic-volume-group-4609cdc86d6aaf81.yaml @ b'23cf5b08ce4149da62c720a28dfb2c90fef57d25'

- Add consistent group capability to generic volume groups in XIV, Spectrum Accelerate and A9000/R storage systems.

.. releasenotes/notes/xiv-new-qos-independent-type-58885c77efe24798.yaml @ b'9b088ca82a2612f0cf73cfa6bc670c6e5b5f64b6'

- Added independent and shared types for qos classes in XIV & A9000. Shared type enables to share bandwidth and IO rates between volumes of the same class. Independent type gives each volume the same bandwidth and IO rates without being affected by other volumes in the same qos class.

.. releasenotes/notes/xiv-replication-group-7ca437c90f2474a7.yaml @ b'bb9a4e1a90e6223a3602172336c8b45f578df55f'

- Add consistency group replication support in XIV\A9000 Cinder driver.


.. _Pike Series Release Notes_11.0.0_stable_pike_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/db-schema-from-mitaka-168ac06161e9ca0d.yaml @ b'5f95cbded70f2ecfc0e7e4d8dd5ca84b8e2575df'

- The Cinder database can now only be upgraded from changes since the Mitaka release. In order to upgrade from a version prior to that, you must now upgrade to at least Mitaka first, then to Pike or later.

.. releasenotes/notes/disco-options-94fe9eaad5e397a5.yaml @ b'7999271653b99d40335b288a55e91de077148cc1'

- Some of DISCO driver options were incorrectly read from ``[DEFAULT]``
  section in the cinder.conf. Now those are correctly read from
  ``[<backend_id>]`` section. This includes following options:

  * ``disco_client``
  * ``disco_client_port``
  * ``rest_ip``
  * ``choice_client``
  * ``disco_src_api_port``
  * ``retry_interval``

  Also some options are renamed (note that 3 of them were both moved and
  renamed):

  * ``rest_ip`` to ``disco_rest_ip``
  * ``choice_client`` to ``disco_choice_client``
  * ``volume_name_prefix`` to ``disco_volume_name_prefix``
  * ``snapshot_check_timeout`` to ``disco_snapshot_check_timeout``
  * ``restore_check_timeout`` to ``disco_restore_check_timeout``
  * ``clone_check_timeout`` to ``disco_clone_check_timeout``
  * ``retry_interval`` to ``disco_retry_interval``

  Old names and locations are still supported but support will be removed in
  the future.

.. releasenotes/notes/dothill-drivers-removed-da00a6b83865271a.yaml @ b'76522b90a3c960ef15f0ad6ce37d24e556b9a5a8'

- Support for Dot Hill AssuredSAN arrays has been removed.

.. releasenotes/notes/hnas-remove-iscsi-driver-419e9c08133f9f0a.yaml @ b'6c603df9ca240299b706a9b6c19bbeb347539ce3'

- The Hitachi NAS Platform iSCSI driver was marked as not supported in the Ocata realease and has now been removed.

.. releasenotes/notes/infinidat-infinisdk-04f0edc0d0a597e3.yaml @ b'921205a8f23001af2f98f621496d43594ca8c5b4'

- INFINIDAT volume driver now requires the 'infinisdk' python module to be installed.

.. releasenotes/notes/mark-blockbridge-unsupported-c9e55df0eb2e3c9f.yaml @ b'3f4916a87334c45e851909f9bcf16a669d368266'

- The Blockbridge driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_drivers`` will need to be set to
  ``True`` in cinder.conf to continue to use it.

.. releasenotes/notes/mark-coho-unsupported-989db9d88ed7fff8.yaml @ b'5aed3b1384526ad146b4b153eda935be356b5ed6'

- The Coho driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it.

.. releasenotes/notes/mark-falconstor-unsupported-3b065556a4cd94de.yaml @ b'314df517a56381c6be28f5919fd25db555b14579'

- The Falconstor drivers have been marked as unsupported and are now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it.

.. releasenotes/notes/mark-infortrend-deprecated-553de89f8dd58aa8.yaml @ b'19413e8abe50aa389213585cfd8591e0c0ac1987'

- The Infortrend drivers have been marked as unsupported
  and are now deprecated. ``enable_unsupported_driver`` will
  need to be set to ``True`` in the driver's section in
  cinder.conf to continue to use them.

.. releasenotes/notes/mark-qnap-unsupported-79bd8ece9a2bfcd2.yaml @ b'b59dc58723094f519b0e1d5613da5bc55124e58f'

- The QNAP driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_drivers`` will need to be set to
  ``True`` in cinder.conf to continue to use it.

.. releasenotes/notes/mark-reduxio-deprecated-b435032a8fdb16f2.yaml @ b'0953f1b6c21bf3737c656550bc21a1c63ec26988'

- The Reduxio driver has been marked unsupported and is now
  deprecated. ``use_unsupported_driver`` will need to be set to
  ``True`` in the driver's section in cinder.conf to use it.

.. releasenotes/notes/mark-synology-deprecated-134ba9764e14af67.yaml @ b'31ad999435d5e3b03cb96aeb4b8ebdcb2fff70c2'

- The Synology driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be
  set to ``True`` in the driver's section in ``cinder.conf`` to
  continue to use it.

.. releasenotes/notes/mark-tegile-deprecated-1effb23010ea997c.yaml @ b'943f3e0660b04e982f95ef5f2fe6385787f7d509'

- The Tegile driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it.

.. releasenotes/notes/mark-violin-unsupported-fdf6b34cf9847359.yaml @ b'061464fa0756f0037c525bac77c00247635a9951'

- The Violin drivers have been marked as unsupported and are now
  deprecated. ``enable_unsupported_drivers`` will need to be set to
  ``True`` in cinder.conf to continue to use them.

.. releasenotes/notes/mark-xio-deprecated-18c914e15695d793.yaml @ b'346f51e6cfae7d1586c7fbc27329ed9cf48aae5f'

- The X-IO driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it.

.. releasenotes/notes/mark-zte-unsupported-3c048e419264eca2.yaml @ b'54583a40dfc896b800d9ab3c8e4425da7a1a240b'

- The ZTE driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it.

.. releasenotes/notes/pure-default-replica-interval-07de0a56f61c7c1e.yaml @ b'0d02e6f6b15f290ead2f61a5b96411408519c122'

- The default value for pure_replica_interval_default used by Pure Storage volume drivers has changed from 900 to 3600 seconds.

.. releasenotes/notes/remove_service_filter-380e7990bfdbddc8.yaml @ b'fa3752efdb787c0e3e71f6690b701235e79ae697'

- The ``service`` filter for service list API was deprecated 3 years ago in 2013 July (Havana). Removed this filter and please use "binary" instead.

.. releasenotes/notes/removing-middleware-sizelimit-ba86907acbda83de.yaml @ b'644c50fe0e3d644d5bd7ebc25c4bcb1d5fe29a68'

- Removing deprecated file cinder.middleware.sizelimit. In your api-paste.ini, replace cinder.middleware.sizelimit:RequestBodySizeLimiter.factory with oslo_middleware.sizelimit:RequestBodySizeLimiter.factory

.. releasenotes/notes/snapshot_backing_up_status_support-164fbbb2a564e137.yaml @ b'9f213981ac349e0fa22a1aed217dbe7aee3813ae'

- The "backing-up" status is added to snapshot's status matrix.

.. releasenotes/notes/tooz-coordination-heartbeat-cfac1064fd7878be.yaml @ b'42dafd2705a8cb4346c396376977c705e55d9e7c'

- The coordination system used by Cinder has been simplified to leverage tooz
  builtin heartbeat feature. Therefore, the configuration options
  `coordination.heartbeat`, `coordination.initial_reconnect_backoff` and
  `coordination.max_reconnect_backoff` have been removed.

.. releasenotes/notes/type-extra-spec-policies-b7742b0ac2732864.yaml @ b'46d9b4091160d8aa957dd49a8b12c1c887da136a'

- When managing volume types an OpenStack provider is now given more control to grant
  access to for different storage type operations. The provider can now customize access
  to type create, delete, update, list, and show using new entries in the cinder policy file.

  As an example one provider may have roles called viewer, admin, type_viewer, and say
  type_admin. Admin and type_admin can create, delete, update types. Everyone can list
  the storage types. Admin, type_viewer, and type_admin can view the extra_specs.

  "volume_extension:types_extra_specs:create": "rule:admin or rule:type_admin",
  "volume_extension:types_extra_specs:delete": "rule:admin or rule:type_admin",
  "volume_extension:types_extra_specs:index": "",
  "volume_extension:types_extra_specs:show": "rule:admin or rule:type_admin or rule:type_viewer",
  "volume_extension:types_extra_specs:update": "rule:admin or rule:type_admin"

.. releasenotes/notes/use-glance-v2-api-and-deprecate-glance_api_version-1a3b698429cb754e.yaml @ b'a766fb0ead97ad4a67092e0f68ca1b9b25dbc17e'

- Cinder now defaults to using the Glance v2 API. The ``glance_api_version`` configuration option has been deprecated and will be removed in the 12.0.0 Queens release.

.. releasenotes/notes/vmware_vmdk_enforce_vc_55-7e1b3ede9bf2129b.yaml @ b'549092a5483d1e6e5693b3cec79d3dca20905717'

- The VMware VMDK driver now enforces minimum vCenter version of 5.5.


.. _Pike Series Release Notes_11.0.0_stable_pike_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/deprecate-api-v2-9f4543ab2e14b018.yaml @ b'f6d3454f608ec40570deb62997ccda8048f6e2dc'

- The Cinder v2 API has now been marked as deprecated. All new client code
  should use the v3 API. API v3 adds support for microversioned API calls.
  If no microversion is requested, the base 3.0 version for the v3 API is
  identical to v2.

.. releasenotes/notes/deprecate_osapi_volume_base_url-b6984886a902a562.yaml @ b'811395c6453c59abffadc9fd0c08e887b1a8b996'

- Instead of using osapi_volume_base_url use public_endpoint. Both do the same thing.

.. releasenotes/notes/falconstor-extend-driver-to-utilize-multiple-fss-pools-dc6f2bc84432a672.yaml @ b'213001f931c469bd16f2558b91eef8152caf8fab'

- The fss_pool option is deprecated. Use fss_pools instead.

.. releasenotes/notes/hitachi-unsupported-drivers-37601e5bfabcdb8f.yaml @ b'595c8d3f8523a9612ccc64ff4147eab993493892'

- The Hitachi Block Storage Driver (HBSD) and VSP driver have been marked as unsupported and are now deprecated. enable_unsupported_driver will need to be set to True in cinder.conf to continue to use them.

.. releasenotes/notes/hnas-deprecate-nfs-driver-0d114bbe141b5d90.yaml @ b'c37fcfa374f5719b7c527a19286e7950b0231b4d'

- The Hitachi NAS NFS driver has been marked as unsupported and is now deprecated. enable_unsupported_driver will need to be set to True in cinder.conf to continue to use it.

.. releasenotes/notes/mark-blockbridge-unsupported-c9e55df0eb2e3c9f.yaml @ b'3f4916a87334c45e851909f9bcf16a669d368266'

- The Blockbridge driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_drivers`` will need to be set to
  ``True`` in cinder.conf to continue to use it. If its support status
  does not change it will be removed in the next release.

.. releasenotes/notes/mark-coho-unsupported-989db9d88ed7fff8.yaml @ b'5aed3b1384526ad146b4b153eda935be356b5ed6'

- The Coho driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it. If its support status does not change, they will be
  removed in the Queens development cycle.

.. releasenotes/notes/mark-falconstor-unsupported-3b065556a4cd94de.yaml @ b'314df517a56381c6be28f5919fd25db555b14579'

- The Falconstor drivers have been marked as unsupported and are now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it. If its support status does not change, they will be
  removed in the Queens development cycle.

.. releasenotes/notes/mark-infortrend-deprecated-553de89f8dd58aa8.yaml @ b'19413e8abe50aa389213585cfd8591e0c0ac1987'

- The Infortrend drivers have been marked as unsupported
  and are now deprecated. ``enable_unsupported_driver`` will
  need to be set to ``True`` in the driver's section in
  cinder.conf to continue to use them. If their support
  status does not change, they will be removed in the Queens
  development cycle.

.. releasenotes/notes/mark-qnap-unsupported-79bd8ece9a2bfcd2.yaml @ b'b59dc58723094f519b0e1d5613da5bc55124e58f'

- The QNAP driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_drivers`` will need to be set to
  ``True`` in cinder.conf to continue to use it. If its support status
  does not change it will be removed in the next release.

.. releasenotes/notes/mark-reduxio-deprecated-b435032a8fdb16f2.yaml @ b'0953f1b6c21bf3737c656550bc21a1c63ec26988'

- The Reduxio driver has been marked unsupported and is now
  deprecated. ``use_unsupported_driver`` will need to be set to
  ``True`` in the driver's section in cinder.conf to use it.
  If its support status does not change, the driver will be
  removed in the Queens development cycle.

.. releasenotes/notes/mark-synology-deprecated-134ba9764e14af67.yaml @ b'31ad999435d5e3b03cb96aeb4b8ebdcb2fff70c2'

- The Synology driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be
  set to ``True`` in the driver's section in ``cinder.conf`` to
  continue to use it. If its support status does not change,
  the driver will be removed in the Queens development cycle.

.. releasenotes/notes/mark-tegile-deprecated-1effb23010ea997c.yaml @ b'943f3e0660b04e982f95ef5f2fe6385787f7d509'

- The Tegile driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it. If its support status does not change, they will be
  removed in the Queens development cycle.

.. releasenotes/notes/mark-violin-unsupported-fdf6b34cf9847359.yaml @ b'061464fa0756f0037c525bac77c00247635a9951'

- The Violin drivers have been marked as unsupported and are now
  deprecated. ``enable_unsupported_drivers`` will need to be set to
  ``True`` in cinder.conf to continue to use them. If its support status
  does not change it will be removed in the next release.

.. releasenotes/notes/mark-xio-deprecated-18c914e15695d793.yaml @ b'346f51e6cfae7d1586c7fbc27329ed9cf48aae5f'

- The X-IO driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it. If its support status does not change, they will be
  removed in the Queens development cycle.

.. releasenotes/notes/mark-zte-unsupported-3c048e419264eca2.yaml @ b'54583a40dfc896b800d9ab3c8e4425da7a1a240b'

- The ZTE driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it. If its support status does not change, they will be
  removed in the Queens development cycle.

.. releasenotes/notes/new-nova-config-section-2a7a51a0572e7064.yaml @ b'9f213981ac349e0fa22a1aed217dbe7aee3813ae'

- The os_privileged_xxx and nova_xxx in the [default] section are deprecated in favor of the settings in the [nova] section.

.. releasenotes/notes/remove-mirrorpolicy-parameter-from-huawei-driver-d32257a60d32fd90.yaml @ b'6e74dbd4c3c4d6a5d6d77998e48b690d23209366'

- Remove mirror policy parameter from huawei driver.

.. releasenotes/notes/scaleio-deprecate-1.32-32033134fec181bb.yaml @ b'a4acf1268d65ff850304e859375b962486664e5a'

- Support for ScaleIO 1.32 is now deprecated and will be removed
  in a future release.

.. releasenotes/notes/scaleio-deprecate-config-1aa300d0c78ac81c.yaml @ b'b12b865ac5fdae72972b8f3416b56f9e7332f995'

- The ScaleIO Driver has deprecated several options specified
  in ``cinder.conf``:
  * ``sio_protection_domain_id``
  * ``sio_protection_domain_name``,
  * ``sio_storage_pool_id``
  * ``sio_storage_pool_name``.
  Users of the ScaleIO Driver should now utilize the
  ``sio_storage_pools`` options to provide a list of
  protection_domain:storage_pool pairs.

.. releasenotes/notes/scaleio-deprecate-config-1aa300d0c78ac81c.yaml @ b'b12b865ac5fdae72972b8f3416b56f9e7332f995'

- The ScaleIO Driver has deprecated the ability to specify the
  protection domain, as ``sio:pd_name``, and storage pool,
  as ``sio:sp_name``, extra specs in volume types.
  The supported way to specify a specific protection domain and
  storage pool in a volume type is to define a ``pool_name``
  extra spec and set the value to the appropriate
  ``protection_domain_name:storage_pool_name``.

.. releasenotes/notes/smbfs-drop-alloc-data-file-8b94da952a3b1548.yaml @ b'792da5dbbf854a3f23414cf4c53babd44db033cf'

- The 'smbfs_allocation_info_file_path' SMBFS driver config option is now
  deprecated as we're no longer using a JSON file to store volume allocation
  data. This file had a considerable chance of getting corrupted.


.. _Pike Series Release Notes_11.0.0_stable_pike_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/add-filter-to-group-snapshots-74sd8g138a289dh4.yaml @ b'cb5aaf0bcb894a141a9bfb50b9aff4fb209fc850'

- Add filter, sorter and pagination support in group snapshot listings.

.. releasenotes/notes/backend-options-ed19e6c63b2b9090.yaml @ b'1f62a411f4c241f9105a8ffb53fa2e7a1f71902a'

- Cinder stopped supporting single-backend configurations in Ocata. However,
  sample ``cinder.conf`` was still generated with driver-related options in
  ``[DEFAULT]`` section, where those options had no effect at all. Now all of
  driver options are listed in ``[backend_defaults]`` section, that indicates
  that those options are effective only in this section and
  ``[<backend_name>]`` sections listed in ``enabled_backends``.

.. releasenotes/notes/bug-1660927-netapp-no-copyoffload-77fc3cf4f2cf2335.yaml @ b'5043f56cb65defd5f623881584681ae814da1a4e'

- Fixed misleading error message when NetApp copyoffload tool is not in place
  during image cloning.

.. releasenotes/notes/bug-1667071-dc6407f40a1f7d15.yaml @ b'b245225d5e67120dfe7aee5e941f381846c89423'

- Modifying the extra-specs of an in use Volume Type was something that we've unintentionally allowed.  The result is unexpected or unknown volume behaviors in cases where a type was modified while a volume was assigned that type.  This has been particularly annoying for folks that have assigned the volume-type to a different/new backend device.
  In case there are customers using this "bug" we add a config option to retain the bad behavior "allow_inuse_volume_type_modification", with a default setting of False (Don't allow).  Note this config option is being introduced as deprecated and will be removed in a future release.  It's being provided as a bridge to not break upgrades without notice.

.. releasenotes/notes/bug-1670260-fix-boolean-is_public-d16e1957c0f09d65.yaml @ b'd8928c20671a23b26ae9d8e76e95d62a174b8300'

- Fixed issue where ``create`` and ``update`` api's of ``volume-type`` and
  ``group_type`` were returning 500 error if boolean 'is_public' value
  passed in the form of string. Now user can pass following valid boolean
  values to these api's:
  '0', 'f', 'false', 'off', 'n', 'no', '1', 't', 'true', 'on', 'y', 'yes'

.. releasenotes/notes/bug-1671220-4d521be71d0b8aa4.yaml @ b'9ed8c61ec5745f7e07e7eb78888e3e76fcd5b289'

- Fixed consistency groups API which was always returning groups
  scoped to project ID from user context instead of given input
  project ID.

.. releasenotes/notes/bug-1693084-fix-az-cache-invalid-6td4q74q28uxcd68.yaml @ b'9f213981ac349e0fa22a1aed217dbe7aee3813ae'

- Now cinder will refresh the az cache immediately if previous create
  volume task failed due to az not found.

.. releasenotes/notes/bug-1705375-prohibit-group-deletion-if-groupsnapshot-exists.yaml @ b'252ff38a9dbe9751a54a0ca9e88d30020cc58296'

- Prohibit the deletion of group if group snapshot exists.

.. releasenotes/notes/bug-1706888-update-backend-when-extending-3e4a9831a0w29d68.yaml @ b'a8776a726ea6320e2985b6c12f580ea8b17d21d2'

- Update backend state in scheduler when extending volume.

.. releasenotes/notes/check-displayname-displaydescription-123sd5gef91acb12.yaml @ b'52fb5585bc7b4b4a781089d141df333a3202e1fd'

- Add 'display_name' and 'display_description' validation for creating/updating snapshot and volume operations.

.. releasenotes/notes/check-snapshots-when-cascade-deleting-transferred-volume-575ef0b76bd7f334.yaml @ b'74ad916490a9fb34a256ed93fe7250e206afd930'

- After transferring a volume without snapshots from one user project to another user project, if the receiving user uses cascade deleting, it will cause some exceptions in driver and volume will be error_deleting. Adding additional check to ensure there are no snapshots left in other project when cascade deleting a tranferred volume.

.. releasenotes/notes/create_volume_from_encrypted_image-9666e1ed7b4eab5f.yaml @ b'a76fda426979ce79e9055b56ef47bf9f5b1ad912'

- Creating a new volume from an image that was created from an encrypted Cinder volume now succeeds.

.. releasenotes/notes/new-nova-config-section-2a7a51a0572e7064.yaml @ b'9f213981ac349e0fa22a1aed217dbe7aee3813ae'

- Fixed using of the user's token in the nova client
  (`bug #1686616 <https://bugs.launchpad.net/cinder/+bug/1686616>`_)

.. releasenotes/notes/nfs_backup_no_overwrite-be7b545453baf7a3.yaml @ b'535e71797031c3d3e3a5e2023c5ede470b02e3a7'

- Fix NFS backup driver, we now support multiple backups on the same
  container, they are no longer overwritten.

.. releasenotes/notes/pure-default-replica-interval-07de0a56f61c7c1e.yaml @ b'0d02e6f6b15f290ead2f61a5b96411408519c122'

- Fixes an issue where starting the Pure volume drivers with replication enabled and default values for pure_replica_interval_default would cause an error to be raised from the backend.

.. releasenotes/notes/qb-backup-5b1f2161d160648a.yaml @ b'43eb121b4110f0e87a36dba1ddbf89d3ebfbd199'

- A bug in the Quobyte driver was fixed that prevented backing up volumes
  and snapshots

.. releasenotes/notes/redundancy-in-volume-url-4282087232e6e6f1.yaml @ b'00006260d2f0d34cc2f090f4bfda32643c709b62'

- Fixes a bug that prevented the configuration of multiple redundant
  Quobyte registries in the quobyte_volume_url config option.

.. releasenotes/notes/snapshot_backing_up_status_support-164fbbb2a564e137.yaml @ b'9f213981ac349e0fa22a1aed217dbe7aee3813ae'

- When backing up a volume from a snapshot, the volume status would be set to "backing-up", preventing operations on the volume until the backup is complete. This status is now set on the snapshot instead, making the volume available for other operations.

.. releasenotes/notes/support-tenants-project-in-attachment-list-3edd8g138a28s4r8.yaml @ b'9f213981ac349e0fa22a1aed217dbe7aee3813ae'

- Add ``all_tenants``, ``project_id`` support in the attachment list and detail APIs.

.. releasenotes/notes/validate_vol_create_uuids-4f08b4ef201385f6.yaml @ b'2d4a8048762b6453b075c29c58c7ab063a9102cf'

- The create volume api will now return 400 error instead of 404/500 if user
  passes non-uuid values to consistencygroup_id, source_volid and
  source_replica parameters in the request body.

.. releasenotes/notes/verify-dorado-luntype-for-huawei-driver-4fc2f4cca3141bb3.yaml @ b'05427efcceaab2f1bbf5c04adc30f99550c157d7'

- Add 'LUNType' configuration verification for Huawei driver when
  connecting to Dorado array. Because Dorado array only supports
  'Thin' lun type, so 'LUNType' only can be configured as 'Thin',
  any other type is invalid and if 'LUNType' not explicitly configured,
  by default use 'Thin' for Dorado array.

.. releasenotes/notes/win-iscsi-config-portals-51895294228d7883.yaml @ b'b2ddad27522a79e7d18e5a6c74776c82faf12fc6'

- The Windows iSCSI driver now honors the configured iSCSI addresses,
  ensuring that only those addresses will be used for iSCSI traffic.

.. releasenotes/notes/zfssa-iscsi-multi-connect-3be99ee84660a280.yaml @ b'278ad6a2bd8a8401ce40d57a8a243500d11b1c17'

- Oracle ZFSSA iSCSI - allows a volume to be connected to more than one connector at the same time, which is required for live-migration to work. ZFSSA software release 2013.1.3.x (or newer) is required for this to work.


.. _Pike Series Release Notes_11.0.0_stable_pike_Other Notes:

Other Notes
-----------

.. releasenotes/notes/lvm-type-default-to-auto-a2ad554fc8bb25f2.yaml @ b'8c57c6d3ee32c6ad3db7f4936412aa4773ff5ada'

- Modify default lvm_type setting from thick to auto.  This will result in
  Cinder preferring thin on init, if there are no LV's in the VG it will
  create a thin-pool and use thin.  If there are LV's and no thin-pool
  it will continue using thick.


