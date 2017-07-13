.. list-table:: Description of extra specs options for NetApp Unified Driver with Clustered Data ONTAP
   :header-rows: 1

   * - Extra spec
     - Type
     - Description
   * - ``netapp_raid_type``
     - String
     - Limit the candidate volume list based on one of the following raid
       types: ``raid4, raid_dp``.
   * - ``netapp_disk_type``
     - String
     - Limit the candidate volume list based on one of the following disk
       types: ``ATA, BSAS, EATA, FCAL, FSAS, LUN, MSATA, SAS, SATA, SCSI, XATA,
       XSAS, or SSD.``
   * - ``netapp:qos_policy_group`` [1]_
     - String
     - Specify the name of a QoS policy group, which defines measurable Service
       Level Objectives, that should be applied to the OpenStack Block Storage
       volume at the time of volume creation. Ensure that the QoS policy group
       object within Data ONTAP should be defined before an OpenStack Block
       Storage volume is created, and that the QoS policy group is not
       associated with the destination FlexVol volume.
   * - ``netapp_mirrored``
     - Boolean
     - Limit the candidate volume list to only the ones that are mirrored on
       the storage controller.
   * - ``netapp_unmirrored`` [2]_
     - Boolean
     - Limit the candidate volume list to only the ones that are not mirrored
       on the storage controller.
   * - ``netapp_dedup``
     - Boolean
     - Limit the candidate volume list to only the ones that have deduplication
       enabled on the storage controller.
   * - ``netapp_nodedup``
     - Boolean
     - Limit the candidate volume list to only the ones that have deduplication
       disabled on the storage controller.
   * - ``netapp_compression``
     - Boolean
     - Limit the candidate volume list to only the ones that have compression
       enabled on the storage controller.
   * - ``netapp_nocompression``
     - Boolean
     - Limit the candidate volume list to only the ones that have compression
       disabled on the storage controller.
   * - ``netapp_thin_provisioned``
     - Boolean
     - Limit the candidate volume list to only the ones that support thin
       provisioning on the storage controller.
   * - ``netapp_thick_provisioned``
     - Boolean
     - Limit the candidate volume list to only the ones that support thick
       provisioning on the storage controller.

.. [1]
   Please note that this extra spec has a colon (``:``) in its name
   because it is used by the driver to assign the QoS policy group to
   the OpenStack Block Storage volume after it has been provisioned.

.. [2]
   In the Juno release, these negative-assertion extra specs are
   formally deprecated by the NetApp unified driver. Instead of using
   the deprecated negative-assertion extra specs (for example,
   ``netapp_unmirrored``) with a value of ``true``, use the
   corresponding positive-assertion extra spec (for example,
   ``netapp_mirrored``) with a value of ``false``.
