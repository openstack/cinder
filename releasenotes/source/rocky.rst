==========================
Rocky Series Release Notes
==========================

.. _Rocky Series Release Notes_13.0.9-7_stable_rocky:

13.0.9-7
========

.. _Rocky Series Release Notes_13.0.9-7_stable_rocky_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-fix-1867163-27afa39ac77b9e15.yaml @ b'917e0b0cef91686787fe7cf4185cd4efb03d6361'

- PowerMax Driver - Issue with upgrades from pre Pike to Pike and later.
  The device is not found when trying to snapshot a legacy volume.


.. _Rocky Series Release Notes_13.0.9_stable_rocky:

13.0.9
======

.. _Rocky Series Release Notes_13.0.9_stable_rocky_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/support-incremental-backup-completion-in-rbd-1f2165fefcc470d1.yaml @ b'bce6d01e153100681540d29496d2332c45b53eb3'

- Fixed issue where all Ceph RBD backups would be incremental after the first one. The driver now honors whether ``--incremental`` is specified or not.


.. _Rocky Series Release Notes_13.0.8_stable_rocky:

13.0.8
======

.. _Rocky Series Release Notes_13.0.8_stable_rocky_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bugfix-1744692-5aebd0c97ae66407.yaml @ b'b886d093d782301829afb42e6476b0f5a4678fba'

- Fixes a bug that prevented distributed file system drivers from creating
  snapshots during volume clone operations (NFS, WindowsSMBFS, VZstorage
  and Quobyte drivers). Fixing this allows creating snapshot based backups.

.. releasenotes/notes/detachedinstanceerror-64be35894c624eae.yaml @ b'eabf648b7acce33cb93d667e8f6e70505093b4c9'

- Fix DetachedInstanceError is not bound to a Session for VolumeAttachments.
  This affected VolumeList.get_all, and could make a service fail on startup
  and make it stay in down state.


.. _Rocky Series Release Notes_13.0.7_stable_rocky:

13.0.7
======

.. _Rocky Series Release Notes_13.0.7_stable_rocky_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/hpe-3par-specify-nsp-for-fc-bootable-volume-f372879e1b625b4d.yaml @ b'df7fd514a77734e5d57a56d5c0f34d0245efc86c'

- `Bug 1809249 <https://bugs.launchpad.net/cinder/+bug/1809249>`_ -
  3PAR driver adds the config option `hpe3par_target_nsp` that can be
  set to the 3PAR backend to use when multipath is not enabled and
  the Fibre Channel Zone Manager is not used.

.. releasenotes/notes/sc-handle-multiattach-onterminate-6ab1f96f21bb284d.yaml @ b'767bdf1a5e28f18c12dba03adc429766f9be79d6'

- Dell EMC SC Driver: Fixes `bug 1822229
  <https://bugs.launchpad.net/cinder/+bug/1822229>`__
  to handle the volume mappings in the backend when a volume
  is attached to multiple instances on the same host.


.. _Rocky Series Release Notes_13.0.6_stable_rocky:

13.0.6
======

.. _Rocky Series Release Notes_13.0.6_stable_rocky_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/kaminario-cinder-driver-bug-44c728f026394a85.yaml @ b'4467c231b029e608104068d33780b8ad021c00d1'

- Kaminario FC and iSCSI drivers: Fixed `bug 1829398
  <https://bugs.launchpad.net/cinder/+bug/1829398>`_ where
  force detach would fail.

.. releasenotes/notes/netapp-non-discovery-19af4e10f7b190ea.yaml @ b'8be2bb6d2a31b157a5247de9068806fd11ac4075'

- NetApp iSCSI drivers no longer use the discovery mechanism for multipathing
  and they always return all target/portals when attaching a volume.  Thanks
  to this, volumes will be successfully attached even if the target/portal
  selected as primary is down, this will be the case for both, multipath and
  single path connections.


.. _Rocky Series Release Notes_13.0.4_stable_rocky:

13.0.4
======

.. _Rocky Series Release Notes_13.0.4_stable_rocky_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1773446-984d76ed29445c9b.yaml @ b'6ca3f2badfc76343db74ce6cea4b91b1c0fc6d17'

- Fixed group availability zone-backend host mismatch
  [`Bug 1773446 <https://bugs.launchpad.net/cinder/+bug/1773446>`_].

.. releasenotes/notes/fix-multiattach-deletion-b3990acf1f5fd378.yaml @ b'10baccdccbccb2e08a834495ff909a23c08306dd'

- Fixed NetApp SolidFire bug that avoided multiatached volumes to be deleted.

.. releasenotes/notes/vnx-update-sg-in-cache-3ecb673727bea79b.yaml @ b'1f57f502c893a840ee5021fbca36ae95eed50e73'

- Dell EMC VNX Driver: Fixes `bug 1817385
  <https://bugs.launchpad.net/cinder/+bug/1817385>`__ to make sure the sg can
  be created again after it was destroyed under `destroy_empty_storage_group`
  setting to `True`.


.. _Rocky Series Release Notes_13.0.3_stable_rocky:

13.0.3
======

.. _Rocky Series Release Notes_13.0.3_stable_rocky_New Features:

New Features
------------

.. releasenotes/notes/multiple_clone-82bd7f80ae439080.yaml @ b'90e3517dad84ca32d2490e942f0e7b933c167be3'

- VMAX driver support for new configuration option - vmax_snapvx_unlink_limit for specifying the maximum number of unlinks which will be performed before a clone operation. Default value is 3


.. _Rocky Series Release Notes_13.0.3_stable_rocky_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1805550-default-policy-file-db15eaa76fefa115.yaml @ b'd07abe397c5bdfb45a82150fb7e1a9efaf21ce42'

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


.. _Rocky Series Release Notes_13.0.3_stable_rocky_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1790141-vmax-powermaxos-upgrade-fix-4c76186cfca66790.yaml @ b'f9bfbec2b5e35d1ae8df51229dd4105221b2761f'

