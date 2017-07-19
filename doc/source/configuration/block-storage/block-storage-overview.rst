=========================================
Introduction to the Block Storage service
=========================================

The Block Storage service provides persistent block storage
resources that Compute instances can consume. This includes
secondary attached storage similar to the Amazon Elastic Block Storage
(EBS) offering. In addition, you can write images to a Block Storage
device for Compute to use as a bootable persistent instance.

The Block Storage service differs slightly from the Amazon EBS offering.
The Block Storage service does not provide a shared storage solution
like NFS. With the Block Storage service, you can attach a device to
only one instance.

The Block Storage service provides:

-  ``cinder-api`` - a WSGI app that authenticates and routes requests
   throughout the Block Storage service. It supports the OpenStack APIs
   only, although there is a translation that can be done through
   Compute's EC2 interface, which calls in to the Block Storage client.

-  ``cinder-scheduler`` - schedules and routes requests to the appropriate
   volume service. Depending upon your configuration, this may be simple
   round-robin scheduling to the running volume services, or it can be
   more sophisticated through the use of the Filter Scheduler. The
   Filter Scheduler is the default and enables filters on things like
   Capacity, Availability Zone, Volume Types, and Capabilities as well
   as custom filters.

-  ``cinder-volume`` - manages Block Storage devices, specifically the
   back-end devices themselves.

-  ``cinder-backup`` - provides a means to back up a Block Storage volume to
   OpenStack Object Storage (swift).

The Block Storage service contains the following components:

-  **Back-end Storage Devices** - the Block Storage service requires some
   form of back-end storage that the service is built on. The default
   implementation is to use LVM on a local volume group named
   "cinder-volumes." In addition to the base driver implementation, the
   Block Storage service also provides the means to add support for
   other storage devices to be utilized such as external Raid Arrays or
   other storage appliances. These back-end storage devices may have
   custom block sizes when using KVM or QEMU as the hypervisor.

-  **Users and Tenants (Projects)** - the Block Storage service can be
   used by many different cloud computing consumers or customers
   (tenants on a shared system), using role-based access assignments.
   Roles control the actions that a user is allowed to perform. In the
   default configuration, most actions do not require a particular role,
   but this can be configured by the system administrator in the
   appropriate ``policy.json`` file that maintains the rules. A user's
   access to particular volumes is limited by tenant, but the user name
   and password are assigned per user. Key pairs granting access to a
   volume are enabled per user, but quotas to control resource
   consumption across available hardware resources are per tenant.

   For tenants, quota controls are available to limit:

   -  The number of volumes that can be created.

   -  The number of snapshots that can be created.

   -  The total number of GBs allowed per tenant (shared between
      snapshots and volumes).

   You can revise the default quota values with the Block Storage CLI,
   so the limits placed by quotas are editable by admin users.

-  **Volumes, Snapshots, and Backups** - the basic resources offered by
   the Block Storage service are volumes and snapshots which are derived
   from volumes and volume backups:

   -  **Volumes** - allocated block storage resources that can be
      attached to instances as secondary storage or they can be used as
      the root store to boot instances. Volumes are persistent R/W block
      storage devices most commonly attached to the compute node through
      iSCSI.

   -  **Snapshots** - a read-only point in time copy of a volume. The
      snapshot can be created from a volume that is currently in use
      (through the use of ``--force True``) or in an available state.
      The snapshot can then be used to create a new volume through
      create from snapshot.

   -  **Backups** - an archived copy of a volume currently stored in
      Object Storage (swift).
