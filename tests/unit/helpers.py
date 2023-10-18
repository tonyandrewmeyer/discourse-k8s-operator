# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""helpers for the unit tests."""

import contextlib
import typing
import unittest.mock

from ops.model import Container
from ops.testing import Harness

from charm import DiscourseCharm

DATABASE_NAME = "discourse"


def start_harness(
    *,
    with_postgres: bool = True,
    with_redis: bool = True,
    with_ingress: bool = False,
    with_config: typing.Optional[typing.Dict[str, typing.Any]] = None,
):
    """Start a harness discourse charm.

    This is also a workaround for the fact that Harness
    doesn't reinitialize the charm as expected.
    Ref: https://github.com/canonical/operator/issues/736

    Args:
        - with_postgres: should a postgres relation be added
        - with_redis: should a redis relation be added
        - with_ingress: should a ingress relation be added
        - with_config: apply some configuration to the charm

    Returns: a ready to use harness instance
    """
    harness = Harness(DiscourseCharm)
    harness.begin_with_initial_hooks()

    # We catch all exec calls to the container by default
    harness.handle_exec("discourse", [], result=0)

    if with_postgres:
        _add_postgres_relation(harness)

    if with_redis:
        _add_redis_relation(harness)
        harness.framework.reemit()

    if with_ingress:
        _add_ingress_relation(harness)

    if with_config is not None:
        harness.update_config(with_config)
        harness.container_pebble_ready("discourse")

    return harness


@contextlib.contextmanager
def _patch_setup_completed():
    """Patch filesystem calls in the _is_setup_completed and _set_setup_completed functions."""
    setup_completed = False

    def exists(*_args, **_kwargs):
        return setup_completed

    def push(*_args, **_kwargs):
        nonlocal setup_completed
        setup_completed = True

    with unittest.mock.patch.multiple(Container, exists=exists, push=push):
        yield


def _add_postgres_relation(harness):
    """Add postgresql relation and relation data to the charm.

    Args:
        - A harness instance

    Returns: the same harness instance with an added relation
    """

    relation_data = {
        "database": DATABASE_NAME,
        "endpoints": "dbhost:5432,dbhost-2:5432",
        "password": "somepasswd",  # nosec
        "username": "someuser",
    }

    # get a relation ID for the test outside of __init__
    harness.db_relation_id = (  # pylint: disable=attribute-defined-outside-init
        harness.add_relation("database", "postgresql")
    )
    harness.add_relation_unit(harness.db_relation_id, "postgresql/0")
    harness.update_relation_data(
        harness.db_relation_id,
        "postgresql",
        relation_data,
    )


def _add_redis_relation(harness):
    """Add redis relation and relation data to the charm.

    Args:
        - A harness instance

    Returns: the same harness instance with an added relation
    """
    redis_relation_id = harness.add_relation("redis", "redis")
    harness.add_relation_unit(redis_relation_id, "redis/0")
    # We need to bypass protected access to inject the relation data
    # pylint: disable=protected-access
    harness.charm._stored.redis_relation = {
        redis_relation_id: {"hostname": "redis-host", "port": 1010}
    }


def _add_ingress_relation(harness):
    """Add ingress relation and relation data to the charm.

    Args:
        - A harness instance

    Returns: the same harness instance with an added relation
    """
    nginx_route_relation_id = harness.add_relation("nginx-route", "ingress")
    harness.add_relation_unit(nginx_route_relation_id, "ingress/0")