- PowerMax driver - Workload support was dropped in ucode 5978. If a VMAX All Flash array is upgraded to 5978 or greater and existing volume types leveraged workload e.g. DSS, DSS_REP, OLTP and OLTP_REP, certain operations will no longer work and the volume type will be unusable. This fix addresses these issues and fixes problems with using old volume types with workloads included in the volume type pool_name.

.. releasenotes/notes/bug-1799221-fix-truncated-volumes-in-case-of-glance-errors-6cae19218249c3cf.yaml @ b'bf89f76fb1b7a52299c17467106018eae01608e8'

- Fixed a bug which could create volumes with invalid content in case of
  unhandled errors from glance client
  (Bug `#1799221 <https://bugs.launchpad.net/cinder/+bug/1799221>`_).

.. releasenotes/notes/bug-reno-69539ecb9b0b5464.yaml @ b'6ceed81d4b25978ac64bf36afa45c021ef95d02f'

- The Solidfire cinder driver has been fixed to ensure delete happens
  on the correct volume.


.. _Rocky Series Release Notes_13.0.2_stable_rocky:

13.0.2
======

.. _Rocky Series Release Notes_13.0.2_stable_rocky_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/cinder-manage-online-migrations-exit-status-7c16edb7facc37bb.yaml @ b'74fd810ad1a8561ba150925d19feb8cbe598fe84'

- The ``cinder-manage db online_data_migrations`` command now returns exit
  status 2 in the case where some migrations failed (raised exceptions) and
  no others were completed successfully from the last batch attempted. This
  should be considered a fatal condition that requires intervention. Exit
  status 1 will be returned in the case where the ``--max-count`` option was
  used and some migrations failed but others succeeded (updated at least one
  row), because more work may remain for the non-failing migrations, and
  their completion may be a dependency for the failing ones. The command
  should be reiterated while it returns exit status 1, and considered
  completed successfully only when it returns exit status 0.


.. _Rocky Series Release Notes_13.0.1_stable_rocky:

13.0.1
======

.. _Rocky Series Release Notes_13.0.1_stable_rocky_Known Issues:

Known Issues
------------

.. releasenotes/notes/lio-multiattach-disabled-a6ee89072fe5d032.yaml @ b'dd5a565c5ba587b0306bb29509293cf1b7c04bc3'

- Multiattach support is disabled for the LVM driver when using the LIO iSCSI
  target.  This functionality will be fixed in a later release.


.. _Rocky Series Release Notes_13.0.1_stable_rocky_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bugfix-netapp-driver-cinder-ipv6-c3c4d0d6a7d0de91.yaml @ b'b290b49183200fb9dbc4fff655f00cfaf3c8b67a'

- Fixed support for IPv6 on management and data paths for NFS, iSCSI and FCP NetApp ONTAP drivers.

.. releasenotes/notes/fix-netapp-cg-da4fd6c396e5bedb.yaml @ b'fb69816509c86736a8cf8e1c9602873f3a787ed3'

- Fixes a bug in NetApp SolidFire where the deletion of group snapshots was failing.

.. releasenotes/notes/fix-netapp-force_detach-36bdf75dd2c9a030.yaml @ b'bfcd4b2f1be3ab37ae0801dd523ce952577cda14'

- Fixes force_detach behavior for volumes in NetApp SolidFire driver.


.. _Rocky Series Release Notes_13.0.0_stable_rocky:

13.0.0
======

.. _Rocky Series Release Notes_13.0.0_stable_rocky_New Features:

New Features
------------

.. releasenotes/notes/add-operation-to-request-spec-7yt6ub75uy1284as.yaml @ b'e1ec4b4c2e1f0de512f09e38824c1d7e2fa38617'

- Now scheduler plugins are aware of operation type via ``operation`` attribute in
  RequestSpec dictionary, plugins can support backend filtering according to backend
  status as well as operation type. Current possible values for ``operation`` are:

  - create_volume
  - extend_volume
  - create_snapshot
  - retype_volume
  - migrate_volume
  - manage_existing
  - manage_existing_snapshot
  - create_group

.. releasenotes/notes/add-split-logger-conf-option-0424e3bd91de3a5a.yaml @ b'70c48ff6bbf7c4094da34a1af256ac7fbc032399'

- Added boolean conf option 'split_loggers' in [default] section of
  cinder.conf to `enable split logging`_ functionality. The default
  value of split_loggers option is set to False. Operator can set it's
  value to True to split HTTP content into subloggers to allow for
  fine-grained control of what is logged and how. This new config option
  'split_loggers' should be enabled only when keystoneauth log level is
  set to DEBUG in 'default_log_levels' config option.

  .. _`enable split logging`: https://docs.openstack.org/keystoneauth/latest/using-sessions.html#logging

.. releasenotes/notes/bp-nvmeof-lvm-target-b7771955b426abe7.yaml @ b'8d7e131c587f31d85c76f990998d411af490554f'

- A new target, NVMET, is added for the LVM driver over RDMA,
  it allows cinder to use nvmetcli in order to create/delete
  subsystems on attaching/detaching an LVM volume to/from an
  instance.

.. releasenotes/notes/bug-1686745-e8f1569455f998ba.yaml @ b'abca1abc7b01fc1d85af8b9cfa5b646abafc9d4a'

- Add support to force detach a volume from all hosts on 3PAR.

.. releasenotes/notes/capacity-based-qos-9f5d174658a40bd5.yaml @ b'29d2090aef7b31df23ca846d365c6d21957486ba'

- Cinder now allows for capacity based QoS which can be useful in environments where storage performance scales with consumption (such as RBD backed storage).  The newly added QoS specs are `read_iops_sec_per_gb`, `write_iops_sec_per_gb`, `total_iops_sec_per_gb`, `read_bytes_sec_per_gb`, `write_bytes_sec_per_gb` and `total_bytes_sec_per_gb`.  These values will be multiplied by the size of the volume and passed to the consumer.
  For example, setting `total_iops_sec_per_gb` to 30 and setting `total_bytes_sec_per_gb` to `1048576` (1MB) then creating a 100 GB volume with that QoS will result in a volume with 3,000 total IOPs and 100MB/s throughput limit.

.. releasenotes/notes/capacity-based-qos-minimum-values-b24a5f49c986f11d.yaml @ b'37f2bdcdec85f27651b91a9a2d0fddb66e7bfe8a'

