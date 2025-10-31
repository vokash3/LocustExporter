import argparse
import json
import logging
import os
import time

import requests
from prometheus_client import start_http_server, REGISTRY
from prometheus_client.metrics_core import GaugeMetricFamily, CounterMetricFamily

METRIC_TYPE_MAP = {
    "gauge": GaugeMetricFamily,
    "counter": CounterMetricFamily
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_json_value(data, path):
    for key in path:
        if isinstance(data, dict):
            data = data.get(key)
        else:
            return None
        if data is None:
            return None
    return data


class LocustExporter:
    def __init__(self, locust_host, metrics_config):
        self._host = locust_host
        self._metrics = metrics_config

    def collect(self):
        url = self._host + '/stats/requests'
        try:
            response = requests.get(url).content.decode('Utf-8')
            response = json.loads(response)
            logging.info(f"Got metrics from Locust: {url}")
            logging.debug(f"{json.dumps(response, ensure_ascii=False, indent=4)}")
        except requests.exceptions.ConnectionError:
            logging.error(f"Failed to connect to Locust: {url}")
            return
        except json.decoder.JSONDecodeError:
            logging.warning(f"Wrong response from server: {url}")
            return

        if 'current_response_time_percentiles' in response:
            yield GaugeMetricFamily('locust_current_response_time_percentile_95', '95 percentile Response Time',
                                    response['current_response_time_percentiles']['response_time_percentile_0.95'])
        else:
            yield GaugeMetricFamily('locust_current_response_time_percentile_50', '50 percentile Response Time',
                                    response['current_response_time_percentile_1'])
            yield GaugeMetricFamily('locust_current_response_time_percentile_95', '95 percentile Response Time',
                                    response['current_response_time_percentile_2'])

        yield GaugeMetricFamily('locust_fail_ratio', 'Current fail ratio', response['fail_ratio'])

        if 'total_avg_response_time' in response:
            yield GaugeMetricFamily('locust_total_avg_response_time', 'Total avarage response time',
                                    response['total_avg_response_time'])
        else:
            pass

        gauge = GaugeMetricFamily('locust_state', 'Locust state: spawning, running etc ...')
        gauge.add_sample('locust_state', value=1 if response['state'] in ['running', 'spawning', 'cleanup'] else 0,
                         labels={'state': response['state']})
        yield gauge

        yield GaugeMetricFamily('locust_total_fail_per_sec', 'Current total fail per second ...',
                                response['total_fail_per_sec'])
        yield GaugeMetricFamily('locust_total_rps', 'Total RPS', response['total_rps'])
        yield GaugeMetricFamily('locust_user_count', 'Current number of users', response['user_count'])

        gauge = GaugeMetricFamily('locust_errors', 'Locust requests errors')
        for error in response['errors']:
            gauge.add_sample('locust_errors', value=error['occurrences'],
                             labels={'name': error['name'], 'method': error['method'], 'error': error['error']})
        yield gauge

        if 'workers' in response:
            gauge = GaugeMetricFamily('locust_workers_info', 'Extra info about workers')
            for worker in response['workers']:
                gauge.add_sample(name=f'locust_workers_info',
                                 labels={'cpu_usage': str(worker['cpu_usage']),
                                         'memory_usage': str(worker['memory_usage']),
                                         'user_count': str(worker['user_count']),
                                         'state': worker['state'],
                                         'id': worker['id']},
                                 value=1)
            yield gauge

        if 'workers' in response:
            yield GaugeMetricFamily('locust_workers', 'Locust number of workers', len(response['workers']))

        stats = ['avg_content_length', 'avg_response_time', 'current_fail_per_sec', 'current_rps',
                 'max_response_time', 'median_response_time', 'min_response_time', 'num_failures', 'num_requests',
                 'response_time_percentile_0.95',
                 'response_time_percentile_0.99']

        for req_metric in stats:

            if req_metric in ['num_requests', 'num_failures']:
                metric = CounterMetricFamily('locust_requests_' + req_metric,
                                             'Locust requests req_metric of ' + req_metric)
            else:
                metric = GaugeMetricFamily('locust_requests_' + req_metric.replace('0.', ''),
                                           'Locust requests req_metric of ' + req_metric.replace('0.', ''))
            for stat in response['stats']:
                if stat['name'] != 'Aggregated':
                    metric.add_sample('locust_requests_' + req_metric.replace('0.', ''), value=stat[req_metric],
                                      labels={'name': stat['name'], 'method': stat['method']})
            yield metric


if __name__ == '__main__':

    help = '''Path to configuration file in json format where \n1) port - where exporter will be available for 
    Prometheus \n2) host - where Locust master is up.\n
    Example of json config file: 
    {
        "port": 9191,
        "host": "http://localhost:8089"
    }\n\n\n If You don't wanna use config file U can use env vars EXPORTER_PORT and LOCUST_HOST'''

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Locust Prometheus Exporter (Config-driven)")
    parser.add_argument("--config", help="Path to exporter config (json)")
    args = parser.parse_args()

    # Чтение основного конфига
    config_path = args.config or os.getenv("EXPORTER_CONFIG", "config.json")
    config = load_json(config_path)
    port = config.get("exporter_port", 9191)
    host = config.get("locust_host", "http://localhost:8089")
    metrics_path = config.get("metrics_config", "metrics_config.json")
    log_level = config.get("log_level", "INFO")

    logging.basicConfig(level=getattr(logging, log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(message)s")
    logging.info(f"Loaded exporter config: {config_path}")

    # Чтение метрик
    metrics_config = load_json(metrics_path).get("metrics", [])
    logging.info(f"Loaded metrics config: {metrics_path}")

    logging.info(f"Starting exporter server on {port}/TCP")
    start_http_server(int(port))
    logging.info("Connecting to Locust on: " + host)
    REGISTRY.register(LocustExporter(host, metrics_config))
    while True:
        time.sleep(1)
