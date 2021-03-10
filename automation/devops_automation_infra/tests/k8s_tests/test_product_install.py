import logging
import os

from devops_automation_infra.k8s_plugins.rancher import Rancher
from pytest_automation_infra.helpers import hardware_config


@hardware_config(hardware={"host1": {"hardware_type": "vm", "base_image": "gravity_infra_230"}},
                 grouping={"cluster1": {"hosts": ["host2"]}})
def test_install_bt(base_config):
    rancher = base_config.clusters.cluster1.Rancher
    rancher.cli_login()
    layer_name, version, catalog = "bettertomorrow-v2-data", "2.3.1-master", "online"
    rancher = Rancher(base_config.clusters.cluster1)
    rancher.add_catalog("https://chart.tls.ai/bettertomorrow-v2", "master",
                        catalog, os.environ.get("CATALOG_USERNAME"), os.environ.get("CATALOG_PASS"))
    rancher.refresh_catalog(catalog)
    rancher.install_app(app_name=layer_name, version=version, timeout=600)
    rancher.delete_app(layer_name)