- Cinder now allows for a minimum value when using the capacity based QoS in order to make sure small volumes can get a minimum allocation for them to be usable.
  The newly added QoS specs are `read_iops_sec_per_gb_min`, `write_iops_sec_per_gb_min`, `total_iops_sec_per_gb_min`, `read_bytes_sec_per_gb_min`, `write_bytes_sec_per_gb_min` and `total_bytes_sec_per_gb_min`

.. releasenotes/notes/cheesecake-promotion-30a3336fb911c3ad.yaml @ b'df81b59f9d1f70dcde002eb9252c55e46d77a5c0'

- A new cinder-manage command, reset_active_backend, was added to promote a
  failed-over backend participating in replication.  This allows you to
  reset a backend without manually editing the database.  A backend
  undergoing promotion using this command is expected to be in a disabled
  and frozen state.  Support for both standalone and clustered backend
  configurations are supported.

.. releasenotes/notes/dell-emc-sc-api-timeouts-ce8d166e1847ea94.yaml @ b'1d6ad6ef179f465289c95b5f45ac79b0f03e0866'

- Added dell_api_async_rest_timeout option to the Dell EMC SC driver. This is the timeout used for asynchronous REST calls to the Dell EMC SC REST API. Default is 15 seconds.

.. releasenotes/notes/dell-emc-sc-api-timeouts-ce8d166e1847ea94.yaml @ b'1d6ad6ef179f465289c95b5f45ac79b0f03e0866'

- Added dell_api_sync_rest_timeout option to the Dell EMC SC driver. This is the timeout used for synchronous REST calls to the Dell EMC SC REST API. Default is 30 seconds.

.. releasenotes/notes/dell-emc-sc-mult-attach-d09cfd06ee8db8da.yaml @ b'2e82f0de90d077f7d87353b59c14f69bff3dbaa5'

- Enabled Cinder Multi-Attach capability in the Dell EMC Storage Center Cinder driver.

.. releasenotes/notes/ds8k-allow-multi-attach-41fa7bddbbd719ec.yaml @ b'3599eb5ba948e743ad63999dabeecafa86373ee0'

- IBM DS8K driver has added multiattach support.

.. releasenotes/notes/ds8k-report-backend-state-in-service-list-f0898950a0f4b122.yaml @ b'3e12e2f930be2563f69bed37906521687b9487ae'

- Added flag 'backend_state' which will give backend state info in service list.

.. releasenotes/notes/enable-multiattach-iscsi-fcp-netapp-driver-98ad2d75fbbf333f.yaml @ b'ac0c7d89ba4cb2b1dc894b1f5a1f2361bc36dc0f'

- NetApp ONTAP iSCSI and FCP drivers multiattach capability enabled.

.. releasenotes/notes/enable-multiattach-nfs-netapp-driver-406b9b285d85c989.yaml @ b'4e064a3ae7ddc305e7226432d5248f4d7ae6c77d'

- NetApp ONTAP NFS multiattach capability enabled.

.. releasenotes/notes/feature-abort-restore-fe1252288c59e105.yaml @ b'89f6291ee33780ed6d4e4886d5d18a0ce0cdb182'

- Support backup restore cancelation by changing the backup status to
  anything other than `restoring` using `cinder backup-reset-state`.

.. releasenotes/notes/feature-cross-az-backups-6b68c4c4456f2fd7.yaml @ b'5feaf74ccf10148859e206ce21bfd54dec2c1c16'

- Cinder backup creation can now (since microversion 3.51) receive the
  availability zone where the backup should be stored.

.. releasenotes/notes/feature-multi-process-backup-8cf5ad5a0cf9b2d5.yaml @ b'373b52404151d80e83004a37d543f825846edea1'

- Cinder backup now supports running multiple processes to make the most of
  the available CPU cores.  Performance gains will be significant when
  running multiple concurrent backups/restores with compression.  The number
  of processes is set with `backup_workers` configuration option.

.. releasenotes/notes/feature-rbd-exclusive-pool-a9bdebdeb1f0bf37.yaml @ b'f33baccc3544cbda6cd5908328a56096046657ed'

- When using the RBD pool exclusively for Cinder we can now set
  `rbd_exclusive_cinder_pool` to `true` and Cinder will use DB information
  to calculate provisioned size instead of querying all volumes in the
  backend, which will reduce the load on the Ceph cluster and the volume
  service.

.. releasenotes/notes/google-auth-for-gcs-backup-1642cd0e741fbdf9.yaml @ b'79d7a4e8da6f1118b5c235928876cf78085f4332'

- Google backup driver now supports ``google-auth`` library, and is the preferred library if both ``google-auth`` (together with ``google-auth-httplib2``) and ``oauth2client`` libraries are present in the system.

.. releasenotes/notes/infinidat-multi-attach-support-533b3e559c15801f.yaml @ b'666c0fc8db20dfe1d5adc036d24b52a3eaa1091a'

- Support for volume multi-attach in the INFINIDAT InfiniBox driver.

.. releasenotes/notes/inspur-instorage-fc-cinder-driver-70c13e4a64d785d5.yaml @ b'a6e79968ed237a7f0982cdc0d8fcf231d63b38fc'

- New FC Cinder volume driver for Inspur Instorage.

.. releasenotes/notes/netapp-log-filter-f3256f55c3ac3faa.yaml @ b'bb0aac560dbc5a2859f02824d36bf76d17039358'

- The NetApp ONTAP driver supports a new configuration option ``netapp_api_trace_pattern`` to enable filtering backend API interactions to log. This option must be specified in the backend section when desired and it accepts a valid python regular expression.

.. releasenotes/notes/nexentaedge-iscsi-driver-302529c56cdbbf38.yaml @ b'e2bd03ef75b4417e3531186fd6cc0a270ffbd32c'

- Added backend driver for Nexenta Edge iSCSI storage.

.. releasenotes/notes/pure-active-cluster-edf8e7e80739b0f8.yaml @ b'715069f6155ca292dbe1bddef7b6bd1ec8ea0ccc'

