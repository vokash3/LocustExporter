#!/bin/bash

locust -f locustfile.py --host=https://mock.httpstatus.io -u 10 -r 1 -t 300 --processes=2 --autostart