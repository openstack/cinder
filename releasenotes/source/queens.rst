===========================
Queens Series Release Notes
===========================

.. _Queens Series Release Notes_12.0.10-10_stable_queens:

12.0.10-10
==========

.. _Queens Series Release Notes_12.0.10-10_stable_queens_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1773725-xtremio-remove-provisioning-factor-y7r5uy3489yd9pbf.yaml @ b'121515cf596ead8fbe9a4c3967bf1eacf975e738'

- The XtremIO driver has been fixed to correctly report the "free_capacity_gb" size.

.. releasenotes/notes/bug-fix-1867163-27afa39ac77b9e15.yaml @ b'748fc29254785d22c4623c0e5ec9bd71f0ef6365'

- PowerMax Driver - Issue with upgrades from pre Pike to Pike and later.
  The device is not found when trying to snapshot a legacy volume.


.. _Queens Series Release Notes_12.0.10_stable_queens:

12.0.10
=======

.. _Queens Series Release Notes_12.0.10_stable_queens_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bugfix-1744692-5aebd0c97ae66407.yaml @ b'772897cad777716e55216f59d0e11ec191b31c80'

- Fixes a bug that prevented distributed file system drivers from creating
  snapshots during volume clone operations (NFS, WindowsSMBFS, VZstorage
  and Quobyte drivers). Fixing this allows creating snapshot based backups.

.. releasenotes/notes/detachedinstanceerror-64be35894c624eae.yaml @ b'2abd8a68bb1bde9adc7c870a1b827731ad4e42e9'

- Fix DetachedInstanceError is not bound to a Session for VolumeAttachments.
  This affected VolumeList.get_all, and could make a service fail on startup
  and make it stay in down state.

.. releasenotes/notes/hpe-3par-specify-nsp-for-fc-bootable-volume-f372879e1b625b4d.yaml @ b'9d4e3674dbba71182122557fa1bb04c3afdf9f91'

- `Bug 1809249 <https://bugs.launchpad.net/cinder/+bug/1809249>`_ -
  3PAR driver adds the config option `hpe3par_target_nsp` that can be
  set to the 3PAR backend to use when multipath is not enabled and
  the Fibre Channel Zone Manager is not used.


.. _Queens Series Release Notes_12.0.8_stable_queens:

12.0.8
======

.. _Queens Series Release Notes_12.0.8_stable_queens_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/fix-multiattach-deletion-b3990acf1f5fd378.yaml @ b'3c4b0c130d26177bab09d167e96c3d7b32e9e04b'

- Fixed NetApp SolidFire bug that avoided multiatached volumes to be deleted.

.. releasenotes/notes/kaminario-cinder-driver-bug-44c728f026394a85.yaml @ b'8d7620b478e31510e5f1ec74eb8fb488d45a7873'

- Kaminario FC and iSCSI drivers: Fixed `bug 1829398
  <https://bugs.launchpad.net/cinder/+bug/1829398>`_ where
  force detach would fail.

.. releasenotes/notes/netapp-non-discovery-19af4e10f7b190ea.yaml @ b'7cc7322a0fb5a9c7f965bdf80de4c0cf71fdfe37'

- NetApp iSCSI drivers no longer use the discovery mechanism for multipathing
  and they always return all target/portals when attaching a volume.  Thanks
  to this, volumes will be successfully attached even if the target/portal
  selected as primary is down, this will be the case for both, multipath and
  single path connections.


.. _Queens Series Release Notes_12.0.7_stable_queens:

12.0.7
======

.. _Queens Series Release Notes_12.0.7_stable_queens_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1773446-984d76ed29445c9b.yaml @ b'8d7675783b6453c8b7ed3396b681be74f04708ce'

- Fixed group availability zone-backend host mismatch
  [`Bug 1773446 <https://bugs.launchpad.net/cinder/+bug/1773446>`_].


.. _Queens Series Release Notes_12.0.6_stable_queens:

12.0.6
======

.. _Queens Series Release Notes_12.0.6_stable_queens_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/vnx-update-sg-in-cache-3ecb673727bea79b.yaml @ b'29d42fa73448b3d23d9da4db7b2f407694681ece'

- Dell EMC VNX Driver: Fixes `bug 1817385
  <https://bugs.launchpad.net/cinder/+bug/1817385>`__ to make sure the sg can
  be created again after it was destroyed under `destroy_empty_storage_group`
  setting to `True`.


.. _Queens Series Release Notes_12.0.5_stable_queens:

12.0.5
======

.. _Queens Series Release Notes_12.0.5_stable_queens_Known Issues:

Known Issues
------------

.. releasenotes/notes/lio-multiattach-disabled-a6ee89072fe5d032.yaml @ b'7503af11e6d00be718de054981fb5969fd0e4a5c'

- Multiattach support is disabled for the LVM driver when using the LIO iSCSI
  target.  This functionality will be fixed in a later release.


.. _Queens Series Release Notes_12.0.5_stable_queens_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1805550-default-policy-file-db15eaa76fefa115.yaml @ b'61e90d528d444fd98d6f34c4b0f81e4ac1e1f0d4'

- Beginning with Cinder version 12.0.0, as part of the Queens release
  "policies  in code" community effort, Cinder has had the ability to run
  without a policy file because sensible default values are specified in
  the code.  Customizing the policies in effect at your site, however,
  still requires a policy file.  The default location of this file has been
  ``/etc/cinder/policy.json`` (although the documentation has indicated
  otherwise).  With this release, the default location of this file is
  changed to ``/etc/cinder/policy.yaml``.

  Some points to keep in mind:

  - The policy file to be used may be specified in the
    ``/etc/cinder/cinder.conf`` file in the ``[oslo_policy]``
    section as the value of the ``policy_file`` configuration option.
    That way there's no question what file is being used.

  - To find out what policies are available and what their default
    values are, you can generate a sample policy file.  To do this,
    you must have a local copy of the Cinder source code repository.
    From the top level directory, run the command::

        tox -e genpolicy

    This will generate a file named ``policy.yaml`` in the ``etc/cinder``
    directory of your checked-out Cinder repository.

  - The sample file is YAML (because unlike JSON, YAML allows comments).
    If you prefer, you may use a JSON policy file.

  - Beginning with Cinder 12.0.0, you only need to specify policies in
    your policy file that you want to **differ** from the default values.
    Unspecified policies will use the default values *defined in the code*.
    Given that a default value *must* be specified *in the code* when a
    new policy is introduced, the ``default`` policy, which was formerly
    used as a catch-all for policy targets that were not defined elsewhere
    in the policy file, has no effect.  We mention this because an old
    upgrade strategy was to use the policy file from the previous release
    with ``"default": "role:admin"`` (or ``"default": "!"``) so that newly
    introduced actions would be blocked from end users until the operator
    had time to assess the implications of exposing these actions.  This
    strategy no longer works.  Hopefully this isn't a problem because
    we're defining sensible defaults in the code.  It would be a good
    idea, however, to generate the sample policy file with each release
    (see instructions above) to verify this for yourself.


.. _Queens Series Release Notes_12.0.5_stable_queens_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1790141-vmax-powermaxos-upgrade-fix-4c76186cfca66790.yaml @ b'4818a540c3e8a96ad3478333a072582ba256ee9a'

- PowerMax driver - Workload support was dropped in ucode 5978. If a VMAX All Flash array is upgraded to 5978 or greater and existing volume types leveraged workload e.g. DSS, DSS_REP, OLTP and OLTP_REP, certain operations will no longer work and the volume type will be unusable. This fix addresses these issues and fixes problems with using old volume types with workloads included in the volume type pool_name.

.. releasenotes/notes/bug-1799221-fix-truncated-volumes-in-case-of-glance-errors-6cae19218249c3cf.yaml @ b'937af5be0e7c17b34860e25cc434a219d7143387'

- Fixed a bug which could create volumes with invalid content in case of
  unhandled errors from glance client
  (Bug `#1799221 <https://bugs.launchpad.net/cinder/+bug/1799221>`_).

