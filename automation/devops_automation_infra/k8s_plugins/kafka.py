import kubernetes
from kubernetes.client import ApiException
import logging
import kafka
from kafka.errors import NoBrokersAvailable
from devops_automation_infra.k8s_plugins.kubectl import Kubectl
from devops_automation_infra.utils import kubectl
from infra.model import cluster_plugins
from automation_infra.utils import waiter


class Kafka:
    def __init__(self, cluster):
        self._cluster = cluster
        self._master = self._cluster.K8SMaster()
        self._namespace = 'default'
        self._name = 'kafka-cluster'

    @property
    def _is_exposed(self):
        try:
            self._bootstrap_endpoint()
        except ApiException as e:
            if e.status == 404:
                return False
            else:
                raise e

        return True

    @property
    def _is_running(self):
        return kubectl.is_stateful_set_ready(name='kafka-cluster-kafka', client=self._cluster.Kubectl.client())

    def _list_broker_pods(self):
        return kubectl.get_pods_by_label(self._cluster.Kubectl.client(),
                                         namespace=self._namespace, label='strimzi.io/name=kafka-cluster-kafka')

    def _expose(self):
        if self._is_exposed:
            return

        logging.debug("Exposing kafka cluster")
        custom_object_client = kubernetes.client.CustomObjectsApi(self._cluster.Kubectl.client())
        kafka_spec = custom_object_client.get_namespaced_custom_object(namespace=self._namespace,
                                                                       group='kafka.strimzi.io',
                                                                       version='v1beta1',
                                                                       plural='kafkas',
                                                                       name=self._name)['spec']
        advertised_brokers = {'brokers': []}
        for i in range(0, kafka_spec['kafka']['replicas']):
            advertised_brokers['brokers'].append({'broker': i, 'advertisedHost': self._master.ip})

        kafka_spec['kafka']['listeners']['external'] = {'type': 'nodeport', 'tls': False, 'overrides': advertised_brokers}

        pods_timestamps = [pod.status.start_time for pod in self._list_broker_pods()]
        custom_object_client.patch_namespaced_custom_object(namespace=self._namespace,
                                                            group='kafka.strimzi.io',
                                                            version='v1beta1',
                                                            plural='kafkas',
                                                            name=self._name,
                                                            body={'spec': kafka_spec})

        logging.debug("Waiting for kafka brokers to restart")
        waiter.wait_for_predicate(lambda: [pod.status.start_time for pod in self._list_broker_pods()] != pods_timestamps, timeout=30)
        waiter.wait_for_predicate(lambda: self._is_running is True, timeout=30)


    def _add_default_options(self, kwargs):
        options = {'bootstrap_servers': self._bootstrap_endpoint()}
        options.update(kwargs)
        return options

    def _bootstrap_endpoint(self):
        v1 = kubernetes.client.CoreV1Api(self._cluster.Kubectl.client())
        port = v1.read_namespaced_service(namespace=self._namespace, name='kafka-cluster-kafka-external-bootstrap').spec.ports[0].node_port
        return f"{self._master.ip}:{port}"

    def admin(self, **kwargs):
        self._expose()
        options = self._add_default_options(kwargs)
        return kafka.KafkaAdminClient(**options)

    def consumer(self, **kwargs):
        self._expose()
        options = self._add_default_options(kwargs)
        return kafka.KafkaConsumer(**options)

    def producer(self, **kwargs):
        self._expose()
        options = self._add_default_options(kwargs)
        return kafka.KafkaProducer(**options)

    def ping(self):
        return self.consumer().topics()


cluster_plugins.register('Kafka', Kafka)