- Added support to Pure Storage Volume Drivers for Active Cluster using the standard replication API's for the Block Storage Service.

.. releasenotes/notes/pure-storage-multiattach-support-994da363e181d627.yaml @ b'8f4802baf51415abd660b1d9bc8bd73e539318e2'

- Pure Storage FlashArray driver has added multiatach support.

.. releasenotes/notes/qnap-support-qes-210-de75892f684cb9c3.yaml @ b'4dceb56f8890a61527a06520abc076c0b42cf92c'

- QNAP Cinder driver added support for QES fw 2.1.0.

.. releasenotes/notes/rbd-active-active-replication-b230367912fe4a23.yaml @ b'245a488c36003764e3550c2c95fa4bef6119e0ea'

- Added support for active-active replication to the RBD driver.  This allows users to configure multiple volume backends that are all a member of the same cluster participating in replication.

.. releasenotes/notes/rbd-support-list-manageable-snapshots-3474c62ed83fb788.yaml @ b'280cc7c5ae4b07a9a1e23b8f9cc925be9872c8e1'

- Allow rbd driver to list manageable snapshots.

.. releasenotes/notes/rbd-support-report-backend-state-4e124eb9efd36724.yaml @ b'006296856808063be6c32c2092b40515b773df84'

- Allow rbd driver to report backend state.

.. releasenotes/notes/report-backend-state-in-service-list-739a5398eec4a6b7.yaml @ b'03676baac5020bafedb3228f561734fb6d89dc8e'

- Added flag 'backend_state: up/down' which will give backend state info in
  service list.

.. releasenotes/notes/report-backend-state-in-service-list-93e9f2b204b735c0.yaml @ b'c5a8000b9c857521e896e1fc39a77f0fcfc12ccc'

- Added flag 'backend_state' which will give backend state info in service list.

.. releasenotes/notes/scaleio-rebranding-d2d113c5d8e5c118.yaml @ b'a852c46ba483e9a015c30a77fa461b45c1517786'

- Dell EMC ScaleIO has been renamed to Dell EMC VxFlex OS.
  Documentation for the driver can be found under the new name.
  The driver maintains full backwards compatability with prior
  ScaleIO releases and no configuration changes are needed upon
  upgrade to the new version of the driver.

.. releasenotes/notes/smbfs-snapshot-attach-14742fe8f5864ac6.yaml @ b'32a08e4d6a18be743e936448f05f97113e80619c'

- The SMBFS driver now supports the 'snapshot attach' feature. Special care
  must be taken when attaching snapshots though, as writing to a snapshot
  will corrupt the differencing image chain.

.. releasenotes/notes/storwize-dr-pool-support-52db3a95e54aef88.yaml @ b'822fb701de48d30e662b5f16270b3c38e8703151'

- Added data reduction pool support for thin-provisoned and compressed
  volume in Storwize cinder driver.

.. releasenotes/notes/support-az-in-volumetype-8yt6fg67de3976ty.yaml @ b'306fa19079ccf8f5278fdf36341edecd95df04a7'

- Now availability zone is supported in volume type as below.

  * ``RESKEY:availability_zones`` now is a reserved spec key for AZ volume type,
    and administrator can create AZ volume type that includes AZ restrictions
    by adding a list of Az's to the extra specs similar to:
    ``RESKEY:availability_zones: az1,az2``.
  * Extra spec ``RESKEY:availability_zones`` will only be used for filtering backends
    when creating and retyping volumes.
  * Volume type can be filtered within extra spec: /types?extra_specs={"key":"value"}
    since microversion "3.52".

.. releasenotes/notes/support-image-signature-verification-yu8qub7286et9dh4.yaml @ b'e8c24577b8bd98d86358abf543010b76229c8757'

- Added image signature verification support when creating volume from image. This depends on signature metadata from glance. This feature is turned on by default, administrators can change behaviour by updating option ``verify_glance_signatures``. Also, an additional image metadata ``signature_verified`` has been added to indicate whether signature verification was performed during creating process.

.. releasenotes/notes/sync-bump-versions-a1e6f6359173892e.yaml @ b'3cd2ebd3759c76fdf5a292e612127094c7aa2b17'

- Cinder-manage DB sync command can now bump the RPC and Objects versions of the services to avoid a second restart when doing offline upgrades.

.. releasenotes/notes/tpool-size-11121f78df24db39.yaml @ b'e570436d1cca5cfa89388aec8b2daa63d01d0250'

- Adds support to configure the size of the native thread pool used by the cinder volume and backup services.  For the backup we use `backup_native_threads_pool_size` in the `[DEFAULT]` section, and for the backends we use `backend_native_threads_pool_size` in the driver section.

.. releasenotes/notes/transfer-snapshots-with-volume-a7763570a807c742.yaml @ b'c0efaa1d46b762693f8fe3a09d0359ead3e097c4'

- Support transfer volume with snapshots by default in new V3 API 'v3/volume_transfers'. After microverison 3.55, if users don't want to transfer snapshots, they could use the new optional argument `no_snapshots=True` in request body of new transfer creation API.

.. releasenotes/notes/unity-compressed-volume-support-4998dee84534a324.yaml @ b'2da949da1f79a0121d75c50eecdd102382287bda'

- Dell EMC Unity driver: Add compressed volume support.

.. releasenotes/notes/unity-enable-ssl-14db2497225c4395.yaml @ b'8aa49599c7df62de5ab25a0a841265092e2881f7'

- Dell EMC Unity Cinder driver allows enabling/disabling the SSL verification. Admin can set `True` or `False` for `driver_ssl_cert_verify` to enable or disable this function, alternatively set the `driver_ssl_cert_path=<PATH>` for customized CA path. Both above 2 options should go under the driver section.

.. releasenotes/notes/unity-multiattach-support-993b997e522d9e84.yaml @ b'dffff08a204ddf6416cd6ddb036e8e029dc80509'

- Dell EMC Unity: Implements `bp unity-multiattach-support
  <https://blueprints.launchpad.net/cinder/+spec/unity-multiattach-support>`__
  to support attaching a volume to multiple servers simultaneously.

