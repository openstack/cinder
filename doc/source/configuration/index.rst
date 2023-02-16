============================
Cinder Service Configuration
============================

.. toctree::
   :maxdepth: 1

   block-storage/block-storage-overview.rst
   block-storage/service-token.rst
   block-storage/volume-drivers.rst
   block-storage/backup-drivers.rst
   block-storage/schedulers.rst
   block-storage/logs.rst
   block-storage/policy-personas.rst
   block-storage/policy.rst
   block-storage/policy-config-HOWTO.rst
   block-storage/fc-zoning.rst
   block-storage/volume-encryption.rst
   block-storage/config-options.rst
   block-storage/samples/index.rst

.. warning::

   For security reasons **Service Tokens must to be configured** in OpenStack
   for Cinder to operate securely.  Pay close attention to the :doc:`specific
   section describing it: <block-storage/service-token>`. See
   https://bugs.launchpad.net/nova/+bug/2004555 for details.

.. note::

   The examples of common configurations for shared
   service and libraries, such as database connections and
   RPC messaging, can be seen in Cinder's sample configuration
   file: `cinder.conf.sample <../_static/cinder.conf.sample>`_.

The Block Storage service works with many different storage
drivers that you can configure by using these instructions.
