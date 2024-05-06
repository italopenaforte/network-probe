import json
import time

from prometheus_client.core import GaugeMetricFamily, REGISTRY
from prometheus_client import start_http_server

from helpers.redis_helper import RedisConnect
from helpers.logging_helper import setup_logging
from config import Config_Presentation


logger = setup_logging("logs/presentation.log")

class CustomCollector(object):
    def __init__(self):
        pass

    def collect(self):

        # Connect to Redis

        try:
            cache = RedisConnect()
        except Exception:
            logger.error("Could not connect to Redis")
            logger.debug("Could not connect to Redis",exc_info=1)

        if not cache:
            return

        if results := cache.redis_read(Config_Presentation.device_id):
            stats = json.loads(json.loads(results))
            logger.info(f"Logged device {Config_Presentation.device_id}")
        else:
            return

        g = GaugeMetricFamily("Network_Stats", 'Network statistics for latency and loss from the probe to the destination', labels=['site_id','type','target'])

        total_latency = 0 # Calculate these in presentation rather than prom to reduce cardinality
        total_loss = 0
        total_jitter = 0

        for item in stats['stats']: # Expose each individual latency / loss metric for each site tested

            g.add_metric([stats['site_id'],'latency',item['site']],item['latency'])
            g.add_metric([stats['site_id'],'loss',item['site']],item['loss'])
            g.add_metric([stats['site_id'],'jitter',item['site']],item['jitter'])

        for item in stats['stats']: # Aggregate all latency / loss metrics into one

            total_latency += float(item['latency'])
            total_loss += float(item['loss'])
            total_jitter += float(item['jitter'])

        average_latency = total_latency / len(stats['stats'])
        average_loss = total_loss / len(stats['stats'])
        average_jitter = total_jitter / len(stats['stats'])

        g.add_metric([stats['site_id'],'latency','all'],average_latency)
        g.add_metric([stats['site_id'],'loss','all'],average_loss)
        g.add_metric([stats['site_id'],'jitter','all'],average_jitter)

        yield g

        h = GaugeMetricFamily("DNS_Stats", 'DNS performance statistics for various DNS servers', labels=['site_id','server'])

        for item in stats['dns_stats']:
            h.add_metric([stats['site_id'],item['nameserver']],item['latency'])

            if item['nameserver'] == 'My_DNS_Server':
                my_dns_latency = float(item['latency']) # Grab the current DNS latency of the probe's DNS resolver

        yield h

        # Calculate overall health score

        weight_loss = Config_Presentation.weight_loss # Loss is 60% of score
        weight_latency = Config_Presentation.weight_latency # Latency is 15% of score
        weight_jitter = Config_Presentation.weight_jitter # Jitter is 20% of score
        weight_dns_latency = Config_Presentation.weight_dns_latency # DNS latency is 0.05 of score

        threshold_loss = Config_Presentation.threshold_loss # 5% loss threshold as max
        threshold_latency = Config_Presentation.threshold_latency # 100ms latency threshold as max
        threshold_jitter = Config_Presentation.threshold_jitter # 30ms jitter threshold as max
        threshold_dns_latency = Config_Presentation.threshold_dns_latency # 100ms dns latency threshold as max


        eval_loss = min(average_loss / threshold_loss, 1)
        eval_latency = min(average_latency / threshold_latency, 1)
        eval_jitter = min(average_jitter / threshold_jitter, 1)
        eval_dns_latency = min(my_dns_latency / threshold_dns_latency, 1)
        # Master scoring function

        score = 1 - weight_loss * (eval_loss) - weight_jitter * (eval_jitter) - weight_latency * (eval_latency) - weight_dns_latency * (eval_dns_latency)

        i = GaugeMetricFamily("Health_Stats", 'Overall internet health function', labels=['site_id'])
        i.add_metric([stats['site_id']],score)

        yield i


if __name__ == '__main__':

    start_http_server(Config_Presentation.presentation_port,addr=Config_Presentation.presentation_interface)

    REGISTRY.register(CustomCollector())
    while True:
        time.sleep(15)