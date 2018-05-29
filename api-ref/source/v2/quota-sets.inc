.. -*- rst -*-

Quota sets extension (os-quota-sets)
====================================

Administrators only, depending on policy settings.

Shows, updates, and deletes quotas for a project.

Show quotas
~~~~~~~~~~~

.. rest_method::  GET /v2/{admin_project_id}/os-quota-sets/{project_id}

Shows quotas for a project.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: quotas_project_id
   - admin_project_id: admin_project_id
   - usage: usage


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: project_id
   - security_groups: security_groups


Response Example
----------------

.. literalinclude:: ./samples/quotas-show-response.json
   :language: javascript

Update quotas
~~~~~~~~~~~~~

.. rest_method::  PUT /v2/{admin_project_id}/os-quota-sets/{project_id}

Updates quotas for a project.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - security_groups: security_groups
   - project_id: quotas_project_id
   - admin_project_id: admin_project_id
   - backup_gigabytes: backup_gigabytes
   - per_volume_gigabytes: per_volume_gigabytes

Request Example
---------------

.. literalinclude:: ./samples/quotas-update-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: project_id
   - security_groups: security_groups

Response Example
----------------

.. literalinclude:: ./samples/quotas-update-response.json
   :language: javascript

Delete quotas
~~~~~~~~~~~~~

.. rest_method::  DELETE /v2/{admin_project_id}/os-quota-sets/{project_id}

Deletes quotas for a project so the quotas revert to default values.

Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: quotas_project_id
   - admin_project_id: admin_project_id

Response Example
----------------

.. literalinclude:: ./samples/quotas-delete-response.json
   :language: javascript

Get default quotas
~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{admin_project_id}/os-quota-sets/{project_id}/defaults

Gets default quotas for a project.


Response codes
--------------

.. rest_status_code:: success ../status.yaml

   - 200


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: quotas_project_id
   - admin_project_id: admin_project_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: project_id
   - security_groups: security_groups


Response Example
----------------

.. literalinclude:: ./samples/quotas-show-defaults-response.json
   :language: javascript