.. releasenotes/notes/unity-remove-empty-host-17d567dbb6738e4e.yaml @ b'f9a9aa5a25688cac86e5dc060a20374e4a29bbef'

- Dell EMC Unity Driver: Adds support for removing empty host. The new option
  named `remove_empty_host` could be configured as `True` to notify Unity
  driver to remove the host after the last LUN is detached from it.

.. releasenotes/notes/unity-thick-support-fdbef833f2b4d54f.yaml @ b'e458bdbf84aba2dab5fc0f65a49764466016558b'

- Dell EMC Unity Driver: Add thick volume support. Refer to `Unity Cinder
  Configuration document
  <https://docs.openstack.org/cinder/latest/configuration/block-storage/drivers/dell-emc-unity-driver.html>`__
  to create a thick volume.

.. releasenotes/notes/veritas_access_iscsi_driver-de642dad9e7d0890.yaml @ b'a9fad35a20570e6ecd3757ea50e794a0592c3921'

- Added ISCSI based driver for Veritas Access.

.. releasenotes/notes/vmax-driver-multiattach-support-43a7f99cd2d742ee.yaml @ b'106cf3cbf0a094755d4af063a05de9aa36ae385d'

- Dell EMC VMAX driver has added multiattach support.

.. releasenotes/notes/vmax-list-manageable-vols-snaps-6a7f5aa114fae8f3.yaml @ b'd05a7a10dc04335c205ab3ee5a2d03a62c26b8e8'

- Dell EMC VMAX driver has added list manageable volumes and snapshots support.

.. releasenotes/notes/vmax-metadata-ac9bdd31e7e561c3.yaml @ b'4662ead8c3ef1970bc7be7815bcbacc221f6fe1e'

- Log VMAX specific metadata of a volume if debug is enabled.

.. releasenotes/notes/vmax-retype-replicated-volumes-325be6e5fd626819.yaml @ b'992542a9fb00efdd479d2d18fd6da848b162adf9'

- Support for retype (storage-assisted migration) of replicated volumes on VMAX cinder driver.

.. releasenotes/notes/vmware_vmdk_datastore_regex-fe7b68ad69ef7384.yaml @ b'f1e21ee2526e35c60f5d2251d569469dddd4efc5'

- VMware VMDK driver and FCD driver now support a config option
  ``vmware_datastore_regex`` to specify the regular expression
  pattern to match the name of datastores where backend volumes
  are created.

.. releasenotes/notes/vmware_vmdk_nfs41-450908bbbc9eea6d.yaml @ b'68e3b4a1d544683a7d7b0cfd7f730dc9a0bbdd77'

- VMware VMDK driver and FCD driver now support NFS 4.1
  datastores in vCenter server.

.. releasenotes/notes/vnx-revert-to-snapshot-e5494b6fb5ad5a1e.yaml @ b'2cd65abb713381bbf6155e6e176043f9c41c04a7'

- Added support to revert a volume to a snapshot with the Dell EMC VNX
  driver.

.. releasenotes/notes/windows-volume-backup-b328858a20f5a499.yaml @ b'302402df330a52fbe9e531cf5603babad0c1f367'

- The Cinder Volume Backup service can now be run on Windows. It supports
  backing up volumes exposed by SMBFS/iSCSI Windows Cinder Volume backends,
  as well as any other Cinder backend that's accessible on Windows (e.g.
  SANs exposing volumes via iSCSI/FC).

  The Swift and Posix backup drivers are known to be working on Windows.

.. releasenotes/notes/xtremio-support-multiattache-20b1882a1216a8b2.yaml @ b'607e7688b90e8233ac8c52b896fa11ca44a2b026'

- Dell EMC XtremIO driver has added multiattach support.


.. _Rocky Series Release Notes_13.0.0_stable_rocky_Known Issues:

Known Issues
------------

.. releasenotes/notes/feature-rbd-exclusive-pool-a9bdebdeb1f0bf37.yaml @ b'f33baccc3544cbda6cd5908328a56096046657ed'

- If RBD stats collection is taking too long in your environment maybe even
  leading to the service appearing as down you'll want to use the
  `rbd_exclusive_cinder_pool = true` configuration option if you are using
  the pool exclusively for Cinder and maybe even if you are not and can live
  with the innacuracy.


.. _Rocky Series Release Notes_13.0.0_stable_rocky_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/coprhd-mark-unsupported-aa48145873db1ab1.yaml @ b'19d5e68b46c829cee9285c5baeff16771c1942e2'

- The Dell EMC CoprHD drivers have been marked as unsupported and are now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it.

.. releasenotes/notes/datacore-mark-unsupported-2399bc19a789fb4c.yaml @ b'13b9df4074de945cb21d8c1a66b7746a4b3c4c61'

- The DataCore drivers have been marked as unsupported and are now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it.

.. releasenotes/notes/disco-mark-unsupported-f6eb8208c8c4eb3b.yaml @ b'4f4a6ba23f2e479dd00a6ce9c80a968032f3f57d'

- The Disco driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it.

.. releasenotes/notes/hgst-mark-unsupported-b2886de36421c8b0.yaml @ b'c88d7ba117205f433be4fcde0c1fef71534c6cad'

- The HGST driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it.

.. releasenotes/notes/nec-delete-volume-per-limit-d10b9df86f64b80e.yaml @ b'ecfd4d393a12b408b9961358841c70d20b476f49'

- In NEC driver, the number of volumes in a storage pool is no longer limited to 1024. More volumes can be created with storage firmware revision 1015 or later.

.. releasenotes/notes/privsep-rocky-35bdfe70ed62a826.yaml @ b'861646d1ba53f6becea59bc50306229e162f0c6c'

- The following commands are no longer required to be listed in your rootwrap
  configuration: cgcreate; and cgset.

.. releasenotes/notes/remove-backup-service-to-driver-mapping-4d2ed6f868a64175.yaml @ b'497cd4e3cdbea7b61d9bca46a65561993e0b9f26'

- Backup service to driver mapping is removed. If you use old values like
  'cinder.backup.services.swift' or 'cinder.backup.services.ceph' it should
  be changed to 'cinder.backup.drivers.swift' or 'cinder.backup.drivers.ceph'
  accordingly to get your backup service working.