.. releasenotes/notes/bug-reno-69539ecb9b0b5464.yaml @ b'ed2c7b90376fa6f5cd6ef8f46fe9b2d408b0b756'

- The Solidfire cinder driver has been fixed to ensure delete happens
  on the correct volume.

.. releasenotes/notes/fix-import-backup-quota-issue-8yh69hd19u7tuu23.yaml @ b'acf16280a48dffbf21358b1c3b7484445c0a2b7c'

- Cinder will now consume quota when importing new backup resource.

.. releasenotes/notes/fix-netapp-cg-da4fd6c396e5bedb.yaml @ b'e201d5fcb51fa4fa5292768ad31fcd952a7979e2'

- Fixes a bug in NetApp SolidFire where the deletion of group snapshots was failing.

.. releasenotes/notes/fix-netapp-force_detach-36bdf75dd2c9a030.yaml @ b'a5edf0b62215fa3335f60115303cae9210408385'

- Fixes force_detach behavior for volumes in NetApp SolidFire driver.

.. releasenotes/notes/storwize-hyperswap-host-site-update-621e763768fab9ee.yaml @ b'5d19cab2922ae26c91953d1618c7f06c05a8e96a'

- Updated the parameter storwzie_preferred_host_site from StrOpt to DictOpt
  in cinder back-end configuration, and removed it from volume type
  configuration.


.. _Queens Series Release Notes_12.0.4_stable_queens:

12.0.4
======

.. _Queens Series Release Notes_12.0.4_stable_queens_New Features:

New Features
------------

.. releasenotes/notes/netapp-log-filter-f3256f55c3ac3faa.yaml @ b'a3564892f97b5ee64b0b6a146383d0e10fd76c17'

- The NetApp ONTAP driver supports a new configuration option ``netapp_api_trace_pattern`` to enable filtering backend API interactions to log. This option must be specified in the backend section when desired and it accepts a valid python regular expression.

.. releasenotes/notes/nimble-retype-support-18f717072948ba6d.yaml @ b'ecb06ef6fc8403140639a2c1b0fac49bf2c7480d'

- Support for retype and volume migration for HPE Nimble Storage driver.


.. _Queens Series Release Notes_12.0.4_stable_queens_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/nec-delete-volume-per-limit-d10b9df86f64b80e.yaml @ b'06b9876207ca81b50a877774b5968decaf1833ca'

- In NEC driver, the number of volumes in a storage pool is no longer limited to 1024. More volumes can be created with storage firmware revision 1015 or later.


.. _Queens Series Release Notes_12.0.4_stable_queens_Security Issues:

Security Issues
---------------

.. releasenotes/notes/scaleio-zeropadding-a0273c56c4d14fca.yaml @ b'f0cef07bef5ea8ed29179ee3774df5f4a634ba86'

- Removed the ability to create volumes in a ScaleIO Storage Pool that has
  zero-padding disabled. A new configuration option
  ``sio_allow_non_padded_volumes`` has been added to override this new
  behavior and allow unpadded volumes, but should not be enabled if multiple
  tenants will utilize volumes from a shared Storage Pool.


.. _Queens Series Release Notes_12.0.4_stable_queens_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bugfix-netapp-driver-cinder-ipv6-c3c4d0d6a7d0de91.yaml @ b'40eaa89a9001edda3e1146831b26aaf7ded64c4a'

- Fixed support for IPv6 on management and data paths for NFS, iSCSI and FCP NetApp ONTAP drivers.

.. releasenotes/notes/fix-quota-deleting-temporary-volume-274e371b425e92cc.yaml @ b'23729bdda4099908a205f6d60f64ffad712f820e'

- Fix a quota usage error triggered by a non-admin user backing up an
  in-use volume. The forced backup uses a temporary volume, and quota
  usage was incorrectly updated when the temporary volume was deleted
  after the backup operation completed.
  Fixes `bug 1778774 <https://bugs.launchpad.net/tripleo/+bug/1778774>`__.

.. releasenotes/notes/force-delete-mv-a53924f09c475386.yaml @ b'869fab393b13d056a702c899d073c48b6bea6f50'

- Volume "force delete" was introduced with the 3.23 API microversion,
  however the check for in the service was incorrectly looking for
  microversion 3.2. That check has now been fixed. It is possible that an API
  call using a microversion below 3.23 would previously work for this call,
  which will now fail. This closes
  `bug #1783028 <https://bugs.launchpad.net/cinder/+bug/1783028>`_.

.. releasenotes/notes/netapp-ontap-fix-force-detach-55be3f4ac962b493.yaml @ b'98ee144c3af5d824c2a828a8b727b9dd95efa659'

- Fixed bug #1783582, where calls to os-force_detach were failing on NetApp
  ONTAP iSCSI/FC drivers.

.. releasenotes/notes/ssl-cert-fix-42e8f263c15d5343.yaml @ b'cf22fa2875f1787889e6eeea693b7c81528e2918'

- VMAX driver - fixes SSL certificate verification error.

.. releasenotes/notes/unity-return-logged-out-initiator-6ab1f96f21bb284c.yaml @ b'e8c223f1f9041a2204138ea587a25728c4dba6fd'

- Dell EMC Unity Driver: Fixes `bug 1773305
  <https://bugs.launchpad.net/cinder/+bug/1773305>`__
  to return the targets which connect to the logged-out initiators. Then the
  zone manager could clean up the FC zone based on the correct target wwns.


.. _Queens Series Release Notes_12.0.3_stable_queens:

12.0.3
======

.. _Queens Series Release Notes_12.0.3_stable_queens_New Features:

New Features
------------

.. releasenotes/notes/unity-remove-empty-host-17d567dbb6738e4e.yaml @ b'24bd0c4b645dbcb99977e6a3e16c51979455b1eb'

- Dell EMC Unity Driver: Adds support for removing empty host. The new option
  named `remove_empty_host` could be configured as `True` to notify Unity
  driver to remove the host after the last LUN is detached from it.


.. _Queens Series Release Notes_12.0.3_stable_queens_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1712651-7bc90264eb5001ea.yaml @ b'41735db868fc1de2dac313ea60742e7e1cc76289'

- NetApp ONTAP iSCSI (bug 1712651): Fix ONTAP NetApp iSCSI driver not
  raising a proper exception when trying to extend an attached volume
  beyond its max geometry.

.. releasenotes/notes/bug-1762424-f76af2f37fe408f1.yaml @ b'e0a1269d8728d8e1fa15d9c89ed7a2f90cab6b77'

- NetApp ONTAP (bug 1762424): Fix ONTAP NetApp driver not being able to extend
  a volume to a size greater than the corresponding LUN max geometry.

.. releasenotes/notes/bug-1775518-fix-unity-empty-list-issue-2d6b7c33aae1ffcc.yaml @ b'c7f9d29e17523653b7d2f0eb2b109798235b6ebb'

- Dell EMC Unity: Fixes bug 1775518 to make sure driver succeed
  to initialize even though the value of unity_io_ports and
  unity_storage_pool_names are empty


.. _Queens Series Release Notes_12.0.2_stable_queens:

12.0.2
======

.. _Queens Series Release Notes_12.0.2_stable_queens_New Features:

New Features
------------

.. releasenotes/notes/feature-rbd-exclusive-pool-a9bdebdeb1f0bf37.yaml @ b'21821c16580377c4e6443d0b440f41cb7de0ca8d'

- When using the RBD pool exclusively for Cinder we can now set
  `rbd_exclusive_cinder_pool` to `true` and Cinder will use DB information
  to calculate provisioned size instead of querying all volumes in the
  backend, which will reduce the load on the Ceph cluster and the volume
  service.

.. releasenotes/notes/sync-bump-versions-a1e6f6359173892e.yaml @ b'25c737d6b8e19a1932696554e47dd262ae651592'

