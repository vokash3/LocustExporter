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
        metrics = self._metrics
        url = self._host + 'stats/requests'
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

        # ===============LOCUST STATE SECTION ===============
        gauge = GaugeMetricFamily('locust_state', 'Locust state: spawning, running etc ...')
        gauge.add_sample('locust_state', value=1 if response['state'] in ['running', 'spawning', 'cleanup'] else 0,
                         labels={'state': response['state']})
        yield gauge

        # ===============GLOBAL STATS SECTION ===============
        if global_stats := metrics.get('global_stats'):
            for gs in global_stats:
                try:
                    if gs['path'] in response:  # from metrics_config.json
                        yield GaugeMetricFamily(gs['name'], gs['documentation'], response[gs['path']])
                except KeyError:
                    logging.error("Error getting global stats for " + gs['name'])

        # ===============REQUESTS STATS SECTION ===============
        if stats := metrics.get('requests_stats'):  # from metrics_config.json
            for req_metric in stats:
                try:
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
                except KeyError:
                    logging.error("Error getting requests stats for " + req_metric)

        # ===============OVERALL RESPONSE TIME SECTION ===============
        if overall_rt := metrics.get('extra').keys():
            for extra in overall_rt:  # if you customize stats: https://docs.locust.io/en/stable/configuration.html#customization-of-statistics-settings
                if extra in response:  # from metrics_config.json
                    m: list = metrics['extra'][extra]
                    for f in m:
                        if rt:= response[extra].get('path', "") == f['path']:
                            yield GaugeMetricFamily(f['name'], f['documentation'], rt)

        # ===============WORKERS SECTION ===============
        if 'workers' in response:  # when U use https://docs.locust.io/en/stable/running-distributed.html
            gauge = GaugeMetricFamily('locust_workers_info', 'Extra info about workers')
            for worker in response['workers']:
                gauge.add_sample(name=f'locust_workers_info',
                                 labels={'cpu_usage': str(worker['cpu_usage']),
                                         'memory_usage': str(worker['memory_usage']),
                                         'user_count': str(worker['user_count']),
                                         'state': worker['state'],
                                         'id': worker['id']},
                                 value=1)
            yield GaugeMetricFamily('locust_workers', 'Locust number of workers', len(response['workers']))
            yield gauge

        # ===============ERRORS SECTION ===============
        gauge = GaugeMetricFamily('locust_errors', 'Locust requests errors')
        for error in response['errors']:
            gauge.add_sample('locust_errors', value=error['occurrences'],
                             labels={'name': error['name'], 'method': error['method'], 'error': error['error']})
        yield gauge


if __name__ == '__main__':
    help_str = '''
    Path to configuration file in json format where \n
    1) port - where exporter will be available for Prometheus \n
    2) host - where Locust master is up.\n
        Example of json config file (config.json):\n: 
        {
              "exporter_port": 9191,
              "locust_host": "http://localhost:8089",
              "metrics_config": "metrics_config.json",
              "log_level": "INFO"
        }\n\n\n 
    If You don't wanna use config file U can use env vars EXPORTER_PORT and LOCUST_HOST\n\n\n
    
    (!) DO NOT DELETE metrics_config.json file\n'''

    parser = argparse.ArgumentParser(description='Locust Exporter for Prometheus')
    parser.add_argument('--config', help=help_str, required=False)
    # DEFAULT VALUES
    port = os.getenv('EXPORTER_PORT', '9191')
    host = os.getenv('LOCUST_HOST', 'http://localhost:8089/')
    metrics_path = os.getenv("METRICS_PATH", "metrics_config.json")

    args = parser.parse_args()

    if config_path := args.config or os.getenv("EXPORTER_CONFIG", "config.json"):
        try:
            # Чтение основного конфига
            config = load_json(config_path)
            port = config.get("exporter_port", 9191)
            host = config.get("locust_host", "http://localhost:8089/")
            metrics_path = config.get("metrics_config", "metrics_config.json")
            log_level = config.get("log_level", "INFO")

            logging.basicConfig(level=getattr(logging, log_level, logging.INFO),
                                format="%(asctime)s %(levelname)s %(message)s")
            logging.info(f"Loaded exporter config: {config_path}")

            logging.info(f'''Used CONFIG:\n
                                {config}\n''')
        except Exception as e:
            parser.print_help()
    else:
        log_level = "INFO"
        logging.basicConfig(level=getattr(logging, log_level, logging.INFO),
                            format="%(asctime)s %(levelname)s %(message)s")
        logging.info(f'''Used ENVIRONMENT variables:\n
                                                    EXPORTER_PORT={port}\n
                                                    LOCUST_HOST={host}\n
                                                    METRICS={metrics_path}\n
                                                    EXPORTER_LOGLEVEL={log_level}\n
                                                    ''')
    try:
        # Чтение метрик
        metrics_config = load_json(metrics_path)
        logging.info(f"Loaded metrics config: {metrics_path}")

        logging.info(f"Starting exporter server on {port}/TCP")
        start_http_server(int(port))
        logging.info("Connecting to Locust on: " + host)
        REGISTRY.register(LocustExporter(host, metrics_config))
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Stopping exporter server")
        exit(0)
    except Exception as e:
        logging.exception("Unexpected error:", e)
