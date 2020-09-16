#!/usr/bin/env python3

import ops.lib
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
)


pgsql = ops.lib.use("pgsql", 1, "postgresql-charmers@lists.launchpad.net")


def create_discourse_pod_config(config):
    pod_config = {
        'DISCOURSE_POSTGRES_USERNAME': config['db_user'],
        'DISCOURSE_POSTGRES_PASSWORD': config['db_password'],
        'DISCOURSE_POSTGRES_HOST': config['db_host'],
        'DISCOURSE_POSTGRES_NAME': config['db_name'],
        'DISCOURSE_DEVELOPER_EMAILS': config['developer_emails'],
        'DISCOURSE_HOSTNAME': config['external_hostname'],
        'DISCOURSE_SMTP_DOMAIN': config['smtp_domain'],
        'DISCOURSE_SMTP_ADDRESS': config['smtp_address'],
        'DISCOURSE_SMTP_PORT': config['smtp_port'],
        'DISCOURSE_SMTP_AUTHENTICATION': config['smtp_authentication'],
        'DISCOURSE_SMTP_OPENSSL_VERIFY_MODE': config['smtp_openssl_verify_mode'],
        'DISCOURSE_SMTP_USER_NAME': config['smtp_username'],
        'DISCOURSE_SMTP_PASSWORD': config['smtp_password'],
        'DISCOURSE_REDIS_HOST': config['redis_host'],
    }
    return pod_config


def create_ingress_config(app_name, config):
    ingressResource = {
        "name": app_name + "-ingress",
        "spec": {
            "rules": [
                {
                    "host": config['external_hostname'],
                    "http": {"paths": [{"path": "/", "backend": {"serviceName": app_name, "servicePort": 3000}}]},
                }
            ]
        },
    }
    return ingressResource


def get_pod_spec(app_name, config):
    pod_spec = {
        "version": 3,
        "containers": [
            {
                "name": app_name,
                "imageDetails": {"imagePath": config['discourse_image']},
                "imagePullPolicy": "IfNotPresent",
                "ports": [{"containerPort": 3000, "protocol": "TCP"}],
                "envConfig": create_discourse_pod_config(config),
                "kubernetes": {"readinessProbe": {"httpGet": {"path": "/srv/status", "port": 3000}}},
            }
        ],
        "kubernetesResources": {"ingressResources": [create_ingress_config(app_name, config)]},
    }
    # This handles when we are trying to get an image from a private
    # registry.
    if config['image_user'] and config['image_pass']:
        pod_spec['containers'][0]['imageDetails'].set("username", config['image_user'])
        pod_spec['containers'][0]['imageDetails'].set("password", config['image_pass'])

    return pod_spec


def check_for_config_problems(config):
    errors = []
    missing_fields = check_for_missing_config_fields(config)

    if len(missing_fields):
        errors.append('Required configuration missing: {}'.format(" ".join(missing_fields)))

    if config["db_host"] is None:
        errors.append("db relation is required")

    return errors


def check_for_missing_config_fields(config):
    missing_fields = []

    needed_fields = ['db_name', 'smtp_address', 'redis_host']
    for key in needed_fields:
        if len(config[key]) == 0:
            missing_fields.append(key)

    return sorted(missing_fields)


class DiscourseCharm(CharmBase):
    state = StoredState()

    def __init__(self, framework, key):
        super().__init__(framework, key)

        # TODO: is_started is unused. Remove?
        self.state.set_default(is_started=False, db_user=None, db_password=None, db_host=None)
        self.framework.observe(self.on.leader_elected, self.configure_pod)
        self.framework.observe(self.on.config_changed, self.configure_pod)
        self.framework.observe(self.on.upgrade_charm, self.configure_pod)

        self.db = pgsql.PostgreSQLClient(self, 'db')
        self.framework.observe(self.db.on.database_relation_joined, self.on_database_relation_joined)
        self.framework.observe(self.db.on_master_changed, self.on_database_changed)

    def check_config_is_valid(self, config):
        valid_config = True
        errors = check_for_config_problems(config)

        # set status if we have a bad config
        if errors:
            self.model.unit.status = BlockedStatus(", ".join(errors))
            valid_config = False
        else:
            self.model.unit.status = MaintenanceStatus("Configuration passed validation")

        return valid_config

    def configure_pod(self, event):
        # Set our status while we get configured.
        self.model.unit.status = MaintenanceStatus('Configuring pod')

        # Leader must set the pod spec.
        if self.model.unit.is_leader():
            # Merge our config and state into a single dict and set
            # defaults here, because the helpers avoid dealing with
            # the framework.
            config = dict(self.model.config)
            if not config["db_name"]:
                config["db_name"] = self.app.name
            config["db_user"] = self.state.db_user
            config["db_password"] = self.state.db_password
            config["db_host"] = self.state.db_host
            # Get our spec definition.
            if self.check_config_is_valid(config):
                # Get pod spec using our app name and config
                pod_spec = get_pod_spec(self.app.name, config)
                # Set our pod spec.
                self.model.pod.set_spec(pod_spec)

        self.state.is_started = True
        self.model.unit.status = ActiveStatus()

    # TODO: This is unused? Remove?
    def on_new_client(self, event):
        if not self.state.is_started:
            return event.defer()

        event.client.serve(hosts=[event.client.ingress_address], port=self.model.config['http_port'])

    def on_database_relation_joined(self, event):
        # Per https://github.com/canonical/ops-lib-pgsql/issues/2,
        # changing the setting in the config will not take effect,
        # unless the relation is dropped and recreated.
        event.database = self.model.config["db_name"]

    def on_database_changed(self, event):
        if event.master is None:
            self.state.db_user = None
            self.state.db_password = None
            self.state.db_host = None
            return

        self.state.db_user = event.master.user
        self.state.db_password = event.master.password
        self.state.db_host = event.master.host


if __name__ == '__main__':
    main(DiscourseCharm)