.. releasenotes/notes/remove-deprecated-option-9ad954726ed4d8c2.yaml @ b'd1c5379369b24effdccfe5dde3e93bd21884eda5'

- Removed the option ``allow_inuse_volume_type_modification`` which had
  been deprecated in Ocata release.

.. releasenotes/notes/remove-lvm-over-sub-3c8addbf47827045.yaml @ b'2c05388d5ccbbecbbe02b45aec30f24321da0057'

- The LVM driver specific `lvm_max_over_subscription_ratio` setting had been
  deprecated and is now removed. Over subscription should now be managed
  using the generic `max_over_subscription_ratio` setting.

.. releasenotes/notes/remove_deprecated_xml-4065b893d781f65c.yaml @ b'c0a5be259e608808d1866dd8f54bcacf8ab6365b'

- VMAX driver - Removed deprecated option ``cinder_dell_emc_config_file``

.. releasenotes/notes/sync-bump-versions-a1e6f6359173892e.yaml @ b'3cd2ebd3759c76fdf5a292e612127094c7aa2b17'

- On offline upgrades, due to the rolling upgrade mechanism we need to restart the cinder services twice to complete the installation just like in the rolling upgrades case.  First you stop the cinder services, then you upgrade them, you sync your DB, then you start all the cinder services, and then you restart them all.  To avoid this last restart we can now instruct the DB sync to bump the services after the migration is completed, the command to do this is `cinder-manage db sync --bump-versions`


.. _Rocky Series Release Notes_13.0.0_stable_rocky_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/add-option-max_luns_per_storage_group-dfe3e1396b262bc8.yaml @ b'04847424b462ceade2daaca519a14e28779a026d'

- Deprecate option `check_max_pool_luns_threshold`. The VNX driver will
  always check the threshold.

.. releasenotes/notes/coprhd-mark-unsupported-aa48145873db1ab1.yaml @ b'19d5e68b46c829cee9285c5baeff16771c1942e2'

- The Dell EMC CoprHD drivers have been marked as unsupported and are now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it. If its support status does not change, they will be
  removed in the Stein development cycle.

.. releasenotes/notes/datacore-mark-unsupported-2399bc19a789fb4c.yaml @ b'13b9df4074de945cb21d8c1a66b7746a4b3c4c61'

- The DataCore drivers have been marked as unsupported and are now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it. If its support status does not change, they will be
  removed in the Stein development cycle.

.. releasenotes/notes/deprecate_san_rest_port-0d8610a872e92e09.yaml @ b'017dd6b4bcf92c14d49421268cb571c00879f3cc'

- VMAX driver - configuration tag san_rest_port will be replaced by
  san_api_port in the next release.

.. releasenotes/notes/disco-mark-unsupported-f6eb8208c8c4eb3b.yaml @ b'4f4a6ba23f2e479dd00a6ce9c80a968032f3f57d'

- The Disco driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it. If its support status does not change, it will be
  removed in the Stein development cycle.

.. releasenotes/notes/google-auth-for-gcs-backup-1642cd0e741fbdf9.yaml @ b'79d7a4e8da6f1118b5c235928876cf78085f4332'

- Cinder's Google backup driver is now called gcs, so ``backup_driver`` configuration for Google Cloud Storage should be updated from ``cinder.backup.drivers.google`` to ``cinder.backup.driver.gcs``.

.. releasenotes/notes/hgst-mark-unsupported-b2886de36421c8b0.yaml @ b'c88d7ba117205f433be4fcde0c1fef71534c6cad'

- The HGST driver has been marked as unsupported and is now
  deprecated. ``enable_unsupported_driver`` will need to be set
  to ``True`` in the driver's section in cinder.conf to continue
  to use it. If its support status does not change, it will be
  removed in the Stein development cycle.

.. releasenotes/notes/netapp-deprecate-eseries-drivers-bc4f552d277c07b9.yaml @ b'747373f4bdfe4814000a88e4443b56545d5d55bd'

- The NetApp E-Series drivers are deprecated as of the Rocky release and will be removed in the Stein release. Other configurations of the NetApp driver, i.e Clustered Data ONTAP and Solidfire, are unaffected.


.. _Rocky Series Release Notes_13.0.0_stable_rocky_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1784871-7f67402eb13abca7.yaml @ b'3a39d09166bf6d1c7d2bae63caf3e2a954328862'

- Removed the ability to create volumes in a ScaleIO Storage Pool
  that has zero-padding disabled.
  A new configuration option had been added to override this new
  behavior and allow volume creation, but should not be enabled if
  multiple tenants will utilize volumes from a shared Storage Pool.

.. releasenotes/notes/privsep-rocky-35bdfe70ed62a826.yaml @ b'861646d1ba53f6becea59bc50306229e162f0c6c'

- Privsep transitions. Cinder is transitioning from using the older style
  rootwrap privilege escalation path to the new style Oslo privsep path.
  This should improve performance and security of Cinder in the long term.

.. releasenotes/notes/privsep-rocky-35bdfe70ed62a826.yaml @ b'861646d1ba53f6becea59bc50306229e162f0c6c'

- Privsep daemons are now started by Cinder when required. These daemons can
  be started via rootwrap if required. rootwrap configs therefore need to
  be updated to include new privsep daemon invocations.

.. releasenotes/notes/scaleio-zeropadding-a0273c56c4d14fca.yaml @ b'41de06dcf6f1c84b6d4eb2f8d3b4f002d8c67f96'

- Removed the ability to create volumes in a ScaleIO Storage Pool that has
  zero-padding disabled. A new configuration option
  ``sio_allow_non_padded_volumes`` has been added to override this new
  behavior and allow unpadded volumes, but should not be enabled if multiple
  tenants will utilize volumes from a shared Storage Pool.


.. _Rocky Series Release Notes_13.0.0_stable_rocky_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/add-option-max_luns_per_storage_group-dfe3e1396b262bc8.yaml @ b'04847424b462ceade2daaca519a14e28779a026d'

- Add option `max_luns_per_storage_group` back. The max LUNs per storage
  group was set to 255 before. With the new option, admin can set it to a
  larger number.

