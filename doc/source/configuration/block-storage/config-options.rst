==================
Additional options
==================

These options can also be set in the ``cinder.conf`` file.

.. config-table::
   :config-target: API
   :exclusive-list: api_opts,compute_opts,socket_opts

   cinder.api.common
   cinder.common.config
   cinder.compute
   cinder.service
   cinder.wsgi.eventlet_server

.. config-table::
   :config-target: [oslo_middleware]

   oslo_middleware.http_proxy_to_wsgi
   oslo_middleware.sizelimit
   oslo_middleware.ssl

.. config-table::
   :config-target: authorization
   :exclusive-list: auth_opts

   cinder.common.config

.. config-table::
   :config-target: Volume Manager

   cinder.volume.manager

.. config-table::
   :config-target: Volume Scheduler

   cinder.scheduler.manager
   cinder.scheduler.host_manager
   cinder.scheduler.driver
   cinder.scheduler.weights.volume_number
   cinder.scheduler.weights.capacity

.. config-table::
   :config-target: backup
   :exclusive-list: backup_opts,backup_manager_opts

   cinder.common.config
   cinder.backup.api
   cinder.backup.chunkeddriver
   cinder.backup.driver
   cinder.backup.manager
   cinder.db.api

.. config-table::
   :config-target: [nova]

   cinder.compute.nova

.. config-table::
   :config-target: images
   :exclusive-list: image_opts,glance_core_properties_opts

   cinder.image.glance
   cinder.image.image_utils
   cinder.volume.driver
   cinder.common.config

.. config-table::
   :config-target: NAS

   cinder.volume.drivers.remotefs

.. config-table::
   :config-target: common driver
   :exclusive-list: volume_opts

   cinder.volume.driver

.. _cinder-storage:

.. config-table::
   :config-target: common
   :exclusive-list: global_opts

   cinder.common.config

.. config-table::
   :config-target: [profiler]

   osprofiler.opts

.. config-table::
   :config-target: quota

   cinder.quota

.. config-table::
   :config-target: SAN

   cinder.volume.drivers.san.san

.. config-table::
   :config-target: iSER volume driver
   :exclusive-list: iser_opts

   cinder.volume.driver

.. config-table::
   :config-target: NVMET volume driver
   :exclusive-list: nvmet_opts

   cinder.volume.driver

.. config-table::
   :config-target: SCST volume driver
   :exclusive-list: scst_opts

   cinder.volume.driver

.. config-table::
   :config-target: zones
   :exclude-list: allow_force_upload_opt,volume_host_opt,az_cache_time_opt

   cinder.volume.api
