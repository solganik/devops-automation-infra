import logging
import time

from base_plugin import TunneledPlugin
from infra.model import plugins
from datetime import datetime
import random

from confluent_kafka import Consumer, Producer, TopicPartition
from confluent_kafka.admin import AdminClient, NewTopic, KafkaException

from pytest_automation_infra import helpers
from pytest_automation_infra.helpers import hardware_config

automation_tests_topic = 'anv.automation.topic1'


class Kafka(TunneledPlugin):
    def __init__(self, host):
        super().__init__(host)
        self.DNS_NAME = 'kafka.tls.ai' if not helpers.is_k8s(self._host.SSH) else 'kafka.default.svc.cluster.local'
        self.PORT = 9092
        self.start_tunnel(self.DNS_NAME, self.PORT)
        self.kafka_config = {'bootstrap.servers': f"localhost:{self.local_bind_port}", 'group.id': "automation-group",
                             'session.timeout.ms': 6000, 'auto.offset.reset': 'earliest'}

        self._kafka_admin = None
        self._c = None
        self._p = None

    @property
    def consumer(self):
        if self._c is None:
            self._c = Consumer(self.kafka_config)
        return self._c

    @property
    def producer(self):
        if self._p is None:
            self._p = Producer(self.kafka_config)
        return self._p

    @property
    def admin(self):
        if self._kafka_admin is None:
            self._kafka_admin = AdminClient(self.kafka_config)
        return self._kafka_admin

    def get_topics(self):
        topics = self.admin.list_topics(timeout=5)
        return topics.topics

    def create_topic(self, name):
        """create topic if not exists"""
        new_topic = NewTopic(name, num_partitions=3, replication_factor=1)
        fs = self.admin.create_topics([new_topic])
        for topic, f in fs.items():
            try:
                f.result()  # The result itself is None
                print("Topic {} created".format(topic))
                return True
            except KafkaException:
                # TODO: validate this exception is thrown only when topic exists and not in other cases
                # Othewise can add check before trying to create it...
                print("topic already exists")
                return True
            except Exception as e:
                print("Failed to create topic {}: {}".format(topic, e))
                raise

    def get_message(self, topics, tries=3):
        self.consumer.subscribe(topics)
        for i in range(tries):
            msg = self.consumer.poll(timeout=1)
            if msg is not None:
                return msg
        return None

    def consume_messages_x_times(self, topics, times):
        self.consumer.subscribe(topics)
        list_of_msg = []
        for i in range(times):
            msg = self.consumer.poll(timeout=1)
            if msg is not None:
                list_of_msg.append(msg)
        return list_of_msg

    def consume_iter(self, topics, timeout=None, commit=False):
        """ Generator - use Kafka consumer for receiving messages from the given *topics* list.
            Yield a tuple of each message key and value.
            If got a *timeout* argument - break the loop if passed the value in seconds, but did not
            received messages since the last one was processed.
            If the optional argument *commit* is true, commit each message consumed."""

        print(f'Started receiving messages (timeout: {timeout}).')

        self.consumer.subscribe(topics)
        last_ts = datetime.now()
        try:
            while (timeout is None) or ((datetime.now() - last_ts).seconds < timeout):
                msg = self.consumer.poll(timeout=1)
                if msg is None:
                    continue
                last_ts = datetime.now()
                if msg.error():
                    raise KafkaException(msg.error())
                else:
                    yield msg
                if commit is True and msg is not None:
                    offset = msg.offset()
                    if offset < 0:
                        offset = 0
                    tpo = TopicPartition(topic=msg.topic(), partition=msg.partition(), offset=offset)
                    self.consumer.commit(offsets=[tpo], asynchronous=True)

        except Exception as e:
            print(f"Error in consume_iter {e}")
        finally:
            logging.info(f"Stopping to consume topics {topics}")

    def parse_message(self, msg):
        key, value = msg.key().decode(), msg.value().decode()
        return key, value

    @staticmethod
    def delivery_report(err, msg):
        if err:
            raise Exception
        else:
            print(f"message {msg} put successfully")

    def put_message(self, topic, key, msg):
        self.producer.produce(topic=topic, key=key, value=msg, callback=self.delivery_report)
        self.producer.poll(0)

    def delete_topic(self, topic):
        fs = self.admin.delete_topics([topic], operation_timeout=30)

        # Wait for operation to finish.
        for topic, f in fs.items():
            try:
                f.result()  # The result itself is None
                print("Topic {} deleted".format(topic))
                return True
            except Exception as e:
                print("Failed to delete topic {}: {}".format(topic, e))

    def empty(self, topics):
        for msg in self.consume_iter(topics, timeout=5, commit=True):
            logging.debug(f"emptying message {msg}")
        # This is a double check to make sure topic is empty:
        time.sleep(5)
        assert self.get_message(topics) is None


plugins.register('Kafka', Kafka)


@hardware_config(hardware={"host": {}})
def test_basic(base_config):
    kafka = base_config.hosts.host.Kafka
    kafka.create_topic(automation_tests_topic)
    for i in range(10):
        kafka.put_message(automation_tests_topic, f'key{random.randint(0, 10)}', f"test {random.randint(10, 100)}")

    kafka.empty([automation_tests_topic])