- Cinder-manage DB sync command can now bump the RPC and Objects versions of the services to avoid a second restart when doing offline upgrades.

.. releasenotes/notes/unity-enable-ssl-14db2497225c4395.yaml @ b'685de5a7b683552899fc0fd6c095d35b6a9bf555'

- Dell EMC Unity Cinder driver allows enabling/disabling the SSL verification. Admin can set `True` or `False` for `driver_ssl_cert_verify` to enable or disable this function, alternatively set the `driver_ssl_cert_path=<PATH>` for customized CA path. Both above 2 options should go under the driver section.


.. _Queens Series Release Notes_12.0.2_stable_queens_Known Issues:

Known Issues
------------

.. releasenotes/notes/feature-rbd-exclusive-pool-a9bdebdeb1f0bf37.yaml @ b'21821c16580377c4e6443d0b440f41cb7de0ca8d'

- If RBD stats collection is taking too long in your environment maybe even
  leading to the service appearing as down you'll want to use the
  `rbd_exclusive_cinder_pool = true` configuration option if you are using
  the pool exclusively for Cinder and maybe even if you are not and can live
  with the innacuracy.


.. _Queens Series Release Notes_12.0.2_stable_queens_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/sync-bump-versions-a1e6f6359173892e.yaml @ b'25c737d6b8e19a1932696554e47dd262ae651592'

- On offline upgrades, due to the rolling upgrade mechanism we need to restart the cinder services twice to complete the installation just like in the rolling upgrades case.  First you stop the cinder services, then you upgrade them, you sync your DB, then you start all the cinder services, and then you restart them all.  To avoid this last restart we can now instruct the DB sync to bump the services after the migration is completed, the command to do this is `cinder-manage db sync --bump-versions`


.. _Queens Series Release Notes_12.0.2_stable_queens_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1690954-40fc21683977e996.yaml @ b'64df0693991bd3815acc8e445da912a499198f7e'

- NetApp ONTAP NFS (bug 1690954): Fix wrong usage of export path
  as volume name when deleting volumes and snapshots.

.. releasenotes/notes/fail-detach-lun-when-auto-zone-enabled-9c87b18a3acac9d1.yaml @ b'febe57cfee50425c0fc9945169b5f9c3898cbdfe'

- Dell EMC Unity Driver: Fixes `bug 1759175
  <https://bugs.launchpad.net/cinder/+bug/1759175>`__
  to detach the lun correctly when auto zone was enabled and the lun was the
  last one attached to the host.

.. releasenotes/notes/netapp-ontap-use_exact_size-d03c90efbb8a30ac.yaml @ b'c664f08fe2bd44b209a1f75a58d6dca86200b2fc'

- Fixed bug #1731474 on NetApp Data ONTAP driver that was causing LUNs to be created
  with larger size than requested. This fix requires version 9.1 of ONTAP
  or later.

.. releasenotes/notes/sync-bump-versions-a1e6f6359173892e.yaml @ b'25c737d6b8e19a1932696554e47dd262ae651592'

- After an offline upgrade we had to restart all Cinder services twice, now with the `cinder-manage db sync --bump-versions` command we can avoid the second restart.


.. _Queens Series Release Notes_12.0.2_stable_queens_Other Notes:

Other Notes
-----------

.. releasenotes/notes/vnx-perf-optimize-bd55dc3ef7584228.yaml @ b'e78fe7d62ce51f0216a8059bf01f18f5cf905d37'

- Dell EMC VNX driver: Enhances the performance of create/delete volume.


.. _Queens Series Release Notes_12.0.1_stable_queens:

12.0.1
======

.. _Queens Series Release Notes_12.0.1_stable_queens_New Features:

New Features
------------

.. releasenotes/notes/bug-1686745-e8f1569455f998ba.yaml @ b'9a3fab147ef1182b5149fc1ccbefa0e6cebf1492'

- Add support to force detach a volume from all hosts on 3PAR.

.. releasenotes/notes/tpool-size-11121f78df24db39.yaml @ b'5dc330a2cb8ed1f28115c28f094900349a33ae20'

- Adds support to configure the size of the native thread pool used by the cinder volume and backup services.  For the backup we use `backup_native_threads_pool_size` in the `[DEFAULT]` section, and for the backends we use `backend_native_threads_pool_size` in the driver section.


.. _Queens Series Release Notes_12.0.1_stable_queens_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/dell-emc-sc-bugfix-1756914-ffca3133273040f6.yaml @ b'96b77e0aa62790320d16f7229aaeeb650fa875b6'

- Dell EMC SC driver correctly returns initialize_connection data when more than one IQN is attached to a volume. This fixes some random Nova Live Migration failures where the connection information being returned was for an IQN other than the one for which it was being requested.

.. releasenotes/notes/fix-abort-backup-df196e9dcb992586.yaml @ b'd65444ce7df88292581d0726f9eb633be2292287'

- We no longer leave orphaned chunks on the backup backend or leave a
  temporary volume/snapshot when aborting a backup.

.. releasenotes/notes/fix-cross-az-migration-ce97eff61280e1c7.yaml @ b'c2df706c023d752825c250c4ceb2f98f5ce5a476'

- Resolve issue with cross AZ migrations and retypes where the destination
  volume kept the source volume's AZ, so we ended up with a volume where the
  AZ does not match the backend. (bug 1747949)

.. releasenotes/notes/migrate-backup-encryption-keys-to-barbican-6f07fd48d4937b2a.yaml @ b'bc76abef28b34723abdbd29881553a1af94b024b'

- When encryption keys based on the ConfKeyManager's fixed_key are migrated
  to Barbican, ConfKeyManager keys stored in the Backup table are included
  in the migration process.
  Fixes `bug 1757235 <https://bugs.launchpad.net/tripleo/+bug/1757235>`__.

.. releasenotes/notes/tpool-size-11121f78df24db39.yaml @ b'5dc330a2cb8ed1f28115c28f094900349a33ae20'

- Fixes concurrency issue on backups, where only 20 native threads could be concurrently be executed.  Now default will be 60, and can be changed with `backup_native_threads_pool_size`.

.. releasenotes/notes/tpool-size-11121f78df24db39.yaml @ b'5dc330a2cb8ed1f28115c28f094900349a33ae20'

- RBD driver can have bottlenecks if too many slow operations are happening at the same time (for example many huge volume deletions), we can now use the `backend_native_threads_pool_size` option in the RBD driver section to resolve the issue.


.. _Queens Series Release Notes_12.0.0_stable_queens:

12.0.0
======

.. _Queens Series Release Notes_12.0.0_stable_queens_New Features:

New Features
------------

.. releasenotes/notes/3par-get-capability-de60c9bc7ae51c14.yaml @ b'9e46d6e1a62a60ff95c503d14b1f0f5ecb8b9ccf'

- Added get capability feature for HPE-3PAR.

.. releasenotes/notes/add-availability_zone-filter-for-snapshot-8e1494212276abde.yaml @ b'0f5a7f3ac31f73c12f627f54e6c41449cce99b98'

- Added availability_zone filter for snapshots list.

.. releasenotes/notes/add-count-info-in-list-api-e43wac44yu750c23.yaml @ b'23b74639848df37ee25f0d613062862749c7e42d'

- Added count info in volume, snapshot and backup's list APIs since 3.45.

.. releasenotes/notes/add-datacore-volume-driver-3775797b0515f538.yaml @ b'5f0ea63b60dbec6175145f975789253d2a956384'

- Added iSCSI and Fibre Channel volume drivers for DataCore's SANsymphony and Hyper-converged Virtual SAN storage.

.. releasenotes/notes/add_multiattach_policies-8e0b22505ed6cbd8.yaml @ b'76f2158d47df2b112293f3463feb1caf5a0db04b'

