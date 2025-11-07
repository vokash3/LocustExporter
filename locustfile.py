import locust
from locust import HttpUser, TaskSet, task, stats, constant_pacing

locust.stats.PERCENTILES_TO_CHART = [0.5, 0.9, 0.95, 0.99]
locust.stats.PERCENTILES_TO_STATISTICS = [0.5, 0.9, 0.95, 0.99]
locust.stats.CURRENT_RESPONSE_TIME_PERCENTILE_WINDOW = 2


class MyTasks(TaskSet):
    @task(1)
    def status_200(self):
        self.client.get("/200", name="status_200")

    @task(1)
    def status_404(self):
        self.client.get("/404", name="status_404")

    @task(1)
    def status_500(self):
        self.client.get("/500", name="status_500")

    @task(1)
    def status_301(self):
        self.client.get("/301", name="status_301")

    # Добавьте другие статус-коды по необходимости
    @task(1)
    def status_403(self):
        self.client.get("/403", name="status_403")


class WebsiteUser(HttpUser):
    tasks = [MyTasks]
    wait_time = constant_pacing(1)
