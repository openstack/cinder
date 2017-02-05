.. -*- rst -*-

====================================
Quota sets extension (os-quota-sets)
====================================

Administrators only, depending on policy settings.

Shows, updates, and deletes quotas for a project.


Show quotas for a user
======================

.. rest_method::  GET /v3/{admin_project_id}/os-quota-sets/{project_id}/{user_id}

Enables an admin user to show quotas for a project and user.


Normal response codes: 200
Error response codes:

Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - user_id: user_id
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
   - id: id
   - security_groups: security_groups

Response Example
----------------

.. literalinclude:: ./samples/quotas-update-response.json
   :language: javascript


Update quotas for a user
========================

.. rest_method::  PUT /v3/{admin_project_id}/os-quota-sets/{project_id}/{user_id}

Updates quotas for a project and user.


Normal response codes: 200
Error response codes:


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
   - id: id
   - security_groups: security_groups
   - project_id: project_id_path
   - user_id: user_id
   - admin_project_id: admin_project_id

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
   - id: id
   - security_groups: security_groups

Response Example
----------------

.. literalinclude:: ./samples/quotas-update-response.json
   :language: javascript

Delete quotas for a user
========================

.. rest_method::  DELETE /v3/{admin_project_id}/os-quota-sets/{project_id}/{user_id}

Deletes quotas for a user so that the quotas revert to default values.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - user_id: user_id
   - admin_project_id: admin_project_id

Response Example
----------------

.. literalinclude:: ./samples/quotas-delete-response.json
   :language: javascript


Show quotas for a project
=========================

.. rest_method::  GET /v3/{admin_project_id}/os-quota-sets/{project_id}

Shows quotas for a project.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
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
   - id: id
   - security_groups: security_groups


Response Example
----------------

.. literalinclude:: ./samples/quotas-show-response.json
   :language: javascript

Update quotas for a project
===========================

.. rest_method::  PUT /v3/{admin_project_id}/os-quota-sets/{project_id}

Updates quotas for a project.


Normal response codes: 200
Error response codes:


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
   - id: id
   - security_groups: security_groups
   - project_id: project_id_path
   - admin_project_id: admin_project_id

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
   - id: id
   - security_groups: security_groups

Response Example
----------------

.. literalinclude:: ./samples/quotas-update-response.json
   :language: javascript

Delete quotas for a project
===========================

.. rest_method::  DELETE /v3/{admin_project_id}/os-quota-sets/{project_id}

Deletes quotas for a project so the quotas revert to default values.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - admin_project_id: admin_project_id

Response Example
----------------

.. literalinclude:: ./samples/quotas-delete-response.json
   :language: javascript

Show quota details for a user
=============================

.. rest_method::  GET /v3/{admin_project_id}/os-quota-sets/{project_id}/detail/{user_id}

Shows details for quotas for a project and user.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - user_id: user_id
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
   - id: id
   - security_groups: security_groups

Response Example
----------------

.. literalinclude:: ./samples/quotas-update-response.json
   :language: javascript


Get default quotas for a project
================================

.. rest_method::  GET /v3/{project_id}/os-quota-sets/defaults

Gets default quotas for a project.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path


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
   - id: id
   - security_groups: security_groups


Response Example
----------------

.. literalinclude:: ./samples/quotas-show-defaults-response.json
   :language: javascript