- Added policies to disallow multiattach operations.  This includes two policies, the first being a general policy to allow the creation or retyping of multiattach volumes is a volume create policy with the name ``volume:multiattach``.
  The second policy is specifically for disallowing the ability to create multiple attachments on a volume that is marked as bootable, and is an attachment policy with the name ``volume:multiattach_bootable_volume``.
  The default for these new policies is ``rule:admin_or_owner``; be aware that if you wish to disable either of these policies for your users you will need to modify the default policy settings.

.. releasenotes/notes/add_replication_failback_to_solidfire-82668c071f4fa91d.yaml @ b'e7498ca5bdd6e16b46e8a6d17dbc7492f6e710e9'

- Add ability to call failover-host on a replication
  enabled SF cluster a second time with host id = default
  to initiate a failback to the default configured SolidFire
  Cluster.

.. releasenotes/notes/allow-encrypted-rbd-volumes-35d3536505e6309b.yaml @ b'fcb45b439ba039fd88c332fd912949d52cfe290f'

- LUKS Encrypted RBD volumes can now be created by cinder-volume. This
  capability was previously blocked by the rbd volume driver due to the lack
  of any encryptors capable of attaching to an encrypted RBD volume. These
  volumes can also be seeded with RAW image data from Glance through the use
  of QEMU 2.10 and the qemu-img convert command.

.. releasenotes/notes/backup-driver-configuration-36357733962dab03.yaml @ b'de2ffaff36e3713e3862b15816f59c4d3dd8abca'

- Add ability to specify backup driver via class name.

.. releasenotes/notes/bp-inspur-instorage-driver-40371862c9559238.yaml @ b'e7362103c67579bf7caf1437afc3d4518923c8a6'

- New Cinder volume driver for Inspur InStorage.
  The new driver supports iSCSI.

.. releasenotes/notes/bp-provisioning-improvements-bb7e28896e2a2539.yaml @ b'f98c9da944b46875cdec91cf4c0c28ce89e1ac6a'

- Cinder now supports the use of 'max_over_subscription_ratio = auto' which automatically calculates the value for max_over_subscription_ratio in the scheduler.

.. releasenotes/notes/bp-vmware-fcd-fbe19ee577d2e9e4.yaml @ b'377549c67c4290532df602e89e6f9e6193ab188d'

- Added backend driver for VMware VStorageObject (First Class Disk).

.. releasenotes/notes/bug-1730933-1bb0272e3c51eed3.yaml @ b'ac0583c94acb8f960e9b6e242ce3e6eb604962c0'

- The Quobyte Cinder driver now supports identifying Quobyte mounts
  via the mounts fstype field.

.. releasenotes/notes/ds8k_async_clone_volume-25232c55da921202.yaml @ b'1d9d7c00b40a529af2dc6cd4672dca14be53a9b6'

- Added support for cloning volume asynchronously, it can be enabled by
  option async_clone set to true in parameter metadata when creating
  volume from volume or snapshot.

.. releasenotes/notes/hpe3par-replication-group-a18a28d18de09e95.yaml @ b'3da071994b76346a823e3bd1b5aa9582e7163cd0'

- Added replication group support in HPE 3PAR cinder driver.

.. releasenotes/notes/infinidat-max-osr-2d9fd2d0f9424657.yaml @ b'88080cb45c1aaadae3aa284384ce595ff4a9a067'

- Added support for oversubscription in thin provisioning in the INFINIDAT InfiniBox driver. To use oversubscription, define ``max_over_subscription_ratio`` in the cinder configuration file.

.. releasenotes/notes/k2-disable-discovery-bca0d65b5672ec7b.yaml @ b'c9ec9b9bd755f042dbe1ccbdc5e3ff87fa60269c'