.. releasenotes/notes/bug-1690954-40fc21683977e996.yaml @ b'4d75cbf3c35a8aa917d3970beac99d612f13eed3'

- NetApp ONTAP NFS (bug 1690954): Fix wrong usage of export path
  as volume name when deleting volumes and snapshots.

.. releasenotes/notes/bug-1712651-7bc90264eb5001ea.yaml @ b'2b60912d5667350eae7ecbc67d4dba3658518d10'

- NetApp ONTAP iSCSI (bug 1712651): Fix ONTAP NetApp iSCSI driver not
  raising a proper exception when trying to extend an attached volume
  beyond its max geometry.

.. releasenotes/notes/bug-1762424-f76af2f37fe408f1.yaml @ b'029cadbf4067ad6f0bf08588cf439587f3c7052c'

- NetApp ONTAP (bug 1762424): Fix ONTAP NetApp driver not being able to extend
  a volume to a size greater than the corresponding LUN max geometry.

.. releasenotes/notes/bug-1765182-34fdc4bb8482f8a5.yaml @ b'792eea0a12bd97f69294ad0570ac330a3f1fe423'

- NetApp ONTAP (bug 1765182): Make ONTAP NetApp iSCSI driver and FC driver
  report to the Cinder scheduler that they don't support online volume
  extending.

.. releasenotes/notes/bug-1765182-bcafd577f4b81eb6.yaml @ b'f33b234aa02a2f682455cbc01758a7330d64e6ae'

- Make Cinder scheduler check if backend reports `online_extend_support`
  before performing an online extend operation.

.. releasenotes/notes/bug-1765182-de132ba52167800b.yaml @ b'40d50eccdef9cc1b42bb8e24e6b641b20213720d'

- NetApp ONTAP (bug 1765182): Make ONTAP NetApp NFS driver report to the
  Cinder scheduler that it doesn't support online volume extending.

.. releasenotes/notes/bug-1765610-qnap-fix-volume-snapshot-create-fail-2bb785eafdb87fb6.yaml @ b'880ff557ca3d6569464b9667ac25825cf5e3c7fd'

- Fixed QNAP driver failures to create volume and snapshot in some
  cases.

.. releasenotes/notes/bug-1766768-qnap-fix-upload-volume-detach-fail-33cbee59f1381bda.yaml @ b'ee9fda3e89b619c058768d5fa17cc3e9ecf4a99f'

- Fixed QNAP driver failures to detach iscsi device while uploading volume
  to image.

.. releasenotes/notes/bug-1773725-xtremio-remove-provisioning-factor-y7r5uy3489yd9pbf.yaml @ b'c157b547067389e697d6eea021de7e71535a62c9'

- The XtremIO driver has been fixed to correctly report the "free_capacity_gb" size.

.. releasenotes/notes/dell-emc-sc-bugfix-1756914-ffca3133273040f6.yaml @ b'f8980ea128dd6698a1cb3a283d98b47371b854f6'

- Dell EMC SC driver correctly returns initialize_connection data when more than one IQN is attached to a volume. This fixes some random Nova Live Migration failures where the connection information being returned was for an IQN other than the one for which it was being requested.

.. releasenotes/notes/fail-detach-lun-when-auto-zone-enabled-9c87b18a3acac9d1.yaml @ b'c816be897e7ab1c95b38979b2cc94ecf179e44e7'

- Dell EMC Unity Driver: Fixes `bug 1759175
  <https://bugs.launchpad.net/cinder/+bug/1759175>`__
  to detach the lun correctly when auto zone was enabled and the lun was the
  last one attached to the host.

.. releasenotes/notes/fix-abort-backup-df196e9dcb992586.yaml @ b'4ff9e63707e2c4cf5869f28e3e86fd0606d2db9a'

- We no longer leave orphaned chunks on the backup backend or leave a
  temporary volume/snapshot when aborting a backup.

.. releasenotes/notes/fix-cross-az-migration-ce97eff61280e1c7.yaml @ b'fb8085894b69f56091bde19683a919cb15d502cc'

- Resolve issue with cross AZ migrations and retypes where the destination
  volume kept the source volume's AZ, so we ended up with a volume where the
  AZ does not match the backend. (bug 1747949)

.. releasenotes/notes/fix-extend-volume-939e30f2e9e516bc.yaml @ b'c96f3997104f0dca4ed191e3df92715b33bd1a63'

- [`bug 1772421 <https://bugs.launchpad.net/keystone/+bug/1772421>`_]
  INFINIDAT fixed a bug in volume extension feature where volumes
  were not extended to target size but added the given target size.

.. releasenotes/notes/fix-import-backup-quota-issue-8yh69hd19u7tuu23.yaml @ b'4b4fbd35da26c7d697ddf18d3f0487f9ea817224'

- Cinder will now consume quota when importing new backup resource.

.. releasenotes/notes/fix-quota-deleting-temporary-volume-274e371b425e92cc.yaml @ b'8d9f8629013bcb880fb3e33f03b274c10befdab0'

- Fix a quota usage error triggered by a non-admin user backing up an
  in-use volume. The forced backup uses a temporary volume, and quota
  usage was incorrectly updated when the temporary volume was deleted
  after the backup operation completed.
  Fixes `bug 1778774 <https://bugs.launchpad.net/tripleo/+bug/1778774>`__.

.. releasenotes/notes/force-delete-mv-a53924f09c475386.yaml @ b'fe69f679369057a7c381178f770bf68d0bc1cee0'

- Volume "force delete" was introduced with the 3.23 API microversion,
  however the check for in the service was incorrectly looking for
  microversion 3.2. That check has now been fixed. It is possible that an API
  call using a microversion below 3.23 would previously work for this call,
  which will now fail. This closes
  `bug #1783028 <https://bugs.launchpad.net/cinder/+bug/1783028>`_.

.. releasenotes/notes/google-auth-for-gcs-backup-1642cd0e741fbdf9.yaml @ b'79d7a4e8da6f1118b5c235928876cf78085f4332'

- Google backup driver now works when using ``google-api-python-client`` version 1.6.0 or higher.

