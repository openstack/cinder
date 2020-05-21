============================
Liberty Series Release Notes
============================

.. _Liberty Series Release Notes_7.0.3_stable_liberty:

7.0.3
=====

.. _Liberty Series Release Notes_7.0.3_stable_liberty_Security Issues:

Security Issues
---------------

.. releasenotes/notes/apply-limits-to-qemu-img-29f722a1bf4b91f8.yaml @ b'455b318ced717fb38dfe40014817d78fbc47dea5'

- The qemu-img tool now has resource limits applied which prevent it from using more than 1GB of address space or more than 2 seconds of CPU time. This provides protection against denial of service attacks from maliciously crafted or corrupted disk images.


.. _Liberty Series Release Notes_7.0.2_stable_liberty:

7.0.2
=====

.. _Liberty Series Release Notes_7.0.2_stable_liberty_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/glance_v2_upload-939c5693bcc25483.yaml @ b'01555a940d0f84d2fbc98cd10905ca6aabe00c48'

- upload-to-image using Image API v2 now correctly handles custom image properties.


.. _Liberty Series Release Notes_7.0.1_stable_liberty:

7.0.1
=====

.. _Liberty Series Release Notes_7.0.1_stable_liberty_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/a7401ead26a7c83b-keystone-url.yaml @ b'fa7d0916d849e9c6f93e08f8323eb2a886bcffc0'

- Cinder will now correctly read Keystone's endpoint for quota calls from keystone_authtoken.auth_uri instead of keymgr.encryption_auth_url config option.

.. releasenotes/notes/attach-failure-cleanup-c900497fce31410b.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- If device attachment failed it could leave the volume partially attached. Cinder now tries to clean up on failure.

.. releasenotes/notes/dell-sc-cgsnapshot-delete-7322950f925912c8.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- Fixed an issue when deleting a consistency group snapshot with the Dell SC backend driver.

.. releasenotes/notes/emc-scaleio-extend-volume-d7ecdb26f6e65825.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- ScaleIO volumes need to be sized in increments of 8G. Handling added to volume extend operations to ensure the new size is rounded up to the nearest size when needed.

.. releasenotes/notes/emc-scaleio-migration-44d554bb46158db2.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- Fixed issue with the EMC ScaleIO driver not able to identify a volume after a migration is performed.

.. releasenotes/notes/emc-scaleio-provisioning-type-f7542d50f62acecc.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- An error has been corrected in the EMC ScaleIO driver that had caused all volumes to be provisioned at 'thick' even if user had specificed 'thin'.

.. releasenotes/notes/emc-vmax-live-migration-bf960f4802979cae.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- Fixed an issue with live migration when using the EMC VMAX driver.

.. releasenotes/notes/emc-vmax-multiportgroup-7352386d5ffd3075.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- Removed restriction of hard coded iSCSI IP address to allow the use of multiple iSCSI portgroups.

.. releasenotes/notes/fix-keystone-quota-url-2018f32e80ed9fb5.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- Fixed an error in quota handling that required the keystone encryption_auth_url to be configured even if no encryption was being used.

.. releasenotes/notes/hnas-manage-spaces-eb1d05447536bf87.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- Allow spaces when managing existing volumes with the HNAS iSCSI driver.

.. releasenotes/notes/huawei-capacity-reporting-4f75ce622e57c28a.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- Capacity reporting fixed with Huawei backend drivers.

.. releasenotes/notes/lio-caseinsensitive-iqn-2324f7729d24a792.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- IQN identification is now case-insensitive when using LIO.

.. releasenotes/notes/netapp-volume-create-cleanup-c738114e42de1e69.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- Better cleanup handling in the NetApp E-Series driver.

.. releasenotes/notes/nimble-clone-extraspecs-27e2660f58b84f67.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- Fixed issue with extra-specs not being applied when cloning a volume.

.. releasenotes/notes/nimble-multi-initiator-8a3a58414c33f032.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- Add ability to enable multi-initiator support to allow live migration in the Nimble backend driver.

.. releasenotes/notes/subproject-quota-delete-3a22da070b578f8b.yaml @ b'c529bddcde41a0e70d1a20d4ead9c402e6c94d16'

- Fixed issue with error being raised when performing a delete quota operation in a subproject.


.. _Liberty Series Release Notes_7.0.1_stable_liberty_Other Notes:

Other Notes
-----------

.. releasenotes/notes/e99b24461613b6c8-start-using-reno.yaml @ b'62a79955eac7d1f247bea1ca479febb8b36349bc'

- Start using reno to manage release notes.


