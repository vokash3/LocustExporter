import json
import logging
import sys
import time
import argparse

import requests
from prometheus_client import start_http_server, REGISTRY
from prometheus_client.metrics_core import GaugeMetricFamily, CounterMetricFamily

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger('LocustExporter')


class LocustExporter:
    def __init__(self, locust_host):
        self._host = locust_host

    def collect(self):
        url = self._host + '/stats/requests'
        try:
            response = requests.get(url).content.decode('Utf-8')
            response = json.loads(response)
            logger.info(f"Got metrics from Locust: {url}")
        except requests.exceptions.ConnectionError:
            logger.error(f"Failed to connect to Locust: {url}")
            return
        except json.decoder.JSONDecodeError:
            logger.warning(f"Wrong response from server: {url}")
            return

        yield GaugeMetricFamily('locust_current_response_time_percentile_50', '50 percentile Response Time',
                                response['current_response_time_percentile_1'])
        yield GaugeMetricFamily('locust_current_response_time_percentile_95', '95 percentile Response Time',
                                response['current_response_time_percentile_2'])
        yield GaugeMetricFamily('locust_fail_ratio', 'Current fail ratio', response['fail_ratio'])

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
                 'max_response_time', 'median_response_time', 'min_response_time', 'ninetieth_response_time',
                 'ninety_ninth_response_time',
                 'num_failures', 'num_requests']

        for req_metric in stats:

            if req_metric in ['num_requests', 'num_failures']:
                metric = CounterMetricFamily('locust_requests_' + req_metric,
                                             'Locust requests req_metric of ' + req_metric)
            else:
                metric = GaugeMetricFamily('locust_requests_' + req_metric,
                                           'Locust requests req_metric of ' + req_metric)
            for stat in response['stats']:
                if stat['name'] != 'Aggregated':
                    metric.add_sample('locust_requests_' + req_metric, value=stat[req_metric],
                                      labels={'name': stat['name'], 'method': stat['method']})
                else:
                    if stat['method']:
                        metric.add_sample('locust_requests_aggregated_' + req_metric, value=stat[req_metric],
                                          labels={'name': stat['name'], 'method': stat['method']})
            yield metric


def load_config(config_file):
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        print(f"Config file '{config_file}' not found.")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Invalid JSON format in config file '{config_file}'.")
        sys.exit(1)


if __name__ == '__main__':

    help = '''Path to configuration file in json format where \n1) port - where exporter will be available for 
    Prometheus \n2) host - where Locust master is up.\n
    Example of json config file: 
    {
        "port": 9191,
        "host": "http://localhost:8089"
    }'''

    parser = argparse.ArgumentParser(description='Locust Exporter for Prometheus')
    parser.add_argument('--config', help=help, required=True)
    try:
        args = parser.parse_args()

        config = load_config(args.config)
        port = config.get("port")
        host = config.get("host")
    except:
        parser.print_help()

    else:
        try:
            logger.info(f"Starting exporter server on {port}/TCP")
            start_http_server(int(port))
            logger.info("Connecting to locust on: " + host)
            REGISTRY.register(LocustExporter(host))
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            exit(0)