- Kaminario K2 iSCSI driver now supports non discovery multipathing (Nova and
  Cinder won't use iSCSI sendtargets) which can be enabled by setting
  `disable_discovery` to `true` in the configuration.

.. releasenotes/notes/migrate-fixed-key-to-barbican-91dfcb829efd4bb6.yaml @ b'189a1096da2b0ad6b51fd5943a385a89f56a18c4'

- When Barbican is the encryption key_manager backend, any encryption keys
  associated with the legacy ConfKeyManager will be automatically migrated
  to Barbican. All database references to the ConfKeyManager's all-zeros key
  ID will be updated with a Barbican key ID. The encryption keys do not
  change. Only the encryption key ID changes.

  Key migration is initiated on service startup, and entries in the
  cinder-volume log will indicate the migration status. Log entries will
  indicate when a volume's encryption key ID has been migrated to Barbican,
  and a summary log message will indicate when key migration has finished.

.. releasenotes/notes/nec-manage-unmanage-06f9beb3004fc227.yaml @ b'db7d054d33da4ca4abaf16dedaf95d1c020fe981'

- Support manage/unmanage volume and manage/unmanage snapshot functions for the NEC volume driver.

.. releasenotes/notes/policy-in-code-226f71562ab28195.yaml @ b'9fe72de4b690bc5c964c12715581128830c667d5'

- Cinder now support policy in code, which means if users don't need to
  modify any of the default policy rules, they do not need a policy file.
  Users can modify/generate a `policy.yaml` file which will override specific
  policy rules from their defaults.

.. releasenotes/notes/ps-report-total-volumes-8aa447c50f2474a7.yaml @ b'a8a4518580d321604fbd54a04996aba9ee02cb25'

- Dell EMC PS volume driver reports the total number of volumes on the backend in volume stats.

.. releasenotes/notes/qnap-enhance-support-4ab5cbb110b3303b.yaml @ b'08dcf03541995cc9f8a22232bf738967e4b6570b'

- Add enhanced support to the QNAP Cinder driver, including
  'CHAP', 'Thin Provision', 'SSD Cache', 'Dedup' and 'Compression'.

.. releasenotes/notes/qnap-support-qes-200-2a3dda49afe14103.yaml @ b'5c32be5a6de64f3a853924c2e82fb1d99acde712'

- QNAP Cinder driver added support for QES fw 2.0.0.

.. releasenotes/notes/rbd-driver-assisted-migration-2d29788243060f77.yaml @ b'dd119d5620bebc59a72f4fb1e1b795f56da5db64'

- Added driver-assisted volume migration to RBD driver. This allows a volume to be efficiently copied by Ceph from one pool to another within the same cluster.

.. releasenotes/notes/rbd-stats-report-0c7e803bb0b1aedb.yaml @ b'8469109016bcfd5806e230202e1996a8ba649535'

- RBD driver supports returning a static total capacity value instead of a
  dynamic value like it's been doing.  Configurable with
  `report_dynamic_total_capacity` configuration option.

.. releasenotes/notes/rbd-support-list-manageable-volumes-8a088a44e01d227f.yaml @ b'164246094e90af6f63f63c321514b07a655941a9'

- Allow rbd driver to list manageable volumes.

.. releasenotes/notes/readd-qnap-driver-e1dc6b0c3fabe30e.yaml @ b'14dea86f5dbdfded0b23afa6ac454f9914ac0a77'

- Re-added QNAP Cinder volume driver.

.. releasenotes/notes/report-backend-state-in-service-list-1e4ee5a2c623671e.yaml @ b'0dc8390e11cfe0946ea61350a82e3e8e0c1c6e4d'

- Added "backend_state: up/down" in response body of service list if
  context is admin. This feature will help operators or cloud management
  system to get the backend device state in every service.
  If device state is *down*, specify that storage device has got some
  problems. Give more information to locate bugs quickly.

.. releasenotes/notes/revert-volume-to-snapshot-6aa0dffb010265e5.yaml @ b'd317c54edb2bfcfef523e5ccbc0119c78539824e'

- Added revert volume to snapshot in 3par driver.

.. releasenotes/notes/scaleio-backup-via-snapshot-8e75aa3f4570e17c.yaml @ b'7b5bbc951aa41174c58c53ec361b4337125ae66a'

- Add support to backup volume using snapshot in the Unity driver, which enables backing up of volumes that are in-use.

.. releasenotes/notes/scaleio-enable-multiattach-e7d84ffa282842e9.yaml @ b'5f0ea63b60dbec6175145f975789253d2a956384'

- The multiattach capability has been enabled and verified
  as working with the ScaleIO driver. It is the user's
  responsibility to add some type of exclusion (at the file
  system or network file system layer) to prevent multiple
  writers from corrupting data on the volume.

.. releasenotes/notes/smbfs-fixed-image-9b642b63fcb79c18.yaml @ b'54c2787132396a73a45682133f66777ba1eb2085'

- The SMBFS volume driver can now be configured to use fixed vhd/x images
  through the 'nas_volume_prov_type' config option.

.. releasenotes/notes/smbfs-manage-unmanage-f1502781dd5f82cb.yaml @ b'ed945da6bf05475c272443d2eebacfc79c389926'

- The SMBFS driver now supports the volume manage/unmanage feature. Images
  residing on preconfigured shares may be listed and managed by Cinder.

.. releasenotes/notes/smbfs-revert-snapshot-5b265ed5ded951dc.yaml @ b'e8715f690e61557d08c6df9040a2e4d87d3e6bad'

- The SMBFS volume driver now supports reverting volumes to the latest
  snapshot.

.. releasenotes/notes/storpool-volume-driver-4d5f16ad9c2f373a.yaml @ b'b5832afb3a7e04b4709be6ab863d0281c75616b3'

- The StorPool backend driver was added.

.. releasenotes/notes/storwize-backup-snapshot-support-728e18dfa0d42943.yaml @ b'f68847353e46c8729d8fc13d2e53608c72c159c7'

- Add backup snapshots support for Storwize/SVC driver.

.. releasenotes/notes/storwize-cg-replication-b038ff0d39fe909f.yaml @ b'24e4c3ea684c7d418c2de5ac8c46d175819a4b42'

- Add consistent replication group support in Storwize Cinder driver.

.. releasenotes/notes/storwize-disable-create-volume-with-non-cgsnap-group-6cba8073e3d6cadd.yaml @ b'b03a23618122ee8abf596a471da326bfcb9e1710'

- Disable creating volume with non cg_snapshot group_id in Storwize/SVC driver.

.. releasenotes/notes/storwize-hyperswap-support-b830182e1058cb4f.yaml @ b'c0d471a42461ccc50dbb4b27cfcdd1f4282f3880'

- Added hyperswap volume and group support in Storwize cinder driver. Storwize/svc versions prior to 7.6 do not support this feature.

.. releasenotes/notes/storwize-revert-snapshot-681c76d68676558a.yaml @ b'f701d091bea170e595ed47469a60c4e148a2edcd'

- Add reverting to snapshot support in Storwize Cinder driver.

.. releasenotes/notes/support-create-volume-from-backup-d363e2b502a76dc2.yaml @ b'39694623e421e1f0149bff2ea62345d93eed425e'

- Starting with API microversion 3.47, Cinder now supports the ability to
  create a volume directly from a backup. For instance, you can use the
  command: ``cinder create <size> --backup-id <backup_id>`` in cinderclient.

.. releasenotes/notes/unity-force-detach-7c89e72105f9de61.yaml @ b'b44721dfacc2b4b7f4b3bf07f813800c597a576a'

- Add support to force detach a volume from all hosts on Unity.

.. releasenotes/notes/validate-expired-user-tokens-40b15322197653ae.yaml @ b'826b72ea09a5a5703d732c2abd18b8e8a92b982b'

- Added support for Keystone middleware feature to pass service token along with
  the user token for Cinder to Nova and Glance services. This will help get rid
  of user token expiration issues during long running tasks e.g. creating volume
  snapshot (Cinder->Nova) and creating volume from image (Cinder->Glance) etc.
  To use this functionality a service user needs to be created first. Add the
  service user configurations in ``cinder.conf`` under ``service_user`` group
  and set ``send_service_user_token`` flag to ``True``.

.. releasenotes/notes/vmax-iscsi-chap-authentication-e47fcfe310b85f7b.yaml @ b'77055e7cc688492a22ac7ba40f38bd78259c9b32'

- Add chap authentication support for the vmax backend.

.. releasenotes/notes/vmax-manage-unmanage-snapshot-3805c4ac64b8133a.yaml @ b'7dda6ef758bb08712855d32293bd973c65f90c22'

- Support for manage/ unmanage snapshots on VMAX cinder driver.

.. releasenotes/notes/vmax-replication-enhancements-c3bec80a3abb6d2e.yaml @ b'84e39916c71ca56ebe5ae14c34dc16dbb359ed05'

- Added asynchronous remote replication support in Dell EMC VMAX cinder driver.

.. releasenotes/notes/vmax-replication-enhancements2-0ba03224cfca9959.yaml @ b'925bdfbb06e31d5ad2240c803102e8a5ff309c5a'

- Support for VMAX SRDF/Metro on VMAX cinder driver.

.. releasenotes/notes/vmax-replication-group-2f65ed92d761f90d.yaml @ b'c6b0c4bca66153634a0685f370283b16fe8e0345'

- Add consistent replication group support in Dell EMC VMAX cinder driver.

.. releasenotes/notes/vmax-revert-volume-to-snapshot-b4a837d84a8b2a85.yaml @ b'cf40a001dac4d2f63165b6e4bbd14acb1d09ed54'

- Support for reverting a volume to a previous snapshot in VMAX cinder driver.

.. releasenotes/notes/vmware-vmdk-revert-to-snapshot-ee3d638565649f44.yaml @ b'01971c9cb6cb555d0c440ffbb7332f18ed553930'

- Added support for revert-to-snapshot in the VMware VMDK driver.

.. releasenotes/notes/vmware-vmdk-snapshot-template-d3dcfc0906c02edd.yaml @ b'f36fc239804fb8fbf57d9df0320e2cb6d315ea10'

- VMware VMDK driver now supports vSphere template as a
  volume snapshot format in vCenter server. The snapshot
  format in vCenter server can be specified using driver
  config option ``vmware_snapshot_format``.

.. releasenotes/notes/vmware_lazy_create-52f52f71105d2067.yaml @ b'18c8af402b057768f56cbcb68b1d00b0447eba4e'

- VMware VMDK driver now supports a config option
  ``vmware_lazy_create`` to disable the default behavior of
  lazy creation of raw volumes in the backend.

.. releasenotes/notes/vmware_retype_adapter_type-dbd8935b8d3bcb1b.yaml @ b'52d2ef021fab8513c68bbf40a9e3990c09920f33'

- VMware VMDK driver now supports changing adpater type using retype.
  To change the adapter type, set ``vmware:adapter_type`` in the
  new volume type.

.. releasenotes/notes/vmware_vmdk_managed_by-3de05504d0f9a65a.yaml @ b'14ff0cc2bd5d6cb91766f7ff6cf83f18d23ac8cd'

- The volumes created by VMware VMDK driver will be displayed as
  "managed by OpenStack Cinder" in vCenter server.

.. releasenotes/notes/vnx-add-force-detach-support-26f215e6f70cc03b.yaml @ b'e91e7d5e2f599bc43ecdfbd0d7d5ede2ee813fac'

- Add support to force detach a volume from all hosts on VNX.

.. releasenotes/notes/vzstorage-log-path-7539342e562a2e4a.yaml @ b'f9ebdbf09d331a683a26b5e626fac0888e7317b9'

- Logging path can now be configured for vzstorage driver in
  shares config file (specified by vzstorage_shares_config option).
  To set custom logging path add `'-l', '<path_to_log_file>'` to
  mount options array. Otherwise default logging path
  `/var/log/vstorage/<cluster_name>/cinder.log.gz` will be used.

.. releasenotes/notes/vzstorage-volume-format-cde85d3ad02f6bb4.yaml @ b'1f69f7507e2c8e0b65516710e974ba6932b5f5a2'

- VzStorage volume driver now supports choosing desired volume format by setting
  vendor property 'vz:volume_format' in volume type metadata.
  Allowed values are 'ploop', 'qcow2' and 'raw'.

.. releasenotes/notes/xtremio-ig-cleanup-bbb4bee1f1e3611c.yaml @ b'645bda4f48482f27e7d71776af02561004069315'

- Added new option to delete XtremIO initiator groups after the last volume
  was detached from them. Cleanup can be enabled by setting
  ``xtremio_clean_unused_ig`` to ``True`` under the backend settings in
  cinder.conf.


.. _Queens Series Release Notes_12.0.0_stable_queens_Known Issues:

Known Issues
------------

.. releasenotes/notes/k2-non-unique-fqdns-b62a269a26fd53d5.yaml @ b'baa8626eac9c975b719c03274d42b54ce3de74fe'

- Kaminario K2 now supports networks with duplicated FQDNs via configuration
  option `unique_fqdn_network` so attaching in these networks will work
  (bug #1720147).


.. _Queens Series Release Notes_12.0.0_stable_queens_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/add_multiattach_policies-8e0b22505ed6cbd8.yaml @ b'76f2158d47df2b112293f3463feb1caf5a0db04b'

- Added policies to disallow multiattach operations.  This includes two policies, the first being a general policy to allow the creation or retyping of multiattach volumes is a volume create policy with the name ``volume:multiattach``.
  The second policy is specifically for disallowing the ability to create multiple attachments on a volume that is marked as bootable, and is an attachment policy with the name ``volume:multiattach_bootable_volume``.
  The default for these new policies is ``rule:admin_or_owner``; be aware that if you wish to disable either of these policies for your users you will need to modify the default policy settings.

.. releasenotes/notes/backup-driver-configuration-36357733962dab03.yaml @ b'de2ffaff36e3713e3862b15816f59c4d3dd8abca'

- Operators should change backup driver configuration value to use class
  name to get backup service working in a 'S' release.

.. releasenotes/notes/bp-remove-netapp-7mode-drivers-c38398e54662f2d4.yaml @ b'425f45a311dc78ff34a18ffea7dbf5bb6dd2d421'

- Support for NetApp ONTAP 7 (previously known as "Data ONTAP operating in 7mode") has been removed. The NetApp Unified driver can now only be used with NetApp Clustered Data ONTAP and NetApp E-Series storage systems. This removal affects all three storage protocols that were supported on for ONTAP 7 - iSCSI, NFS and FC. Deployers are advised to consult the `migration support <https://mysupport.netapp.com/info/web/ECMP1658253 .html>`_ provided to transition from ONTAP 7 to Clustered Data ONTAP operating system.

.. releasenotes/notes/bug-1714209-netapp-ontap-drivers-oversubscription-issue-c4655b9c4858d7c6.yaml @ b'42b8b7fe60ffdd7a7772dc0ab228265dc83344bc'

- If using the NetApp ONTAP drivers (7mode/cmode), the configuration value for "max_over_subscription_ratio" may need to be increased to avoid scheduling problems where storage pools that previously were valid to schedule new volumes suddenly appear to be out of space to the Cinder scheduler. See documentation `here <https://docs.openstack .org/cinder/latest/admin/blockstorage-over-subscription.html>`_.

.. releasenotes/notes/castellan-backend-0c49591a54821c45.yaml @ b'e75be5d90519094fca3ee475b906e7c2fe1d09fd'

- The support for ``cinder.keymgr.barbican.BarbicanKeyManager`` and the
  ``[keymgr]`` config section has now been removed. All configs should now be
  switched to use
  ``castellan.key_manager.barbican_key_manager.BarbicanKeyManager`` and the
  ``[key_manager]`` config section.

.. releasenotes/notes/db-schema-from-newton-79b18439bd15e4c4.yaml @ b'a9afbddd11fd5cd82f88e51170633b58cbcb8ecc'

- The Cinder database can now only be ugpraded from changes since the Newton
  release. In order to upgrade from a version prior to that, you must now
  upgrade to at least Newton first, then to Queens or later.

.. releasenotes/notes/deprecate_hosts_api_extension-fe0c042af10a20db.yaml @ b'74746b3407684df6a6e687ce502ffdc7c57f44ab'

- The hosts api extension is now deprecated and will be removed in a
  future version.

.. releasenotes/notes/glance-v1-removed-5121af3bef285324.yaml @ b'd76fef6bf454d1aa3a3c111567126d3a837ea9e3'

- The Glance v1 API has been deprecated and will soon be removed. Cinder
  support for using the v1 API was deprecated in the Pike release and
  is now no longer available. The ``glance_api_version`` configuration
  option to support version selection has now been removed.

.. releasenotes/notes/lvm-thin-overprovision-1d279f66ee2252ff.yaml @ b'9d4922771383bdd24261cde95ce322d7e04d67f3'

- The default value has been removed for the LVM specific
  `lvm_max_over_subscription_ratio` setting. This changes the behavior so
  that LVM backends now adhere to the common `max_over_subscription_ratio`
  setting. The LVM specific config option may still be used, but it is
  now deprecated and will be removed in a future release.

.. releasenotes/notes/mark-cisco-zm-unsupported-57e5612f57e2407b.yaml @ b'c92c428233df7b42bea05bf5468771c07fa8e51b'

- The Cisco Fibre Channel Zone Manager driver has been marked
  as unsupported and is now deprecated. ``enable_unsupported_driver``
  will need to be set to ``True`` in the driver's section in cinder.conf
  to continue to use it.

.. releasenotes/notes/nec-auto-accesscontrol-55f4b090e8128f5e.yaml @ b'd4dd162bcddba85dee5920e147e0b9ce189be276'

- Added automatic configuration of SAN access control for the NEC volume driver.

.. releasenotes/notes/nec-delete-unused-parameter-367bc9447acbb03e.yaml @ b'9974c39f0355bd0a0c3c3364297688de2eccf467'

- In NEC driver, the deprecated configuration parameter `ldset_controller_node_name` was deleted.

.. releasenotes/notes/pure-default-replica-interval-07de0a56f61c7c1e.yaml @ b'f82d2bf6f13a360f6a1c08066cf682e2e07043db'

- The default value for pure_replica_interval_default used by Pure Storage volume drivers has changed from 900 to 3600 seconds.

.. releasenotes/notes/queens-driver-removal-72a1a36689b6d890.yaml @ b'9d3be35cd6ad3b40983f43ce0cc4c2cf9bdcd807'

- The following volume drivers were deprecated in the Pike release and have
  now been removed:

    * Block device driver
    * Blockbridge
    * Coho
    * FalconStor FSS
    * Infortrend
    * QNAP
    * Reduxio
    * Tegile
    * Violin
    * X-IO
    * ZTE

.. releasenotes/notes/rbd-stats-report-0c7e803bb0b1aedb.yaml @ b'8469109016bcfd5806e230202e1996a8ba649535'

- RBD/Ceph backends should adjust `max_over_subscription_ratio` to take into
  account that the driver is no longer reporting volume's physical usage but
  it's provisioned size.

.. releasenotes/notes/remove-block-device-driver-14f76dca2ee9bd38.yaml @ b'711e88a8f9f8322f02a434bbe00417580715cacd'

- BlockDeviceDriver was deprecated in Ocata release and marked as
  'unsupported'. There is no CI for it too. If you used this driver before
  you have to migrate your volumes to LVM with LIO target yourself before
  upgrading to Queens release to get your volumes working.

.. releasenotes/notes/remove-deprecated-keymgr-d11a25c620862ed6.yaml @ b'ef2202b6adc5d817b26559a9e20b536a547bca65'

- The old deprecated ``keymgr`` options have been removed.
  Configuration options using the ``[keymgr]`` group will not be
  applied anymore. Use the ``[key_manager]`` group from Castellan instead.
  The Castellan ``backend`` options should also be used instead of
  ``api_class``, as most
  of the options that lived in Cinder have migrated to Castellan.

  - Instead of ``api_class`` option
    ``cinder.keymgr.barbican.BarbicanKeyManager``, use ``backend`` option
    `barbican``
  - ``cinder.keymgr.conf_key_mgr.ConfKeyManager`` still remains, but
    the ``fixed_key`` configuration options should be moved to the ``[key_manager]`` section

.. releasenotes/notes/remove-deprecated-nova-opts-b1ec66fe3a9bb3b9.yaml @ b'c463c6f50c5d1cf6277539626fe386f6d4df6355'

- Removed the deprecated options for the Nova connection:> os_privileged_user{name, password, tenant, auth_url}, nova_catalog_info, nova_catalog_admin_info, nova_endpoint_template, nova_endpoint_admin_template, nova_ca_certificates_file, nova_api_insecure. From Pike, using the [nova] section is preferred to configure compute connection for Guest Assisted Snapshost or the InstanceLocalityFilter.

.. releasenotes/notes/remove-hitachi-57d0b37cb9cc7e13.yaml @ b'55d726e5c366834a4dc3131326e9bd3850a6e22f'

- The Hitachi HNAS, HBSD, and VSP volume drivers were marked as deprecated
  in the Pike release and have now been removed. Hitachi storage drivers are
  now only available directly from Hitachi.

.. releasenotes/notes/remove-hp3par-config-options-3cf0d865beff9018.yaml @ b'b36ec9c29b742b416f2eba5cb6a5563d85c3c7af'

- The old deprecated ``hp3par*`` options have been removed.
  Use the ``hpe3par*`` instead of them.

.. releasenotes/notes/remove-nas-ip-config-option-8d56c14f1f4614fc.yaml @ b'd3d53eeb84b417f83db5995bd4640b768d6763bf'

- The old deprecated ``nas_ip`` option has been removed.
  Use the ``nas_host`` instead of it.

.. releasenotes/notes/remove-netapp-teseries-thost-type-config-option-908941dc7d2a1d59.yaml @ b'93b4b27dccf5a317ceb12880ab48e39bc4c2b24c'

- The old deprecated ``netapp_eseries_host_type`` option has been removed.
  Use the ``netapp_host_type`` instead.

.. releasenotes/notes/remove-pybasedir-config-option-572604d26a57ba5e.yaml @ b'b8a553dfedc9fb2667945cf7b158c64edd05a05e'

- The old deprecated ``pybasedir`` option has been removed.
  Use the ``state_path`` instead.

.. releasenotes/notes/remove_osapi_volume_base_url-33fed24c4ad1b2b6.yaml @ b'efc9016055b81872eb548f2a61b55d651f912658'

- The `osapi_volume_base_URL` config option was deprecated in Pike and has
  now been removed. The `public_endpoint` config option should be used
  instead.

.. releasenotes/notes/removed-apiv1-616b1b76a15521cf.yaml @ b'3e91de956e1947a7014709010b99df380242ac74'

- The Cinder API v1 was deprecated in the Juno release and defaulted to be
  disabled in the Ocata release. It is now removed completely.
  If upgrading from a previous version, it is recommended you edit your
  `/etc/cinder/api-paste.ini` file to remove all references to v1.

.. releasenotes/notes/rename-windows-iscsi-a7b0ca62a48c1371.yaml @ b'0914b850f9d850543dedb4183d427462ee994a4c'

- The Windows iSCSI driver has been renamed. The updated driver location
  is ``cinder.volume.drivers.windows.iscsi.WindowsISCSIDriver``.

.. releasenotes/notes/type-extra-spec-policies-b7742b0ac2732864.yaml @ b'7bd2950ad53603457f539d7afa54c710137313fc'

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

.. releasenotes/notes/update_config_options_disco_volume_driver-07e52aa43e83c243.yaml @ b'1a3f91662c383f105a74638c84655689ab5eac60'

- We replaced the config option in the disco volume driver
  "disco_choice_client" with "disco_client_protocol".
  We add "san_api_port" as new config option in san driver for accessing
  the SAN API using this port.

.. releasenotes/notes/vmware-vmdk-snapshot-template-d3dcfc0906c02edd.yaml @ b'f36fc239804fb8fbf57d9df0320e2cb6d315ea10'

- VMware VMDK driver will use vSphere template as the
  default snapshot format in vCenter server.


.. _Queens Series Release Notes_12.0.0_stable_queens_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/backup-driver-configuration-36357733962dab03.yaml @ b'de2ffaff36e3713e3862b15816f59c4d3dd8abca'

- Backup driver initialization using module name is deprecated.

.. releasenotes/notes/castellan-backend-0c49591a54821c45.yaml @ b'e75be5d90519094fca3ee475b906e7c2fe1d09fd'

- The Castellan library used for encryption has deprecated the ``api_class``
  config option. Configuration files using this should now be updated to use
  the ``backend`` option instead.

.. releasenotes/notes/deprecate-backup-service-to-driver-mapping-a3afabd4f55eca01.yaml @ b'1fedb7334bb0a3b6d585d00f91516ad2a9b4bde7'

- Backup service to driver mapping is deprecated. If you use old values
  like 'cinder.backup.services.swift' or 'cinder.backup.services.ceph'
  it should be changed to 'cinder.backup.drivers.swift' or
  'cinder.backup.drivers.ceph' accordingly to get your backup service
  working in the 'R' release.

.. releasenotes/notes/deprecate-consistency-group-apis-0d9120d16f090781.yaml @ b'556ae86d382bc4bf9a4272884dd1f8ed5f694b4e'

- The Consistency Group APIs have now been marked as deprecated and
  will be removed in a future release. Generic Volume Group APIs should
  be used instead.

.. releasenotes/notes/deprecate_hosts_api_extension-fe0c042af10a20db.yaml @ b'74746b3407684df6a6e687ce502ffdc7c57f44ab'

- The hosts api extension is now deprecated and will be removed in a
  future version.

.. releasenotes/notes/deprecate_logs_commands-a0d59cb7535a2138.yaml @ b'7c00d9b966abac50ad5ad8664fbe327ba2aca10e'

- Deprecate the "cinder-manage logs" commands.  These will be removed
  in a later release.

.. releasenotes/notes/lvm-thin-overprovision-1d279f66ee2252ff.yaml @ b'9d4922771383bdd24261cde95ce322d7e04d67f3'

- The `lvm_max_overprovision_ratio` config option has been deprecated. It
  will be removed in a future release. Configurations should move to using
  the common `max_overprovision_ratio` config option.

.. releasenotes/notes/mark-cisco-zm-unsupported-57e5612f57e2407b.yaml @ b'c92c428233df7b42bea05bf5468771c07fa8e51b'

- The Cisco Firbre Channel Zone Manager driver has been marked as
  unsupported and is now deprecated. ``enable_unsupported_driver``
  will need to be set to ``True`` in the driver's section in cinder.conf
  to continue to use it. If its support status does not change, they
  will be removed in the Queens development cycle.

.. releasenotes/notes/rename-iscsi-target-config-options-24913d7452c4a58e.yaml @ b'4b092e8d9d6611d73e22177cb57581e3e2cecee3'

- ``iscsi_ip_address``, ``iscsi_port``, ``target_helper``,
  ``iscsi_target_prefix`` and ``iscsi_protocol`` config options are
  deprecated in flavor of ``target_ip_address``, ``target_port``,
  ``target_helper``, ``target_prefix`` and ``target_protocol`` accordingly.
  Old config options will be removed in S release.

.. releasenotes/notes/vmax-deprecate-backend-xml-708a41919bcc55a8.yaml @ b'ec7f04ee97d9484845c41b8c775ec248da8cda4b'

- The use of xml files for vmax backend configuration is now deprecated and
  will be removed during the following release. Deployers are encouraged
  to use the cinder.conf for configuring connections to the vmax.


.. _Queens Series Release Notes_12.0.0_stable_queens_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1560867-support-nova-specific-image-7yt6fd1173c4e3wd.yaml @ b'25dd8109df4425e7f470429956d093bf59fcf669'

- Fix the bug that Cinder can't support creating volume from Nova specific image which only includes ``snapshot-id`` metadata (Bug

.. releasenotes/notes/bug-1587376-fix-manage-resource-quota-issue-78f59f39b9fa4762.yaml @ b'e72f0fdf2678482723e95bcc89a8c2117865c8a7'

- Fix the bug that Cinder would commit quota twice in a clean environment when managing volume and snapshot resource (Bug

.. releasenotes/notes/bug-1632333-netapp-ontap-copyoffload-downloads-glance-image-twice-08801d8c7b9eed2c.yaml @ b'c27173bad69da4889a5237cf2becc14bb6fc578a'

- Fixed bug 1632333 with the NetApp ONTAP Driver. Now the copy offload method is invoked
  early to avoid downloading Glance images twice.

.. releasenotes/notes/bug-1691771-fix-netapp-manage-volumes-62bec192a08b3ceb.yaml @ b'4b874c5ddc154629a82814d26b64b7eb0c0fb5d6'

- The NetApp cDOT driver operating with NFS protocol has been fixed to manage volumes correctly when ``nas_secure_file_operations`` option has been set to False.

.. releasenotes/notes/bug-1699936-fix-host-show-incorrect-fg8698gu7y6r7d15.yaml @ b'f50b3555773a1559e29c75ac48857b50cea8dfe5'

- Now the ``os-host show`` API will count project's
  resource correctly.

.. releasenotes/notes/bug-1714209-netapp-ontap-drivers-oversubscription-issue-c4655b9c4858d7c6.yaml @ b'42b8b7fe60ffdd7a7772dc0ab228265dc83344bc'

- The ONTAP drivers ("7mode" and "cmode") have been fixed to not report consumed space as "provisioned_capacity_gb". They instead rely on the cinder scheduler's calculation of "provisioned_capacity_gb". This fixes the oversubscription miscalculations with the ONTAP drivers. This bugfix affects all three protocols supported by these drivers (iSCSI/FC/NFS).

.. releasenotes/notes/bug-1718739-netapp-eseries-fix-provisioned-capacity-report-8c51fd1173c15dbf.yaml @ b'f905253b9443db1870c3d2b7b70e032bb089efa0'

- The NetApp E-series driver has been fixed to correctly report the "provisioned_capacity_gb". Now it sums the capacity of all the volumes in the configured backend to get the correct value. This bug fix affects all the protocols supported by the driver (FC and iSCSI).

.. releasenotes/notes/bug-1723226-allow-purging-0day-4de8979db7215cf3.yaml @ b'2a44b3cdba722682a326155060c12c51b5fca1fb'

- Added ability to purge records less than 1 day old, using the cinder-manage db_purge utility.
  This helps especially for those testing scenarios in which a a large number of volumes are created and deleted.
  (bug

.. releasenotes/notes/fix-backup-handling-of-encryption-key-id-f2fa56cadd80d582.yaml @ b'bec756e0401bfbb7a31a0532e4163fcf29126f32'

- Fix the way encryption key IDs are managed for encrypted volume backups.
  When creating a backup, the volume's encryption key is cloned and assigned
  a new key ID. The backup's cloned key ID is now stored in the backup
  database so that it can be deleted whenever the backup is deleted.

  When restoring the backup of an encrypted volume, the destination volume
  is assigned a clone of the backup's encryption key ID. This ensures every
  restored backup has a unique encryption key ID, even when multiple volumes
  have been restored from the same backup.

.. releasenotes/notes/fix-reserve-volume-policy-31790a8d865ee0a1.yaml @ b'678b9de0f43fa666946a064edc32f38514dfd593'

- The reserve volume API was incorrectly enforcing "volume:retype" policy
  action. It has been corrected to "volume_extension:volume_actions:reserve".

.. releasenotes/notes/fix-vol-image-metadata-endpoints-returning-none-ba0590e6c6757b0c.yaml @ b'b5f6c2864f5ca829854af5c12f37a3d49ccc9d5f'

- Fix the following volume image metadata endpoints returning None following
  policy enforcement failure:

  * ``os-set_image_metadata``
  * ``os-unset_image_metadata``

  The endpoints will now correctly raise a 403 Forbidden instead.

.. releasenotes/notes/group-update-d423eaa18dbcecc1.yaml @ b'fdfb2d51a4f362091ab5e94981d18d7741f11cf6'

- Volume group updates of any kind had previously required the group to be
  in ``Available`` status. Updates to the group name or
  description will now work regardless of the volume group status.

.. releasenotes/notes/netapp_fix_svm_scoped_permissions.yaml @ b'887797541dff6d2cd10265de26214bcf1515fcf7'

- NetApp cDOT block and file drivers have improved support for SVM scoped user accounts. Features not supported for SVM scoped users include QoS, aggregate usage reporting, and dedupe usage reporting.

.. releasenotes/notes/ps-duplicate-ACL-5aa447c50f2474e7.yaml @ b'22c09d57687b98faf4193cb1be3d738ddf3bbd28'

- Dell EMC PS Series Driver code was creating duplicate ACL records during live migration. Fixes the initialize_connection code to not create access record for a host if one exists previously. This change fixes bug 1726591.

.. releasenotes/notes/ps-extend_volume-no-snap-8aa447c50f2475a7.yaml @ b'0910706e762cec88a2b53e82bd7e6a1c372163b9'

- Dell EMC PS Series Driver was creating unmanaged snapshots when extending volumes. Fixed it by adding the missing no-snap parameter. This changes fixes bug 1720454.

.. releasenotes/notes/ps-optimize-parsing-8aa447c50f2474c7.yaml @ b'a9a0c2ee2e973d0594f2707d64846e882e179c94'

- Dell EMC PS Series Driver code reporting volume stats is now optimized to return the information earlier and accelerate the process. This change fixes bug 1661154.

.. releasenotes/notes/ps-over-subscription-ratio-cal-8aa447c50f2474a8.yaml @ b'761f0c3e66691e6f5c683a63a81beccbbca1cacf'

- Dell EMC PS Driver stats report has been fixed, now reports the
  `provisioned_capacity_gb` properly. Fixes bug 1719659.

.. releasenotes/notes/pure-default-replica-interval-07de0a56f61c7c1e.yaml @ b'f82d2bf6f13a360f6a1c08066cf682e2e07043db'

- Fixes an issue where starting the Pure volume drivers with replication enabled and default values for pure_replica_interval_default would cause an error to be raised from the backend.

.. releasenotes/notes/rbd-stats-report-0c7e803bb0b1aedb.yaml @ b'8469109016bcfd5806e230202e1996a8ba649535'

- RBD stats report has been fixed, now properly reports
  `allocated_capacity_gb` and `provisioned_capacity_gb` with the sum of the
  sizes of the volumes (not physical sizes) for volumes created by Cinder and
  all available in the pool respectively.  Free capacity will now properly
  handle quota size restrictions of the pool.

.. releasenotes/notes/releasenotes/notes/bug-1735337-remove-skip-quota-validation-flag-2ecb24143f1f1292.yaml @ b'7310676502f34a3e38329995731e12bcd5331210'

- Quota validations are now forced for all APIs. skip_validation flag is now removed from the request body for the quota-set update API.

.. releasenotes/notes/windows-multiple-backends-9aa83631ad3d42f2.yaml @ b'3510f3860481482b2311ef3eef8b5fd6cabb2337'

- Multiple backends may now be enabled within the same Cinder Volume service
  on Windows by using the ``enabled_backends`` config option.


.. _Queens Series Release Notes_12.0.0_stable_queens_Other Notes:

Other Notes
-----------

.. releasenotes/notes/policy-in-code-226f71562ab28195.yaml @ b'9fe72de4b690bc5c964c12715581128830c667d5'

- Default `policy.json` file is now removed as Cinder now uses default
  policies. A policy file is only needed if overriding one of the defaults.