.. releasenotes/notes/migrate-backup-encryption-keys-to-barbican-6f07fd48d4937b2a.yaml @ b'341dd44ba796e933920da6718a2891e35ed88506'

- When encryption keys based on the ConfKeyManager's fixed_key are migrated
  to Barbican, ConfKeyManager keys stored in the Backup table are included
  in the migration process.
  Fixes `bug 1757235 <https://bugs.launchpad.net/tripleo/+bug/1757235>`__.

.. releasenotes/notes/modify-ensure-export-1d56a40f5e762aa8.yaml @ b'd5f79c52d886e962e1e42af4d892b35eec5bb81f'

- Storwize SVC Driver: Fixes `bug 1749687
  <https://bugs.launchpad.net/cinder/+bug/1749687>`__
  previously lsvdisk() was called separately for every
  'in-use' volume in order to check if the volume exists
  on the storage.
  In order to avoid problem of too long driver initialization
  now lsvdisk() is called once per pool.

.. releasenotes/notes/netapp-ontap-fix-force-detach-55be3f4ac962b493.yaml @ b'8776c81f64bfee814573f217b140408f57fb302d'

- Fixed bug #1783582, where calls to os-force_detach were failing on NetApp
  ONTAP iSCSI/FC drivers.

.. releasenotes/notes/netapp-ontap-use_exact_size-d03c90efbb8a30ac.yaml @ b'67391f1f0f30172190882e7d3f4a4ddc271dfa00'

- Fixed bug #1731474 on NetApp Data ONTAP driver that was causing LUNs to be created
  with larger size than requested. This fix requires version 9.1 of ONTAP
  or later.

.. releasenotes/notes/policy-for-type-list-and-show-apis-rt56uy78crt5e378.yaml @ b'44b4e5462a5652a58b141e7409f50431a12a7299'

- Two new policies "volume_extension:type_get" and "volume_extension:type_get_all" have been added to control type show and type list APIs.

.. releasenotes/notes/quobyte_vol-snap-cache-baf607f14d916ec7.yaml @ b'8c72fcadae92640331807f021401a7c250e56286'

- Added a new optional cache of volumes generated from snapshots for the
  Quobyte backend. Enabling this cache speeds up creation of multiple
  volumes from a single snapshot at the cost of a slight increase in
  creation time for the first volume generated for this given snapshot.
  The ``quobyte_volume_from_snapshot_cache`` option is off by default.

.. releasenotes/notes/ssl-cert-fix-42e8f263c15d5343.yaml @ b'512fd07124ea7210a6653e519e964a898a31d406'

- VMAX driver - fixes SSL certificate verification error.

.. releasenotes/notes/storwize-hyperswap-host-site-update-621e763768fab9ee.yaml @ b'b47b199c4f53870880299137c5bb5a079c8a7440'

- Updated the parameter storwize_preferred_host_site from StrOpt to DictOpt
  in cinder back-end configuration, and removed it from volume type
  configuration.

.. releasenotes/notes/sync-bump-versions-a1e6f6359173892e.yaml @ b'3cd2ebd3759c76fdf5a292e612127094c7aa2b17'

- After an offline upgrade we had to restart all Cinder services twice, now with the `cinder-manage db sync --bump-versions` command we can avoid the second restart.

.. releasenotes/notes/tpool-size-11121f78df24db39.yaml @ b'e570436d1cca5cfa89388aec8b2daa63d01d0250'

- Fixes concurrency issue on backups, where only 20 native threads could be concurrently be executed.  Now default will be 60, and can be changed with `backup_native_threads_pool_size`.

.. releasenotes/notes/tpool-size-11121f78df24db39.yaml @ b'e570436d1cca5cfa89388aec8b2daa63d01d0250'

- RBD driver can have bottlenecks if too many slow operations are happening at the same time (for example many huge volume deletions), we can now use the `backend_native_threads_pool_size` option in the RBD driver section to resolve the issue.

.. releasenotes/notes/unity-return-logged-out-initiator-6ab1f96f21bb284c.yaml @ b'1ef06d4a31c3010f170da20fcc823dd81e77c1a7'

- Dell EMC Unity Driver: Fixes `bug 1773305
  <https://bugs.launchpad.net/cinder/+bug/1773305>`__
  to return the targets which connect to the logged-out initiators. Then the
  zone manager could clean up the FC zone based on the correct target wwns.


.. _Rocky Series Release Notes_13.0.0_stable_rocky_Other Notes:

Other Notes
-----------

.. releasenotes/notes/json-schema-validation-0d22576bd556f4e0.yaml @ b'd98dbf4da8852b0726b87520511fcc16b1c75dd8'

- Added schema validation support using jsonschema `[json-schema-validation]`_
  for all supported v3 APIs.

  Following APIs were accepting boolean parameters with leading and trailing
  white spaces (for e.g. " true "). But now with schema validation support,
  all these boolean parameters henceforth will not accept leading and trailing
  whitespaces to maintain consistency.

  * Generic volume groups:

    * delete group: "POST /v3/{project_id}/groups/{group_id}/action"

    * failover replication: "POST /v3/{project_id}/groups/{group_id}/action"
  * Volume Snapshots:

    * create a snapshot: "POST /v3/{project_id}/snapshots"
  * Volume_actions:

    * set bootable: "POST /v3/{project_id}/volumes/{volume_id}/action"

    * volume readonly update: "POST /v3/{project_id}/volumes/{volume_id}/action"

  .. _`[json-schema-validation]`: https://blueprints.launchpad.net/cinder/+spec/json-schema-validation

.. releasenotes/notes/remove-cinder-manage-logs-cmds-40fb8f475b37fb2f.yaml @ b'adfda23b609aae482208966e8fd65f176d4bcd49'

- The "cinder-manage logs" commands have been removed.  Information
  previously gathered by these commands may be found in cinder service and
  syslog logs.

.. releasenotes/notes/vnx-perf-optimize-bd55dc3ef7584228.yaml @ b'b54e7ff3576e495c4a1ed95a3e307b897860209b'

- Dell EMC VNX driver: Enhances the performance of create/delete volume.


